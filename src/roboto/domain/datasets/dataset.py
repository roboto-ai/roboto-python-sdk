# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import functools
import importlib.metadata
import os
import pathlib
import typing

import pathspec

from ...association import Association
from ...auth import Permissions
from ...env import RobotoEnv
from ...exceptions import (
    RobotoInvalidRequestException,
    RobotoNotFoundException,
)
from ...http import PaginatedList, RobotoClient
from ...logging import default_logger
from ...paths import (
    excludespec_from_patterns,
    path_to_pattern,
)
from ...query import QuerySpecification
from ...updates import (
    MetadataChangeset,
    StrSequence,
    UpdateCondition,
)
from ..events import Event
from ..files import (
    DirectoryRecord,
    File,
    FileRecord,
)
from ..files.file_service import FileService
from ..files.progress import (
    TqdmProgressMonitorFactory,
)
from ..topics import Topic
from .operations import (
    BeginManifestTransactionRequest,
    BeginManifestTransactionResponse,
    CreateDatasetRequest,
    QueryDatasetFilesRequest,
    RenameDirectoryRequest,
    RenameFileRequest,
    ReportTransactionProgressRequest,
    UpdateDatasetRequest,
)
from .record import (
    DatasetBucketAdministrator,
    DatasetCredentials,
    DatasetRecord,
    DatasetStorageLocation,
    TransactionRecord,
)

logger = default_logger()


MAX_FILES_PER_MANIFEST = 500


