# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections
import collections.abc
import pathlib
import tempfile
import typing

from ...association import Association
from ...domain.actions import InvocationInput
from ...domain.files import File
from ...domain.topics import Topic
from ...fs import DownloadableFile, FileService
from ...http import RobotoClient
from ...logging import default_logger, maybe_pluralize
from ...progress import NoopProgressMonitor, TqdmProgressMonitor
from ...roboto_search import RobotoSearch
from .action_input import ActionInputRecord
from .file_resolver import InputFileResolver
from .topic_resolver import InputTopicResolver

log = default_logger()

OptionallyDownloadedFile: typing.TypeAlias = tuple[File, pathlib.Path | None]


class ActionInputResolver:
    """
    Resolves the action invocation input spec to concrete Roboto entities.

    The entities are packaged together in an `ActionInput` instance,
    which is available to action code via `ActionRuntime`.
    """

    @classmethod
    def from_env(
        cls,
        roboto_client: typing.Optional[RobotoClient] = None,
        roboto_search: typing.Optional[RobotoSearch] = None,
    ) -> ActionInputResolver:
        roboto_client = RobotoClient.defaulted(roboto_client)
        roboto_search = roboto_search if roboto_search is not None else RobotoSearch.for_roboto_client(roboto_client)

        return cls(
            file_resolver=InputFileResolver(roboto_client, roboto_search),
            topic_resolver=InputTopicResolver(roboto_client, roboto_search),
            file_service=FileService(roboto_client=roboto_client),
        )

    def __init__(
        self,
        file_resolver: InputFileResolver,
        topic_resolver: InputTopicResolver,
        file_service: FileService,
    ):
        self.__file_resolver = file_resolver
        self.__topic_resolver = topic_resolver
        self.__file_service = file_service

    def resolve_input_spec(
        self,
        input_spec: InvocationInput,
        download: bool = False,
        download_path: typing.Optional[pathlib.Path] = None,
    ) -> ActionInputRecord:
        """This method takes an InvocationInput containing data selectors (e.g., for files and topics)
        and resolves them to concrete entities.

        Optionally downloads files to a local path.

        Args:
            input_spec: Input specification containing data selectors.
                See :py:class:`~roboto.domain.actions.InvocationInput` for more detail.
            download: If True, download all resolved files to local disk. Defaults to False.
            download_path: Directory path where files should be downloaded.
                If not provided and download=True, a temporary directory will be created.
                Ignored if download=False.

        Returns:
            ActionInputRecord containing:
            - files: List of (FileRecord, Optional[Path]) tuples. Path is None if download=False,
              otherwise contains the local path where the file was downloaded.
            - topics: List of TopicRecord instances.

        Examples:
            Resolve files using a RoboQL query without downloading:

            >>> input_spec = InvocationInput.file_query('dataset_id = "ds_abc123" AND path LIKE "%.mcap"')
            >>> result = resolver.resolve_input_spec(input_spec)
            >>> # result.files contains (FileRecord, None) tuples
            >>> # result.topics is empty

            Resolve and download files to a specific directory:

            >>> input_spec = InvocationInput.file_query('dataset_id = "ds_abc123" AND path LIKE "%.mcap"')
            >>> result = resolver.resolve_input_spec(input_spec, download=True, download_path=Path("/tmp/data"))
            >>> # result.files contains (FileRecord, Path) tuples with local paths

            Resolve both files and topics:

            >>> input_spec = InvocationInput(
            ...     files=FileSelector(query='dataset_id = "ds_abc123" AND path LIKE "%.mcap"'),
            ...     topics=DataSelector(names=["battery_status", "gps"]),
            ... )
            >>> result = resolver.resolve_input_spec(input_spec)
            >>> # result.files contains file records
            >>> # result.topics contains topic records
        """
        files: list[File] = []
        topics: list[Topic] = []

        if input_spec.files:
            files = self.__file_resolver.resolve_all(input_spec.safe_files)
            if not files:
                log.warning("No files matched the provided input specification.")

        if input_spec.topics:
            topics = self.__topic_resolver.resolve_all(input_spec.safe_topics)
            if not topics:
                log.warning("No topics matched the provided input specification.")

        resolved_files: collections.abc.Sequence[OptionallyDownloadedFile] = [(file, None) for file in files]
        if download:
            if download_path is None:
                download_path = pathlib.Path(tempfile.mkdtemp())
            log.info("Downloading {%d} file(s) ...", len(files))
            resolved_files = self.__download_files(download_path, files)

            if topics:
                log.warning(
                    "Topic data cannot be downloaded during action invocation setup. "
                    "Use topic.get_data() or topic.get_data_as_df() in your action code to access topic data. "
                    "See: https://docs.roboto.ai/reference/python-sdk/roboto/domain/topics/topic/index.html"
                )

        return ActionInputRecord(
            files=[(file.record, path) for file, path in resolved_files],
            topics=[topic.record for topic in topics],
        )

    def __download_files(
        self,
        out_path: pathlib.Path,
        files: collections.abc.Iterable[File],
    ) -> list[tuple[File, pathlib.Path]]:
        """
        Downloads the specified files to the provided local directory.

        Files already present locally with matching size are skipped.

        Args:
            out_path: Destination directory for the downloaded files.
            files: Files to download.

        Returns:
            A list of (File, Path) tuples, relating each provided file to its download path.
        """

        class DownloadCandidate(typing.NamedTuple):
            file: File
            path: pathlib.Path
            requires_download: bool

        download_candidates_by_association: dict[str, list[DownloadCandidate]] = collections.defaultdict(list)

        for file in files:
            local_path = out_path / file.file_id / str(file.version) / pathlib.Path(file.relative_path).name

            # Skip download if file already exists locally with matching size
            requires_download = True
            if local_path.exists():
                local_file_size_matches_remote = local_path.stat().st_size == file.record.size
                if local_file_size_matches_remote:
                    log.debug(
                        "%s (%s@v%d) already downloaded.",
                        file.relative_path,
                        file.file_id,
                        file.version,
                    )
                    requires_download = False

            download_candidates_by_association[file.dataset_id].append(
                DownloadCandidate(file=file, path=local_path, requires_download=requires_download)
            )

        # Calculate total size of files that need downloading
        total_size = sum(
            candidate.file.record.size
            for candidates in download_candidates_by_association.values()
            for candidate in candidates
            if candidate.requires_download
        )
        file_count = sum(
            1
            for candidates in download_candidates_by_association.values()
            for candidate in candidates
            if candidate.requires_download
        )

        progress_monitor = (
            TqdmProgressMonitor(
                total=total_size,
                desc=f"Downloading {file_count} {maybe_pluralize('file', file_count)}",
            )
            if file_count > 0
            else NoopProgressMonitor()
        )

        with progress_monitor:
            for association_id, candidates in download_candidates_by_association.items():
                downloadable: list[DownloadableFile] = [
                    {
                        "bucket_name": candidate.file.record.bucket,
                        "source_uri": candidate.file.record.uri,
                        "destination_path": candidate.path,
                    }
                    for candidate in candidates
                    if candidate.requires_download
                ]

                if downloadable:
                    self.__file_service.download(
                        files=downloadable,
                        association=Association.dataset(association_id),
                        on_progress=progress_monitor.update,
                    )

        return [
            (candidate.file, candidate.path)
            for candidates in download_candidates_by_association.values()
            for candidate in candidates
        ]
