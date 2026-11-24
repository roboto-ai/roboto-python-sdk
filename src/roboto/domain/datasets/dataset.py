# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import pathlib
import typing

from ...ai import SetSummaryRequest
from ...ai.summary import (
    AISummary,
    PollingStreamingAISummary,
    StreamingAISummary,
)
from ...association import Association
from ...exceptions import (
    RobotoDeviceNotFoundException,
)
from ...experimental.ingest import MAX_FILES_AND_TOPICS_PER_REQUEST
from ...experimental.sessions import Session, SessionFile
from ...http import RobotoClient
from ...logging import default_logger
from ...query import DEFAULT_PAGE_SIZE, QueryContentMode, QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from ...storage import FileService
from ...updates import (
    CustomFieldChangeset,
    MetadataChangeset,
    StrSequence,
)
from ...warnings import experimental
from ..devices import Device
from ..files import (
    DirectoryRecord,
    File,
    FileRecord,
    FileSystem,
)
from ..files.file_system import MAX_FILES_PER_MANIFEST
from ..topics import Topic, TopicTimeBounds
from .operations import (
    CreateDatasetIfNotExistsRequest,
    CreateDatasetRequest,
    UpdateDatasetRequest,
)
from .record import DatasetRecord

logger = default_logger()


class Dataset:
    """A dataset: a container of files in a directory structure, usually from one robot activity such as a flight.

    A dataset belongs to one organization and can name the device its data came from. Its files are
    :py:class:`~roboto.domain.files.File` objects, reached through ``files`` or the file methods on this class.
    Ingestion extracts topics from those files, which ``get_topics`` lists. A session can include files from one or
    more datasets.
    A dataset also carries tags, key-value metadata, custom-field values, and an optional AI summary.

    Get a ``Dataset`` from ``create``, ``create_if_not_exists``, ``from_id``, or ``query``. To wrap a
    :py:class:`~roboto.domain.datasets.DatasetRecord` already fetched from Roboto, build a ``Dataset`` from it
    directly. Each instance holds a copy of the dataset's record: methods that change the dataset's properties update
    that copy from Roboto's response, and ``refresh`` fetches changes made elsewhere.

    Args:
        record: Record of the dataset.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        file_service: Transfers file contents to and from storage. Built from ``roboto_client`` if omitted.
        content_mode: Whether ``record`` includes the dataset's metadata.
            :py:attr:`~roboto.query.QueryContentMode.RecordOnly` makes the first ``get_metadata`` call fetch the
            full record. ``None`` means ``record`` includes it.
    """

    __roboto_client: RobotoClient
    __record: DatasetRecord
    __content_mode: QueryContentMode
    __file_service: FileService

    @classmethod
    def create(
        cls,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        name: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        device_id: typing.Optional[str] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        create_device_if_missing: bool = False,
    ) -> Dataset:
        """Create a dataset.

        Args:
            description: Human-readable description of the dataset.
            metadata: Key-value metadata to set on the dataset. ``None`` sets none.
            name: Human-readable name of the dataset, at most 120 characters. Roboto does not require names to be
                unique.
            tags: Tags to set on the dataset. ``None`` sets none.
            device_id: ID of the device that produced the dataset's data. ``None`` records the calling device when
                a device makes the request, and no device otherwise.
            custom_fields: Initial values for the dataset's custom fields, keyed by field name. Each name must be a
                custom field defined for datasets in the organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type. ``None`` sets none.
            caller_org_id: Organization to create the dataset in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            create_device_if_missing: Whether to create the device named by ``device_id`` when the organization has
                no such device, then create the dataset again. When ``False``, a missing device raises
                :py:class:`~roboto.exceptions.RobotoDeviceNotFoundException`.

        Returns:
            The new dataset.

        Raises:
            RobotoDeviceNotFoundException: ``device_id`` names no device in the organization, and
                ``create_device_if_missing`` is ``False``.
            RobotoIllegalArgumentException: A ``custom_fields`` name is not a ready custom field for datasets, or its
                value does not match the field's type.

        Examples:
            Create a dataset with a name, tags, and metadata:

            >>> dataset = Dataset.create(
            ...     name="Highway Test Session",
            ...     description="Autonomous vehicle highway driving test data",
            ...     tags=["highway", "autonomous", "test"],
            ...     metadata={"vehicle_id": "vehicle_001", "test_type": "highway"},
            ... )

            Create an empty dataset with no properties set:

            >>> dataset = Dataset.create()
            >>> print(dataset.dataset_id)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDatasetRequest(
            description=description,
            device_id=device_id,
            metadata=metadata or {},
            name=name,
            tags=tags or [],
            custom_fields=custom_fields,
        )

        try:
            record = roboto_client.post("v1/datasets", data=request, caller_org_id=caller_org_id).to_record(
                DatasetRecord
            )
        except RobotoDeviceNotFoundException as exc:
            if not create_device_if_missing or device_id is None:
                raise exc

            Device.create(
                device_id=device_id,
                caller_org_id=caller_org_id,
                roboto_client=roboto_client,
            )
            record = roboto_client.post("v1/datasets", data=request, caller_org_id=caller_org_id).to_record(
                DatasetRecord
            )

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def create_if_not_exists(
        cls,
        match_roboql_query: str,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        name: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        device_id: typing.Optional[str] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        create_device_if_missing: bool = False,
    ) -> Dataset:
        """Fetch the first dataset that matches a RoboQL query, creating one when none matches.

        A matching dataset is returned unchanged: the other arguments apply only to a dataset this call creates.

        Concurrent calls with the same ``match_roboql_query`` in one organization create one dataset between them,
        because Roboto runs them one at a time from the search through the create. Calls with different queries are
        not run one at a time, even when both queries would match the same dataset.

        The dataset created must match ``match_roboql_query``. If ``name``, ``tags`` or ``metadata`` describe a
        dataset the query does not match, every later call creates another one. When several datasets match, which
        one is returned is not defined unless the query ends with a ``SORT BY`` clause.

        Args:
            match_roboql_query: RoboQL query that looks for an existing dataset in the organization.
            description: Human-readable description of the dataset.
            metadata: Key-value metadata to set on the dataset. ``None`` sets none.
            name: Human-readable name of the dataset, at most 120 characters.
            tags: Tags to set on the dataset. ``None`` sets none.
            device_id: ID of the device that produced the dataset's data. ``None`` records the calling device when
                a device makes the request, and no device otherwise.
            custom_fields: Initial values for the dataset's custom fields, keyed by field name. Each name must be a
                custom field defined for datasets in the organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type. ``None`` sets none.
            caller_org_id: Organization to search and to create the dataset in. Required when the caller belongs to
                more than one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            create_device_if_missing: Whether to create the device named by ``device_id`` when the organization has
                no such device, then make the call again. When ``False``, a missing device raises
                :py:class:`~roboto.exceptions.RobotoDeviceNotFoundException`.

        Returns:
            The matching dataset, or the new dataset when none matched.

        Raises:
            RobotoDeviceNotFoundException: No dataset matched, ``device_id`` names no device in the organization,
                and ``create_device_if_missing`` is ``False``.
            RobotoIllegalArgumentException: No dataset matched, and a ``custom_fields`` name is not a ready custom
                field for datasets, or its value does not match the field's type.
            RobotoInvalidRequestException: ``match_roboql_query`` is not a valid RoboQL query.

        Examples:
            Create a dataset unless one with this metadata value exists:

            >>> dataset = Dataset.create_if_not_exists(
            ...     match_roboql_query="dataset.metadata.vehicle_id = 'vehicle_001'",
            ...     name="Vehicle 001 Test Session",
            ...     description="Test data for vehicle 001",
            ...     metadata={"vehicle_id": "vehicle_001", "test_type": "highway"},
            ...     tags=["vehicle_001", "highway"],
            ... )

            Create a dataset unless one with this tag exists. The new dataset carries the tag, so later calls
            return it:

            >>> dataset = Dataset.create_if_not_exists(
            ...     match_roboql_query="dataset.tags CONTAINS 'unique_session_id_xyz'",
            ...     name="Unique Test Session",
            ...     tags=["unique_session_id_xyz", "test"],
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDatasetIfNotExistsRequest(
            match_roboql_query=match_roboql_query,
            create_request=CreateDatasetRequest(
                description=description,
                device_id=device_id,
                metadata=metadata or {},
                name=name,
                tags=tags or [],
                custom_fields=custom_fields,
            ),
        )

        try:
            record = roboto_client.post(
                "v1/datasets/create_if_not_exists",
                data=request,
                caller_org_id=caller_org_id,
            ).to_record(DatasetRecord)
        except RobotoDeviceNotFoundException as exc:
            if not create_device_if_missing or device_id is None:
                raise exc

            Device.create(
                device_id=device_id,
                caller_org_id=caller_org_id,
                roboto_client=roboto_client,
            )

            record = roboto_client.post(
                "v1/datasets/create_if_not_exists",
                data=request,
                caller_org_id=caller_org_id,
            ).to_record(DatasetRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(cls, dataset_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> Dataset:
        """Fetch a dataset by its ID.

        Args:
            dataset_id: Unique ID of the dataset, beginning with ``ds_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoDatasetNotFoundException: No dataset has this ID.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> print(dataset.name)
        """
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
        """List the datasets in an organization that match a query specification.

        Fetches one page of results at a time as the generator advances, and writes each page's token to
        ``spec.after`` to request the next.

        Args:
            spec: Conditions, sort order, and page size of the query. Each condition's field must be a
                :py:class:`~roboto.domain.datasets.DatasetRecord` field, or a dotted path that starts with one, such
                as ``metadata.software_version``. ``None`` lists every dataset in the organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            owner_org_id: Organization whose datasets to list. Defaults to the organization the caller acts in.

        Yields:
            Datasets that match ``spec``, with their metadata.

        Raises:
            ValueError: ``spec`` names a field that is not a dataset record field. It surfaces on the first
                iteration, before any request.

        Examples:
            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(field="name", comparator=Comparator.Contains, value="Roboto")
            ... )
            >>> for dataset in Dataset.query(spec):
            ...     print(dataset.dataset_id, dataset.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec if spec is not None else QuerySpecification(limit=DEFAULT_PAGE_SIZE)

        known = set(DatasetRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # A dotted field such as "metadata.SoftwareVersion" is checked by its first segment.
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = "are not known attributes of Dataset" if plural else "is not a known attribute of Dataset"
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

    def __eq__(self, other: object) -> bool:
        """Return whether ``other`` is a ``Dataset`` whose record equals this one's, ignoring ``metadata``."""
        if not isinstance(other, Dataset):
            return False

        exclude_meta: dict[str, typing.Any] = {"metadata": dict()}
        return self.record.model_copy(update=exclude_meta) == other.record.model_copy(update=exclude_meta)

    def __init__(
        self,
        record: DatasetRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        file_service: typing.Optional[FileService] = None,
        content_mode: typing.Optional[QueryContentMode] = None,
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__file_service = file_service or FileService(self.__roboto_client)
        self.__record = record
        self.__content_mode = content_mode or QueryContentMode.RecordWithMeta

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """Time the dataset was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the dataset, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def dataset_id(self) -> str:
        """Unique ID of the dataset, beginning with ``ds_``."""
        return self.__record.dataset_id

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the dataset, or ``None`` if it has none."""
        return self.__record.description

    @property
    def device_id(self) -> typing.Optional[str]:
        """ID of the device the dataset's data came from, or ``None`` if none was given."""
        return self.__record.device_id

    @property
    def files(self) -> FileSystem:
        """Files and directories of the dataset.

        The file methods on ``Dataset`` call the same methods on this object, so ``dataset.upload_files(...)`` and
        ``dataset.files.upload_files(...)`` are the same call.
        """
        return FileSystem(
            Association.dataset(self.dataset_id),
            roboto_client=self.__roboto_client,
            file_service=self.__file_service,
            org_id=self.org_id,
        )

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Copy of the key-value metadata on the dataset.

        Reading it can make a request, as ``get_metadata`` describes. Prefer that method, which returns the same value
        and shows the request at the call site.
        """

        return self.get_metadata()

    @property
    @experimental
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields the organization defines for datasets, keyed by field name.

        :py:attr:`~roboto.domain.datasets.DatasetRecord.custom_fields` says which fields appear as keys. A
        :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is an ISO 8601 string.
        """
        return self.__record.custom_fields

    def get_metadata(self) -> dict[str, typing.Any]:
        """Return a copy of the key-value metadata on the dataset.

        Nested metadata comes back as nested dictionaries. When this instance was loaded without metadata, as
        :py:meth:`~roboto.roboto_search.RobotoSearch.find_datasets` does by default, the first call fetches the
        dataset's full record from Roboto, replacing this instance's copy.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> metadata = dataset.get_metadata()
            >>> metadata.get("vehicle_id")
        """

        if self.__content_mode is not QueryContentMode.RecordWithMeta:
            # This instance was built from a record without metadata; fetch the full record once.
            self.refresh()
            self.__content_mode = QueryContentMode.RecordWithMeta

        return self.__record.metadata.copy()

    @property
    def modified(self) -> datetime.datetime:
        """Time the dataset was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the dataset, in the same ``<type>:<id>`` form as ``created_by``."""
        return self.__record.modified_by

    @property
    def name(self) -> typing.Optional[str]:
        """Human-readable name of the dataset, at most 120 characters, or ``None`` if it has none.

        :py:attr:`~roboto.domain.datasets.DatasetRecord.name` says whether names must be unique.
        """
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the dataset."""
        return self.__record.org_id

    @property
    def record(self) -> DatasetRecord:
        """Record of the dataset that this instance holds.

        ``refresh`` replaces it with the current one.
        """
        return self.__record

    @property
    def tags(self) -> list[str]:
        """Copy of the tags on the dataset."""
        return self.__record.tags.copy()

    def create_directory(
        self,
        name: str,
        error_if_exists: bool = False,
        create_intermediate_dirs: bool = False,
        parent_path: typing.Optional[pathlib.Path] = None,
        origination: typing.Optional[str] = None,
    ) -> DirectoryRecord:
        """Create a directory in the dataset.

        It calls :py:meth:`~roboto.domain.files.FileSystem.create_directory`, whose failures also apply.

        Args:
            name: Name of the directory to create.
            error_if_exists: Whether to raise when the directory already exists.
            create_intermediate_dirs: Whether to create missing directories in ``parent_path``. When ``False``,
                every directory in ``parent_path`` must already exist.
            parent_path: Path of the parent directory, relative to the dataset's root. ``None`` creates the
                directory at the root.
            origination: Free-form description of what created the directory. ``None`` records the
                ``ROBOTO_ENV`` environment variable if set, and otherwise ``roboto`` followed by the SDK version.

        Returns:
            Record of the created directory.

        Examples:
            Create a directory at the dataset's root:

            >>> import pathlib
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> directory = dataset.create_directory("foo")
            >>> print(directory.relative_path)
            foo

            Create a directory and any missing directories above it:

            >>> directory = dataset.create_directory(
            ...     name="final",
            ...     parent_path=pathlib.Path("path/to/deep"),
            ...     create_intermediate_dirs=True,
            ... )
            >>> print(directory.relative_path)
            path/to/deep/final
        """
        return self.files.create_directory(
            name=name,
            error_if_exists=error_if_exists,
            create_intermediate_dirs=create_intermediate_dirs,
            parent_path=parent_path,
            origination=origination,
        )

    @experimental
    def create_session(
        self,
        name: typing.Optional[str] = None,
        *,
        device_ids: typing.Optional[collections.abc.Sequence[str]] = None,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[collections.abc.Sequence[str]] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
    ) -> Session:
        """Create a session in the dataset's organization that includes the dataset's files.

        A session is an operational time window of a device. The new session includes every file of the dataset
        that ``include_patterns`` and ``exclude_patterns`` select, each over its whole time range.

        Args:
            name: Human-readable name of the session, at most 120 characters.
            device_ids: IDs of the devices to attach to the session. ``None`` attaches none.
            include_patterns: Gitignore-style patterns for the files to include, as in ``list_files``. ``None`` or
                an empty list includes every file.
            exclude_patterns: Gitignore-style patterns for the files to leave out. Takes precedence over
                ``include_patterns``.
            description: Human-readable description of the session.
            metadata: Key-value metadata to set on the session. Sessions cannot be filtered or sorted by
                metadata keys; for a queryable attribute, define a custom field for sessions instead.
            tags: Tags to set on the session. Sessions can be filtered by tag but not sorted by tag.
            custom_fields: Initial values for the session's custom fields, keyed by field name. Each name must be a
                custom field defined for sessions in the dataset's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type.

        Returns:
            The new :py:class:`~roboto.experimental.sessions.Session`.

        Raises:
            RobotoDomainException: Roboto refused a file, or a request failed. Unless the session could not be
                deleted (see the note below), no session is left behind, so calling again is safe.

        Note:
            This method calls :py:meth:`~roboto.experimental.sessions.Session.create`, then
            :py:meth:`~roboto.experimental.sessions.Session.add_files` once per batch of at most 500 files
            (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`). Every file goes in or
            none does: when any batch fails or Roboto refuses any file, the session is deleted before the exception
            propagates. If deleting it fails too, such as on a network error, the session is left holding the
            files added so far; that failure is logged, and the caller sees the original exception.

        Examples:
            Include every file of the dataset:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> session = dataset.create_session("flight-2026-04-23-001")

            Include only the dataset's MCAP files:

            >>> session = dataset.create_session("flight-2026-04-23-002", include_patterns=["**/*.mcap"])
        """
        session_files = [
            SessionFile(file_id=file.file_id)
            for file in self.list_files(include_patterns=include_patterns, exclude_patterns=exclude_patterns)
        ]

        session = Session.create(
            name=name,
            device_ids=list(device_ids) if device_ids is not None else [],
            description=description,
            metadata=metadata,
            tags=tags,
            custom_fields=custom_fields,
            caller_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )
        try:
            for batch_start in range(0, len(session_files), MAX_FILES_AND_TOPICS_PER_REQUEST):
                batch = session_files[batch_start : batch_start + MAX_FILES_AND_TOPICS_PER_REQUEST]
                add_results = session.add_files(batch)
                if add_results.failed:
                    raise add_results.failed[0]
        except Exception:
            try:
                session.delete()
            except Exception:
                logger.exception(
                    "Dataset.create_session: failed to roll back Session %s after add_files error; "
                    "the Session may exist holding whichever files were added before the error",
                    session.session_id,
                )
            raise
        return session

    def delete(self) -> None:
        """Delete the dataset, with its files and their topics. This cannot be undone.

        Files uploaded through Roboto are also deleted from storage, whether they are stored in a Roboto-managed
        bucket or in a bucket the organization provides. Files imported from such a bucket with
        :py:meth:`~roboto.domain.files.File.import_batch` stay in the bucket; only their records are deleted from
        Roboto.

        Deleting a dataset that no longer exists succeeds and changes nothing.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.delete()
        """
        self.__roboto_client.delete(f"v1/datasets/{self.dataset_id}")

    def delete_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> None:
        """Delete the dataset's files that match the given patterns.

        Deletes the matching files one request per file, so when one request fails, the files deleted before it
        stay deleted. It calls :py:meth:`~roboto.domain.files.FileSystem.delete_files`, whose failures also apply.

        Args:
            include_patterns: Gitignore-style patterns for the files to delete. ``None`` or an empty list selects
                every file.
            exclude_patterns: Gitignore-style patterns for files to keep. Takes precedence over
                ``include_patterns``. ``None`` or an empty list keeps none.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore.

        Examples:
            Delete every PNG file except those under a ``back_camera`` directory:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.delete_files(include_patterns=["**/*.png"], exclude_patterns=["**/back_camera/**"])

            Delete every log file:

            >>> dataset.delete_files(include_patterns=["**/*.log"])
        """
        self.files.delete_files(include_patterns, exclude_patterns)

    def download_files(
        self,
        out_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        print_progress: bool = True,
    ) -> list[tuple[FileRecord, pathlib.Path]]:
        """Download the dataset's files that match the given patterns to a local directory.

        Each file is saved at its path relative to the dataset's root, under ``out_path``. It calls
        :py:meth:`~roboto.domain.files.FileSystem.download_files`, whose failures also apply.

        Args:
            out_path: Local directory to download into. Created, with any missing parents, if it does not exist.
            include_patterns: Gitignore-style patterns for the files to download. ``None`` or an empty list selects
                every file.
            exclude_patterns: Gitignore-style patterns for files to skip. Takes precedence over
                ``include_patterns``. ``None`` or an empty list skips none.
            print_progress: Whether to show a progress bar during the download.

        Returns:
            One ``(record, local_path)`` pair per downloaded file.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore.

        Examples:
            Download the dataset's bag files, except those under a ``test`` directory:

            >>> import pathlib
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> downloaded = dataset.download_files(
            ...     pathlib.Path("/tmp/dataset_download"),
            ...     include_patterns=["**/*.bag"],
            ...     exclude_patterns=["**/test/**"],
            ... )
            >>> print(f"Downloaded {len(downloaded)} files")

            Download every file:

            >>> all_files = dataset.download_files(pathlib.Path("/tmp/all_files"))
        """
        return self.files.download_files(out_path, include_patterns, exclude_patterns, print_progress)

    def get_file_by_path(
        self,
        relative_path: typing.Union[str, pathlib.Path],
        version_id: typing.Optional[int] = None,
    ) -> File:
        """Fetch the dataset's file at a path.

        It calls :py:meth:`~roboto.domain.files.FileSystem.get_file_by_path`, whose failures also apply.

        Args:
            relative_path: Path of the file, relative to the dataset's root.
            version_id: Version of the file to fetch. ``None`` fetches the latest version.

        Examples:
            Fetch the latest version of a file:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> file = dataset.get_file_by_path("logs/session1.bag")
            >>> print(file.file_id)

            Fetch version 1 of a file:

            >>> old_file = dataset.get_file_by_path("data/sensors.csv", version_id=1)
            >>> print(old_file.version)
            1
        """
        return self.files.get_file_by_path(relative_path, version_id)

    def generate_summary(self) -> StreamingAISummary:
        """Start generating a new AI summary of the dataset.

        Roboto generates the summary in the background. This method returns once generation has started; the
        returned object fetches the rest of the summary from Roboto when you wait for it or stream its text.

        Returns:
            The summary being generated, which starts in the
            :py:attr:`~roboto.ai.summary.AISummaryStatus.Pending` state.

        Examples:
            Generate a summary and wait for its full text:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> summary = dataset.generate_summary()
            >>> print(summary.complete_text)

            Print the text as it is generated:

            >>> summary = dataset.generate_summary()
            >>> for text_chunk in summary.text_stream():
            ...     print(text_chunk, end="", flush=True)

            Check the summary's state without waiting:

            >>> from roboto.ai.summary import AISummaryStatus
            >>> summary = dataset.generate_summary()
            >>> if summary.current and summary.current.status == AISummaryStatus.Complete:
            ...     print("Summary is ready!")
        """
        initial_summary = self.__roboto_client.post(f"v1/datasets/{self.dataset_id}/summary").to_record(AISummary)

        return PollingStreamingAISummary(
            poll_fn=self.__get_latest_summary,
            poll_on_init=False,
            initial_summary=initial_summary,
        )

    def get_summary(self) -> StreamingAISummary:
        """Fetch the dataset's latest AI summary, without generating one.

        Returns:
            The dataset's latest summary. If its generation is still running, the summary is
            :py:attr:`~roboto.ai.summary.AISummaryStatus.Pending`; its ``await_completion`` and ``text_stream``
            methods wait for the rest.

        Raises:
            RobotoNotFoundException: The dataset has no AI summary. Call ``generate_summary`` to create one.

        Examples:
            Get the existing summary, generating one first if there is none:

            >>> from roboto.exceptions import RobotoNotFoundException
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> try:
            ...     summary = dataset.get_summary()
            ... except RobotoNotFoundException:
            ...     summary = dataset.generate_summary()
            >>> print(summary.complete_text)

            Check whether a summary exists without generating one:

            >>> try:
            ...     summary = dataset.get_summary()
            ...     print(summary.complete_text)
            ... except RobotoNotFoundException:
            ...     print("No summary yet — call generate_summary() to create one.")
        """
        return PollingStreamingAISummary(poll_fn=self.__get_latest_summary, poll_on_init=True)

    @experimental
    def get_sessions(self) -> collections.abc.Generator[Session, None, None]:
        """List the sessions that include at least one of the dataset's files.

        A session is an operational time window of a device, and can include files from several datasets.

        Yields:
            Each :py:class:`~roboto.experimental.sessions.Session` that includes a file of this dataset, fetched
            a page at a time as the generator advances.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for session in dataset.get_sessions():
            ...     print(session.session_id, session.name)
        """
        yield from Session.for_dataset(self.dataset_id, roboto_client=self.__roboto_client)

    def get_topics(
        self,
        include: typing.Optional[collections.abc.Sequence[str]] = None,
        exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> collections.abc.Generator[Topic, None, None]:
        """List the topics of the dataset's files, optionally filtered by name.

        A topic is a sequence of structured time-series data from one file, usually extracted by ingestion. When
        several files have a topic with the same name, such as files split from one recording, each file's topic is
        yielded separately.

        Args:
            include: Exact topic names to yield. ``None`` yields every topic.
            exclude: Exact topic names to skip. Takes precedence over ``include``. ``None`` skips none.

        Yields:
            Each of the dataset's :py:class:`~roboto.domain.topics.Topic` objects that the filters admit.

        Note:
            The topics come without message paths: each topic's ``message_paths`` is empty. To get them, call
            :py:meth:`~roboto.domain.files.File.get_topics` on each file instead.

        Examples:
            List every topic:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for topic in dataset.get_topics():
            ...     print(topic.name)

            List only the camera topics:

            >>> camera_topics = list(dataset.get_topics(include=["/camera/image", "/camera/info"]))

            List every topic except diagnostics:

            >>> data_topics = list(dataset.get_topics(exclude=["/diagnostics"]))
        """

        for topic in Topic.get_by_dataset(self.dataset_id, self.__roboto_client):
            if include is not None and topic.name not in include:
                continue

            if exclude is not None and topic.name in exclude:
                continue

            yield topic

    def get_topic_time_bounds(self) -> TopicTimeBounds:
        """Fetch the earliest start time and latest end time across every topic in the dataset.

        Returns the same values as taking the minimum ``start_time`` and maximum ``end_time`` over ``get_topics``, in
        one request instead of one per page of topics.

        Returns:
            Bounds in nanoseconds since the Unix epoch. Both are ``None`` when the dataset's files hold no topics,
            and either is ``None`` when no topic in the dataset has that bound.

        Raises:
            RobotoNotFoundException: The dataset does not exist.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> bounds = dataset.get_topic_time_bounds()
            >>> print(bounds.start_time, bounds.end_time)
        """
        return self.__roboto_client.get(f"v1/datasets/{self.dataset_id}/topics/time-bounds").to_record(TopicTimeBounds)

    def get_topics_by_file(
        self, relative_path: typing.Union[str, pathlib.Path]
    ) -> collections.abc.Generator[Topic, None, None]:
        """List the topics of the dataset's file at a path.

        Equivalent to ``dataset.get_file_by_path(relative_path).get_topics()``. The file is looked up when this
        method is called, before the first topic is fetched.

        Args:
            relative_path: Path of the file, relative to the dataset's root.

        Yields:
            Each :py:class:`~roboto.domain.topics.Topic` of the file.

        Raises:
            RobotoNotFoundException: The dataset has no file at this path.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for topic in dataset.get_topics_by_file("logs/session1.bag"):
            ...     print(topic.name)
        """
        file = self.get_file_by_path(relative_path)
        return file.get_topics()

    def list_directories(
        self,
    ) -> collections.abc.Generator[DirectoryRecord, None, None]:
        """List every directory in the dataset, at any depth.

        It calls :py:meth:`~roboto.domain.files.FileSystem.list_directories`, whose failures also apply.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for directory in dataset.list_directories():
            ...     print(directory.relative_path)
        """
        yield from self.files.list_directories()

    def list_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> collections.abc.Generator[File, None, None]:
        """List the dataset's files that match the given patterns.

        It calls :py:meth:`~roboto.domain.files.FileSystem.list_files`, whose failures also apply.

        Args:
            include_patterns: Gitignore-style patterns for the files to list. ``None`` or an empty list selects
                every file.
            exclude_patterns: Gitignore-style patterns for files to leave out. Takes precedence over
                ``include_patterns``. ``None`` or an empty list leaves out none.

        Yields:
            Each matching :py:class:`~roboto.domain.files.File`, fetched a page at a time as the generator
            advances.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore. A file appears
            here shortly after its upload completes, not at once.

        Examples:
            List every file:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for file in dataset.list_files():
            ...     print(file.relative_path)

            List the image files, except those under a ``back_camera`` directory:

            >>> for file in dataset.list_files(
            ...     include_patterns=["**/*.png", "**/*.jpg"], exclude_patterns=["**/back_camera/**"]
            ... ):
            ...     print(file.relative_path)
        """
        yield from self.files.list_files(include_patterns, exclude_patterns)

    def put_metadata(
        self,
        metadata: dict[str, typing.Any],
    ) -> None:
        """Set metadata keys on the dataset, adding new keys and overwriting existing ones.

        Keys the dict does not name keep their values. A dotted key such as ``"weather.condition"`` sets
        ``condition`` inside the nested ``weather`` object.

        Args:
            metadata: Key-value metadata to set on the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.put_metadata(
            ...     {
            ...         "vehicle_id": "vehicle_001",
            ...         "test_type": "highway_driving",
            ...         "weather.condition": "sunny",
            ...         "weather.temperature": 25,
            ...     }
            ... )
            >>> print(dataset.get_metadata()["weather"]["condition"])
            sunny
        """
        self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(
        self,
        tags: StrSequence,
    ) -> None:
        """Add tags to the dataset, keeping its existing tags.

        A tag the dataset already has is not added again.

        Args:
            tags: Tags to add to the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.put_tags(["highway", "sunny"])
            >>> dataset.put_tags(["test"])
            >>> {"highway", "sunny", "test"} <= set(dataset.tags)
            True
        """
        self.update(
            metadata_changeset=MetadataChangeset(put_tags=tags),
        )

    def refresh(self) -> Dataset:
        """Replace this instance's record with the dataset's current record from Roboto.

        Use it to see changes that other users or processes made after this instance was loaded.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoDatasetNotFoundException: The dataset no longer exists.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> print(dataset.refresh().tags)
        """
        self.__record = self.__roboto_client.get(f"v1/datasets/{self.dataset_id}").to_record(DatasetRecord)
        return self

    def remove_metadata(
        self,
        metadata: StrSequence,
    ) -> None:
        """Remove metadata keys from the dataset. Keys the dataset does not have are ignored.

        A dotted key such as ``"baz.qux"`` removes ``qux`` from inside the nested ``baz`` object.

        Args:
            metadata: Metadata keys to remove.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.remove_metadata(["foo", "baz.qux"])
        """
        self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(
        self,
        tags: StrSequence,
    ) -> None:
        """Remove tags from the dataset. Tags the dataset does not have are ignored.

        Args:
            tags: Tags to remove from the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.remove_tags(["draft"])
            >>> "draft" in dataset.tags
            False
        """
        self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    @experimental
    def set_custom_field(self, name: str, value: typing.Any) -> Dataset:
        """Set one custom-field value on the dataset.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for datasets in the dataset's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            value: Value to set, which must match the field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.set_custom_field("flight_count", 12)
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    @experimental
    def clear_custom_field(self, name: str) -> Dataset:
        """Clear one custom-field value on the dataset, so the field reads back as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a ready custom field defined for datasets in the dataset's organization.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.clear_custom_field("flight_count").custom_fields["flight_count"] is None
            True
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    @experimental
    def set_custom_fields(self, fields: dict[str, typing.Any]) -> Dataset:
        """Set several custom-field values on the dataset. Fields not named keep their values.

        It calls ``update``, whose failures also apply.

        Args:
            fields: New values keyed by field name. Each name must be a custom field defined for datasets in the
                dataset's organization, with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`,
                and each value must match that field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.set_custom_fields({"drone_id": "DJI-X", "flight_count": 12})
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=fields))

    @experimental
    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> Dataset:
        """Clear several custom-field values on the dataset, so each field reads back as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            names: Names of ready custom fields defined for datasets in the dataset's organization.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.clear_custom_fields(["drone_id", "flight_count"])
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))

    def set_device_id(self, device_id: typing.Optional[str], create_device_if_missing: bool = False) -> Dataset:
        """Set or clear the device the dataset's data came from.

        It calls ``update``, whose failures also apply.

        Args:
            device_id: ID of a device in the dataset's organization. ``None`` clears the dataset's device.
            create_device_if_missing: Whether to create the device named by ``device_id`` when the organization has
                no such device, then update the dataset again. When ``False``, a missing device raises
                :py:class:`~roboto.exceptions.RobotoDeviceNotFoundException`.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.set_device_id("rover-01", create_device_if_missing=True)
        """
        return self.update(
            device_id=device_id,
            create_device_if_missing=create_device_if_missing,
        )

    def set_summary(self, summary: str) -> Dataset:
        """Replace the dataset's AI summary with the given text.

        Use it when an action or other process can write a more specific summary than ``generate_summary`` would.
        The text becomes the summary that ``get_summary`` returns and the Roboto web app shows.

        Args:
            summary: Text of the summary, rendered as Markdown. It can include ``roboto://`` links to Roboto
                resources, which the Roboto web app renders as links.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.set_summary("Highway drive, 42 minutes, no disengagements.")
        """
        self.__roboto_client.put(
            f"v1/datasets/{self.dataset_id}/summary",
            data=SetSummaryRequest(summary=summary),
        )

        return self

    def to_association(self) -> Association:
        """Return an association that refers to the dataset, for APIs that take one.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.to_association().association_id
            'ds_abc123'
        """
        return Association.dataset(self.dataset_id)

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the record this instance holds, as a JSON-compatible dictionary.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset_dict = dataset.to_dict()
            >>> dataset_dict["dataset_id"]
            'ds_abc123'
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        name: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        create_device_if_missing: bool = False,
        custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None,
    ) -> Dataset:
        """Update the dataset's properties. Arguments left unset leave their property unchanged.

        Args:
            description: Human-readable description of the dataset. ``None`` clears it.
            device_id: ID of the device that produced the dataset's data, which must be in the dataset's
                organization. ``None`` clears it.
            metadata_changeset: Changes to the dataset's tags and metadata.
            name: Human-readable name of the dataset, at most 120 characters. ``None`` clears it.
            create_device_if_missing: Whether to create the device named by ``device_id`` when the organization has
                no such device, then update the dataset again. When ``False``, a missing device raises
                :py:class:`~roboto.exceptions.RobotoDeviceNotFoundException`.
            custom_fields_changeset: Changes to the dataset's custom-field values. Fields the changeset does not
                name keep their values. ``None`` changes none.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoDeviceNotFoundException: ``device_id`` names no device in the dataset's organization, and
                ``create_device_if_missing`` is ``False``.
            RobotoIllegalArgumentException: The custom-field changeset names a field that is not a ready custom
                field for datasets, or sets a value that does not match its field's type.

        Examples:
            Rename the dataset and change its description:

            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.update(name="Updated Highway Test Session", description="Updated description")
            >>> print(dataset.name)
            Updated Highway Test Session

            Set a metadata key:

            >>> from roboto.updates import MetadataChangeset
            >>> dataset.update(metadata_changeset=MetadataChangeset(put_fields={"processed": True}))

            Clear the dataset's device and description:

            >>> dataset.update(device_id=None, description=None)
        """
        request = remove_not_set(
            UpdateDatasetRequest(
                description=description,
                device_id=device_id,
                name=name,
                metadata_changeset=metadata_changeset,
                custom_fields_changeset=custom_fields_changeset,
            )
        )

        try:
            self.__record = self.__roboto_client.put(
                f"/v1/datasets/{self.dataset_id}",
                data=request,
            ).to_record(DatasetRecord)
        except RobotoDeviceNotFoundException as exc:
            if not create_device_if_missing or device_id is None or not is_set(device_id):
                raise exc

            Device.create(
                device_id=device_id,
                caller_org_id=self.org_id,
                roboto_client=self.__roboto_client,
            )

            self.__record = self.__roboto_client.put(
                f"/v1/datasets/{self.dataset_id}",
                data=request,
            ).to_record(DatasetRecord)

        return self

    def rename_directory(self, old_path: str, new_path: str) -> DirectoryRecord:
        """Rename or move a directory in the dataset.

        Both paths are relative to the dataset's root. A ``new_path`` with fewer components moves the directory up
        the tree; a different last component at the same depth renames it in place. It calls
        :py:meth:`~roboto.domain.files.FileSystem.rename_directory`, whose failures also apply.

        Args:
            old_path: Current path of the directory, such as ``"logs/session1"``.
            new_path: New path of the directory, such as ``"session1"`` to move it up one level.

        Returns:
            Record of the directory at its new path.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.rename_directory("logs/session1", "session1")
        """
        return self.files.rename_directory(old_path, new_path)

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:
        """Rename or move a file in the dataset.

        The file keeps its ID and versions; only its path changes. It calls
        :py:meth:`~roboto.domain.files.FileSystem.rename_file`, whose failures also apply.

        Args:
            file_id: ID of the file to rename or move.
            new_path: New path of the file, relative to the dataset's root, such as ``"file.bag"`` to move it to
                the root or ``"other_dir/file.bag"`` to move it into an existing directory.

        Returns:
            Record of the file at its new path.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> record = dataset.rename_file("fl_xyz789", "file.bag")
            >>> record.relative_path
            'file.bag'
        """
        return self.files.rename_file(file_id, new_path)

    def upload_directory(
        self,
        directory_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        delete_after_upload: bool = False,
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
        print_progress: bool = True,
        device_id: typing.Optional[str] = None,
    ) -> None:
        """Upload every file under a local directory, at any depth, to the dataset.

        Each file is uploaded to its path relative to ``directory_path``, so the dataset mirrors the local layout.
        It calls :py:meth:`~roboto.domain.files.FileSystem.upload_directory`, whose failures also apply.

        Args:
            directory_path: Local directory whose files to upload.
            include_patterns: Gitignore-style patterns for the files to upload. ``None`` uploads every file; an
                empty list uploads none.
            exclude_patterns: Gitignore-style patterns for files to skip. Takes precedence over
                ``include_patterns``.
            delete_after_upload: Whether to delete each uploaded local file once every upload has succeeded.
                Directories are kept.
            max_batch_size: Maximum number of files per upload batch. Each batch finishes uploading before the
                next starts.
            print_progress: Whether to show a progress bar during the upload.
            device_id: ID of the device that produced the files' data.

        Note:
            Patterns follow the gitignore format described at https://git-scm.com/docs/gitignore#_pattern_format,
            but each is matched against a file's name only, not its path under ``directory_path``. A pattern
            naming a directory, such as ``"__pycache__/"``, matches no file.

        Examples:
            Upload a directory, skipping compiled Python and log files:

            >>> import pathlib
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.upload_directory(
            ...     pathlib.Path("/path/to/directory"),
            ...     exclude_patterns=["*.pyc", "*.log"],
            ... )
        """
        self.files.upload_directory(
            directory_path,
            include_patterns,
            exclude_patterns,
            delete_after_upload,
            max_batch_size,
            print_progress,
            device_id,
        )

    def upload_file(
        self,
        file_path: pathlib.Path,
        file_destination_path: typing.Optional[str] = None,
        print_progress: bool = True,
        device_id: typing.Optional[str] = None,
    ) -> File:
        """Upload one local file to the dataset.

        It calls :py:meth:`~roboto.domain.files.FileSystem.upload_file`, whose failures also apply.

        Args:
            file_path: Local file to upload.
            file_destination_path: Path within the dataset to upload the file to. ``None`` uploads it to the
                dataset's root under its own name.
            print_progress: Whether to show a progress bar during the upload.
            device_id: ID of the device that produced the file's data.

        Returns:
            The uploaded file. Its record is fetched from Roboto the first time it is read.

        Examples:
            >>> import pathlib
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> file = dataset.upload_file(
            ...     pathlib.Path("/path/to/file.txt"),
            ...     file_destination_path="foo/bar.txt",
            ... )
        """
        return self.files.upload_file(file_path, file_destination_path, print_progress, device_id)

    def upload_files(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        file_destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
        print_progress: bool = True,
        device_id: typing.Optional[str] = None,
    ) -> dict[pathlib.Path, str]:
        """Upload several local files to the dataset.

        It calls :py:meth:`~roboto.domain.files.FileSystem.upload_files`, whose failures also apply.

        Args:
            files: Local files to upload.
            file_destination_paths: Path within the dataset to upload each local file to, keyed by local path.
                A file not in the mapping is uploaded to the dataset's root under its own name.
            max_batch_size: Maximum number of files per upload batch. Each batch finishes uploading before the
                next starts.
            print_progress: Whether to show a progress bar during the upload.
            device_id: ID of the device that produced the files' data.

        Returns:
            ID of the file each local path was uploaded as, keyed by local path.

        Examples:
            >>> import pathlib
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> file_ids = dataset.upload_files(
            ...     [pathlib.Path("/path/to/file.txt")],
            ...     file_destination_paths={
            ...         pathlib.Path("/path/to/file.txt"): "foo/bar.txt",
            ...     },
            ... )
            >>> print(file_ids[pathlib.Path("/path/to/file.txt")])
        """
        return self.files.upload_files(files, file_destination_paths, max_batch_size, print_progress, device_id)

    def __get_latest_summary(self) -> AISummary:
        return self.__roboto_client.get(f"v1/datasets/{self.dataset_id}/summary").to_record(AISummary)
