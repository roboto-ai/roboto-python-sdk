# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import pathlib
import tempfile
import typing

from ...domain.actions import InvocationInput
from ...domain.files import File, FileDownloader
from ...domain.topics import Topic
from ...http import RobotoClient
from ...logging import default_logger
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
            file_downloader=FileDownloader(roboto_client),
        )

    def __init__(
        self,
        file_resolver: InputFileResolver,
        topic_resolver: InputTopicResolver,
        file_downloader: FileDownloader,
    ):
        self.input_file_resolver = file_resolver
        self.input_topic_resolver = topic_resolver
        self.file_downloader = file_downloader

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
            files = self.input_file_resolver.resolve_all(input_spec.safe_files)
            if not files:
                log.warning("No files matched the provided input specification.")

        if input_spec.topics:
            topics = self.input_topic_resolver.resolve_all(input_spec.safe_topics)
            if not topics:
                log.warning("No topics matched the provided input specification.")

        resolved_files: collections.abc.Sequence[OptionallyDownloadedFile] = [(file, None) for file in files]
        if download:
            if download_path is None:
                download_path = pathlib.Path(tempfile.mkdtemp())
            log.info(f"Downloading {len(files)} file(s) ...")
            resolved_files = self.file_downloader.download_files(download_path, files)

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