class Dataset:
    __roboto_client: RobotoClient
    __record: DatasetRecord
    __temp_credentials: typing.Optional[DatasetCredentials] = None
    __transaction_manifests: dict[str, set[str]]
    __transaction_completed_unreported_items: dict[str, set[str]]
    __manifest_reporting_increments: int = 10
    __manifest_reporting_min_batch_size: int = 10

    @classmethod
    def create(
        cls,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Dataset":
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDatasetRequest(
            description=description, metadata=metadata or {}, tags=tags or []
        )
        record = roboto_client.post(
            "v1/datasets", data=request, caller_org_id=caller_org_id
        ).to_record(DatasetRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, dataset_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "Dataset":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/datasets/{dataset_id}").to_record(DatasetRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator["Dataset", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec if spec is not None else QuerySpecification()

        known = set(DatasetRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # Support dot notation for nested fields
            # E.g., "metadata.SoftwareVersion"
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = (
                "are not known attributes of Dataset"
                if plural
                else "is not a known attribute of Dataset"
            )
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        while True:
            paginated_results = roboto_client.post(
                "v1/datasets/query",
                data=spec,
                owner_org_id=owner_org_id,
                idempotent=True,
            ).to_paginated_list(DatasetRecord)

            for record in paginated_results.items:
                yield cls(record, roboto_client)

            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self, record: DatasetRecord, roboto_client: typing.Optional[RobotoClient] = None
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record
        self.__transaction_manifests = {}
        self.__transaction_completed_unreported_items = {}

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def dataset_id(self) -> str:
        return self.__record.dataset_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        return self.__record.metadata.copy()

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def record(self) -> DatasetRecord:
        return self.__record

    @property
    def tags(self) -> list[str]:
        return self.__record.tags.copy()

    def delete(self) -> None:
        self.__roboto_client.delete(f"v1/datasets/{self.dataset_id}")

    def delete_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> None:
        """
        Delete files associated with this dataset.

        `include_patterns` and `exclude_patterns` are lists of gitignore-style patterns.
        See https://git-scm.com/docs/gitignore.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.delete_files(
            ...    include_patterns=["**/*.png"],
            ...    exclude_patterns=["**/back_camera/**"]
            ... )
        """
        for file in self.list_files(include_patterns, exclude_patterns):
            file.delete()

    def download_files(
        self,
        out_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> None:
        """
        Download files associated with this dataset to the given directory.
        If `out_path` does not exist, it will be created.

        `include_patterns` and `exclude_patterns` are lists of gitignore-style patterns.
        See https://git-scm.com/docs/gitignore.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.download_files(
            ...     pathlib.Path("/tmp/tmp.nV1gdW5WHV"),
            ...     include_patterns=["**/*.g4"],
            ...     exclude_patterns=["**/test/**"]
            ... )
        """
        if (
            self.__record.storage_location != DatasetStorageLocation.S3
            or self.__record.administrator != DatasetBucketAdministrator.Roboto
        ):
            raise NotImplementedError(
                "Only S3-backed storage administered by Roboto is supported at this time."
            )

        if not out_path.is_dir():
            out_path.mkdir(parents=True)

        def _credential_provider():
            return self.get_temporary_credentials(
                Permissions.ReadOnly
            ).to_s3_credentials()

        def _file_to_download_tuple(f: File) -> tuple[FileRecord, pathlib.Path]:
            return f.record, out_path / f.relative_path

        all_files = list(self.list_files(include_patterns, exclude_patterns))

        def _file_generator():
            for x in map(
                _file_to_download_tuple,
                all_files,
            ):
                yield x

        self.__file_service().download_files(
            file_generator=_file_generator(),
            credential_provider=_credential_provider,
            progress_monitor_factory=TqdmProgressMonitorFactory(
                concurrency=1,
                ctx={
                    "base_path": self.dataset_id,
                    "total_file_count": len(all_files),
                },
            ),
            max_concurrency=8,
        )

    def get_events(
        self, transitive: bool = False
    ) -> collections.abc.Generator[Event, None, None]:
        return Event.get_by_dataset(
            dataset_id=self.dataset_id,
            transitive=transitive,
            roboto_client=self.__roboto_client,
        )

    def get_file_by_path(
        self,
        relative_path: typing.Union[str, pathlib.Path],
    ) -> File:
        """
        Get a File object for the given relative path.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> file = dataset.get_file_by_path("foo/bar.txt")
            >>> print(file.file_id)
            file-abc123
        """
        escaped_path = path_to_pattern(str(relative_path))

        matching = list(self.list_files(include_patterns=[escaped_path]))
        if not matching:
            raise RobotoNotFoundException(
                f"File '{escaped_path}' not found in dataset '{self.dataset_id}'"
            )

        if len(matching) > 1:
            raise RobotoInvalidRequestException(
                f"Multiple files found for '{relative_path}' in dataset '{self.dataset_id}'"
            )

        return matching[0]

    def get_temporary_credentials(
        self,
        permissions: Permissions = Permissions.ReadOnly,
        force_refresh: bool = False,
        transaction_id: typing.Optional[str] = None,
    ) -> DatasetCredentials:
        """
        Effectively protected, this is exposed for specific Roboto internal scenarios, but should generally be avoided
        unless you have a very compelling use case.
        """
        if (
            force_refresh
            or permissions == Permissions.ReadWrite
            or self.__temp_credentials is None
            or self.__temp_credentials.is_expired()
        ):
            query_params = {"mode": permissions.value}

            if transaction_id:
                query_params["transaction_id"] = transaction_id

            return self.__roboto_client.get(
                f"v1/datasets/{self.dataset_id}/credentials", query=query_params
            ).to_record(DatasetCredentials)

        return self.__temp_credentials

    def get_topics(self) -> collections.abc.Generator[Topic, None, None]:
        """
        List all topics associated with files in this dataset. If multiple files have topics with the same name (i.e.
        if a dataset has chunked files with the same schema), they'll be returned as separate topic objects.
        """
        return Topic.get_by_dataset(self.dataset_id, self.__roboto_client)

    def get_topics_by_file(
        self, relative_path: typing.Union[str, pathlib.Path]
    ) -> collections.abc.Generator[Topic, None, None]:
        file = self.get_file_by_path(relative_path)
        return file.get_topics()

    def list_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> collections.abc.Generator[File, None, None]:
        """
        List files associated with this dataset.

        `include_patterns` and `exclude_patterns` are lists of gitignore-style patterns.
        See https://git-scm.com/docs/gitignore.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> for file in dataset.list_files(
            ...     include_patterns=["**/*.g4"],
            ...     exclude_patterns=["**/test/**"]
            ... ):
            ...     print(file.relative_path)
        """

        page_token: typing.Optional[str] = None
        while True:
            paginated_results = self.__list_files_page(
                page_token=page_token,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
            for record in paginated_results.items:
                yield File(record, self.__roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def put_metadata(
        self,
        metadata: dict[str, typing.Any],
    ) -> None:
        """
        Set each `key`: `value` in this dict as dataset metadata if it doesn't exist, else overwrite the existing value.
        Keys must be strings. Dot notation is supported for nested keys.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.put_metadata({
            ...     "foo": "bar",
            ...     "baz.qux": 101,
            ... })

        """
        self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(
        self,
        tags: StrSequence,
    ) -> None:
        """Add each tag in this sequence if it doesn't exist"""
        self.update(
            metadata_changeset=MetadataChangeset(put_tags=tags),
        )

    def refresh(self) -> "Dataset":
        """Refresh the underlying dataset record with the latest server state."""
        self.__record = self.__roboto_client.get(
            f"v1/datasets/{self.dataset_id}"
        ).to_record(DatasetRecord)
        return self

    def remove_metadata(
        self,
        metadata: StrSequence,
    ) -> None:
        """
        Remove each key in this sequence from dataset metadata if it exists.
        Keys must be strings. Dot notation is supported for nested keys.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.remove_metadata(["foo", "baz.qux"])
        """
        self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(
        self,
        tags: StrSequence,
    ) -> None:
        """Remove each tag in this sequence if it exists"""
        self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    def to_association(self) -> Association:
        return Association.dataset(self.dataset_id)

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        conditions: typing.Optional[list[UpdateCondition]] = None,
        description: typing.Optional[str] = None,
        metadata_changeset: typing.Optional[MetadataChangeset] = None,
    ) -> "Dataset":
        request = UpdateDatasetRequest(
            conditions=conditions,
            description=description,
            metadata_changeset=metadata_changeset,
        )

        self.__record = self.__roboto_client.put(
            f"/v1/datasets/{self.dataset_id}",
            data=request,
        ).to_record(DatasetRecord)
        return self

    def rename_file(self, old_path: str, new_path: str) -> FileRecord:

        response = self.__roboto_client.put(
            f"v1/datasets/{self.dataset_id}/files/rename",
            data=RenameFileRequest(
                old_path=old_path,
                new_path=new_path,
            ),
        )

        return response.to_record(FileRecord)

    def rename_directory(self, old_path: str, new_path: str) -> DirectoryRecord:
        response = self.__roboto_client.put(
            f"v1/datasets/{self.dataset_id}/directory/rename",
            data=RenameDirectoryRequest(
                old_path=old_path,
                new_path=new_path,
            ),
        )

        return response.to_record(DirectoryRecord)

    def upload_directory(
        self,
        directory_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        delete_after_upload: bool = False,
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
    ) -> None:
        """
        Uploads all files and directories recursively from the specified directory path. You can use
        `include_patterns` and `exclude_patterns` to control what files and directories are uploaded, and can
        use `delete_after_upload` to clean up your local filesystem after the uploads succeed.

        Example:
            >>> from roboto import Dataset
            >>> dataset = Dataset(...)
            >>> dataset.upload_directory(
            ...     pathlib.Path("/path/to/directory"),
            ...     exclude_patterns=[
            ...         "__pycache__/",
            ...         "*.pyc",
            ...         "node_modules/",
            ...         "**/*.log",
            ...     ],
            ... )

        Notes:
            - Both `include_patterns` and `exclude_patterns` follow the 'gitignore' pattern format described
              in https://git-scm.com/docs/gitignore#_pattern_format.
            - If both `include_patterns` and `exclude_patterns` are provided, files matching
              `exclude_patterns` will be excluded even if they match `include_patterns`.
        """
        include_spec: typing.Optional[pathspec.PathSpec] = excludespec_from_patterns(
            include_patterns
        )
        exclude_spec: typing.Optional[pathspec.PathSpec] = excludespec_from_patterns(
            exclude_patterns
        )
        all_files = self.__list_directory_files(
            directory_path, include_spec=include_spec, exclude_spec=exclude_spec
        )
        file_destination_paths = {
            path: os.path.relpath(path, directory_path) for path in all_files
        }

        self.upload_files(all_files, file_destination_paths, max_batch_size)

        if delete_after_upload:
            for file in all_files:
                if file.is_file():
                    file.unlink()

    def upload_file(
        self,
        file_path: pathlib.Path,
        file_destination_path: typing.Optional[str] = None,
    ) -> None:
        """
        Upload a single file to the dataset.
        If `file_destination_path` is not provided, the file will be uploaded to the top-level of the dataset.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.upload_file(
            ...     pathlib.Path("/path/to/file.txt"),
            ...     file_destination_path="foo/bar.txt",
            ... )
        """
        if not file_destination_path:
            file_destination_path = file_path.name

        self.upload_files([file_path], {file_path: file_destination_path})

    def upload_files(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        file_destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
    ):
        """
        Upload multiple files to the dataset.
        If `file_destination_paths` is not provided, files will be uploaded to the top-level of the dataset.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.upload_files(
            ...     [
            ...         pathlib.Path("/path/to/file.txt"),
            ...         ...
            ...     ],
            ...     file_destination_paths={
            ...         pathlib.Path("/path/to/file.txt"): "foo/bar.txt",
            ...     },
            ... )
        """
        working_set: list[pathlib.Path] = []

        for file in files:
            working_set.append(file)

            if len(working_set) >= max_batch_size:
                self.__upload_files_batch(working_set, file_destination_paths)
                working_set = []

        if len(working_set) > 0:
            self.__upload_files_batch(working_set, file_destination_paths)

    def _complete_manifest_transaction(self, transaction_id: str) -> None:
        """
        Marks a transaction as 'completed', which allows the Roboto Platform to evaluate triggers
        for automatic action on incoming data. This also aids reporting on partial upload failure cases.

        This should be considered private.

        It is loosely exposed (single underscore instead of double) because of a niche, administrative use-case.
        """
        self.__roboto_client.put(
            f"v2/datasets/{self.dataset_id}/batch_uploads/{transaction_id}/complete"
        )

    def _create_manifest_transaction(
        self,
        origination: str,
        resource_manifest: dict[str, int],
    ) -> tuple[TransactionRecord, dict[str, str]]:
        """
        This should be considered private.

        It is loosely exposed (single underscore instead of double) because of a niche, administrative use-case.
        """
        request = BeginManifestTransactionRequest(
            origination=origination,
            resource_manifest=resource_manifest,
        )

        result = self.__roboto_client.post(
            f"v2/datasets/{self.dataset_id}/batch_uploads",
            data=request,
            caller_org_id=self.org_id,
        ).to_record(BeginManifestTransactionResponse)

        return result.record, dict(result.upload_mappings)

    def __credential_provider(self, transaction_id: str):
        return self.get_temporary_credentials(
            Permissions.ReadWrite,
            force_refresh=True,
            transaction_id=transaction_id,
        ).to_s3_credentials()

    def __file_service(self) -> FileService:
        return FileService(self.__roboto_client)

    def _flush_manifest_item_completions(
        self,
        transaction_id: str,
        manifest_items: list[str],
    ) -> None:
        """
        This should be considered private.

        It is loosely exposed (single underscore instead of double) because of a niche, administrative use-case.
        """
        self.__roboto_client.put(
            f"v2/datasets/{self.dataset_id}/batch_uploads/{transaction_id}/progress",
            data=ReportTransactionProgressRequest(
                manifest_items=manifest_items,
            ),
        )

    def __list_directory_files(
        self,
        directory_path: pathlib.Path,
        include_spec: typing.Optional[pathspec.PathSpec] = None,
        exclude_spec: typing.Optional[pathspec.PathSpec] = None,
    ) -> collections.abc.Iterable[pathlib.Path]:
        all_files = set()

        for root, _, files in os.walk(directory_path):
            for file in files:
                should_include = include_spec is None or include_spec.match_file(file)
                should_exclude = exclude_spec is not None and exclude_spec.match_file(
                    file
                )

                if should_include and not should_exclude:
                    all_files.add(pathlib.Path(root, file))

        return all_files

    def __list_files_page(
        self,
        page_token: typing.Optional[str] = None,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> PaginatedList[FileRecord]:
        """
        List files associated with dataset.

        Files are associated with datasets in an eventually-consistent manner,
        so there will likely be delay between a file being uploaded and it appearing in this list.
        """
        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = str(page_token)

        request = QueryDatasetFilesRequest(
            page_token=page_token,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        return self.__roboto_client.post(
            f"v1/datasets/{self.dataset_id}/files/query",
            data=request,
            query=query_params,
            idempotent=True,
        ).to_paginated_list(FileRecord)

    def __on_manifest_item_complete(
        self,
        transaction_id: str,
        manifest_item_identifier: str,
    ) -> None:
        if transaction_id not in self.__transaction_manifests:
            raise RobotoNotFoundException(
                f"Transaction {transaction_id} does not have a manifest"
            )

        if transaction_id not in self.__transaction_completed_unreported_items:
            self.__transaction_completed_unreported_items[transaction_id] = set()

        self.__transaction_completed_unreported_items[transaction_id].add(
            manifest_item_identifier
        )

        if self.__unreported_manifest_items_batch_ready_to_report(transaction_id):
            self._flush_manifest_item_completions(
                transaction_id=transaction_id,
                manifest_items=list(
                    self.__transaction_completed_unreported_items[transaction_id]
                ),
            )
            self.__transaction_completed_unreported_items[transaction_id] = set()

    def __unreported_manifest_items_batch_ready_to_report(self, transaction_id):
        return (
            len(self.__transaction_completed_unreported_items[transaction_id])
            >= (
                len(self.__transaction_manifests[transaction_id])
                / self.__manifest_reporting_increments
            )
            and len(self.__transaction_completed_unreported_items[transaction_id])
            >= self.__manifest_reporting_min_batch_size
        )

    def __upload_files_batch(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        file_destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
    ):
        try:
            package_version = importlib.metadata.version("roboto")
        except importlib.metadata.PackageNotFoundError:
            package_version = "version_not_found"

        origination = RobotoEnv.default().roboto_env or f"roboto {package_version}"
        file_manifest = {
            file_destination_paths.get(path, path.name): path.stat().st_size
            for path in files
        }

        total_file_count = len(file_manifest)
        total_file_size = sum(file_manifest.values())

        transaction, create_upload_mappings = self._create_manifest_transaction(
            origination=origination,
            resource_manifest=file_manifest,
        )

        file_path_to_manifest_mappings = {
            file_destination_paths.get(path, path.name): path for path in files
        }
        upload_mappings = {
            file_path_to_manifest_mappings[src_path]: dest_uri
            for src_path, dest_uri in create_upload_mappings.items()
        }

        progress_monitor_factory = TqdmProgressMonitorFactory(
            concurrency=1,
            ctx={
                "expected_file_count": total_file_count,
                "expected_file_size": total_file_size,
            },
        )

        with progress_monitor_factory.upload_monitor(
            source=f"{total_file_count} file" + ("s" if total_file_count != 1 else ""),
            size=total_file_size,
        ) as progress_monitor:
            self.__file_service().upload_many_files(
                file_generator=upload_mappings.items(),
                credential_provider=functools.partial(
                    self.__credential_provider, transaction.transaction_id
                ),
                on_file_complete=functools.partial(
                    self.__on_manifest_item_complete,
                    transaction.transaction_id,
                ),
                progress_monitor=progress_monitor,
                max_concurrency=8,
            )

        self._complete_manifest_transaction(
            transaction.transaction_id,
        )
