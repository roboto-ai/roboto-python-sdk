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
from ...experimental.sessions import Session
from ...http import RobotoClient
from ...logging import default_logger, maybe_pluralize
from ...progress import NoopProgressMonitor, TqdmProgressMonitor
from ...roboto_search import RobotoSearch
from ...storage import DownloadableFile, FileService
from .action_input import ActionInputRecord
from .file_resolver import InputFileResolver
from .session_resolver import InputSessionResolver
from .topic_resolver import InputTopicResolver

log = default_logger()

OptionallyDownloadedFile: typing.TypeAlias = tuple[File, pathlib.Path | None]
"""A file paired with the local path it was downloaded to, or with ``None`` when it was not downloaded."""


class ActionInputResolver:
    """Service that resolves an invocation's input selectors to the files, sessions, and topics they match.

    Roboto runs it while it prepares an invocation, before the action's code starts, and the action reads the result
    as :py:class:`~roboto.action_runtime.action_input.ActionInput`, from
    :py:meth:`~roboto.action_runtime.InvocationContext.get_input`. You can also run it yourself, to see what an
    :py:class:`~roboto.domain.actions.InvocationInput` resolves to while you test an action outside Roboto. Build one
    with ``from_env``.

    Args:
        file_resolver: :py:class:`~roboto.action_runtime.action_input.InputFileResolver` that resolves the input's
            file selectors.
        session_resolver: :py:class:`~roboto.action_runtime.action_input.InputSessionResolver` that resolves the
            input's session selectors.
        topic_resolver: :py:class:`~roboto.action_runtime.action_input.InputTopicResolver` that resolves the input's
            topic selectors.
        file_service: Service that downloads the resolved files when ``resolve_input_spec`` is called with
            ``download=True``.
    """

    @classmethod
    def from_env(
        cls,
        roboto_client: typing.Optional[RobotoClient] = None,
        roboto_search: typing.Optional[RobotoSearch] = None,
    ) -> ActionInputResolver:
        """Build a resolver whose lookups and downloads go through ``roboto_client``.

        Args:
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            roboto_search: :py:class:`~roboto.roboto_search.RobotoSearch` that runs the selectors' RoboQL queries,
                including the queries that look inputs up by name. Defaults to one that sends its queries through
                ``roboto_client``.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        roboto_search = roboto_search if roboto_search is not None else RobotoSearch.for_roboto_client(roboto_client)

        return cls(
            file_resolver=InputFileResolver(roboto_client, roboto_search),
            session_resolver=InputSessionResolver(roboto_client, roboto_search),
            topic_resolver=InputTopicResolver(roboto_client, roboto_search),
            file_service=FileService(roboto_client=roboto_client),
        )

    def __init__(
        self,
        file_resolver: InputFileResolver,
        session_resolver: InputSessionResolver,
        topic_resolver: InputTopicResolver,
        file_service: FileService,
    ):
        self.__file_resolver = file_resolver
        self.__session_resolver = session_resolver
        self.__topic_resolver = topic_resolver
        self.__file_service = file_service

    def resolve_input_spec(
        self,
        input_spec: InvocationInput,
        download: bool = False,
        download_path: typing.Optional[pathlib.Path] = None,
    ) -> ActionInputRecord:
        """Fetch the records that an input's file, session, and topic selectors match.

        Each file, session, and topic appears once, even when several selectors match it. When the input selects
        files, sessions, or topics and none match, that kind comes back empty, with a logged warning rather than an
        exception.

        With ``download=True``, each file is saved to ``<download_path>/<file_id>/<version>/<file_name>``, and a file
        already at that path with the stored file's size is not downloaded again. A link is saved under its own ID and
        version, with the contents of its target. Only files are downloaded: when topics or sessions also match, a
        warning says to read their data from the action's code.

        Args:
            input_spec: Input whose selectors to resolve.
            download: Whether to download the resolved files.
            download_path: Directory to download the files to. ``None`` creates a temporary directory. Ignored when
                ``download`` is ``False``.

        Returns:
            :py:class:`~roboto.action_runtime.action_input.ActionInputRecord` of the matched records. Each entry of
            its ``files`` pairs a file's record with the local path it was downloaded to, or with ``None`` when
            ``download`` is ``False``.

        Raises:
            RobotoNotFoundException: A selector names a dataset, file, session, or topic by an ID that matches
                nothing, or, with ``download=True``, a resolved file is a link whose target no longer exists.
            ExceptionGroup: With ``download=True``, one or more files still failed to download after three attempts.

        Examples:
            Resolve the files a RoboQL query matches, without downloading them:

            >>> from roboto.action_runtime import ActionInputResolver
            >>> from roboto.domain.actions import InvocationInput
            >>> resolver = ActionInputResolver.from_env()
            >>> input_spec = InvocationInput.file_query('dataset_id = "ds_12345" AND path LIKE "%.mcap"')
            >>> result = resolver.resolve_input_spec(input_spec)
            >>> for file_record, local_path in result.files:
            ...     print(file_record.relative_path, local_path)

            Resolve the same files and download them to a directory:

            >>> import pathlib
            >>> result = resolver.resolve_input_spec(input_spec, download=True, download_path=pathlib.Path("/tmp/data"))

            Resolve files and topics together:

            >>> from roboto.domain.actions import DataSelector, FileSelector
            >>> input_spec = InvocationInput(
            ...     files=FileSelector(query='dataset_id = "ds_12345" AND path LIKE "%.mcap"'),
            ...     topics=DataSelector(names=["battery_status", "gps"]),
            ... )
            >>> result = resolver.resolve_input_spec(input_spec)
        """
        files: list[File] = []
        topics: list[Topic] = []
        sessions: list[Session] = []

        if input_spec.files:
            files = self.__file_resolver.resolve_all(input_spec.safe_files)
            if not files:
                log.warning("No files matched the provided input specification.")

        if input_spec.sessions:
            sessions = self.__session_resolver.resolve_all(input_spec.safe_sessions)
            if not sessions:
                log.warning("No sessions matched the provided input specification.")

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

            if sessions:
                log.warning(
                    "Session data cannot be downloaded during action invocation setup. "
                    "Use session.get_topic(name) or session.list_topics() in your action code to reach a "
                    "session's topics, then get_data() or get_data_as_df() on each. Topics obtained this way "
                    "read only the session's data by default. "
                    "See: https://docs.roboto.ai/reference/python-sdk/roboto/experimental/sessions/session/index.html"
                )

        return ActionInputRecord(
            files=[(file.record, path) for file, path in resolved_files],
            sessions=[session.record for session in sessions],
            topics=[topic.record for topic in topics],
        )

    def __download_files(
        self,
        out_path: pathlib.Path,
        files: collections.abc.Iterable[File],
    ) -> list[tuple[File, pathlib.Path]]:
        """Download ``files`` under ``out_path``, skipping each one already saved there at the stored file's size.

        Returns:
            Each file paired with its local path, including the files that were skipped.
        """

        class DownloadCandidate(typing.NamedTuple):
            file: File
            source: File
            """File whose contents are downloaded: ``file`` itself, or for a link, its target at the pinned version."""
            path: pathlib.Path
            requires_download: bool

        # Grouped by the resource that owns the downloaded contents, since a link's target can belong to a different
        # dataset, device, or organization than the link, and each FileService.download call reads with credentials
        # for one resource.
        download_candidates_by_association: dict[str, list[DownloadCandidate]] = collections.defaultdict(list)

        for file in files:
            local_path = out_path / file.file_id / str(file.version) / pathlib.Path(file.relative_path).name
            source = file._resolve_link()

            requires_download = True
            if local_path.exists():
                local_file_size_matches_remote = local_path.stat().st_size == source.record.size
                if local_file_size_matches_remote:
                    log.debug(
                        "%s (%s@v%d) already downloaded.",
                        file.relative_path,
                        file.file_id,
                        file.version,
                    )
                    requires_download = False

            download_candidates_by_association[source.association.association_id].append(
                DownloadCandidate(file=file, source=source, path=local_path, requires_download=requires_download)
            )

        total_size = sum(
            candidate.source.record.size
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
                        "bucket_name": candidate.source.record.bucket,
                        "source_uri": candidate.source.record.uri,
                        "destination_path": candidate.path,
                    }
                    for candidate in candidates
                    if candidate.requires_download
                ]

                if downloadable:
                    self.__file_service.download(
                        files=downloadable,
                        association=Association.from_id(association_id),
                        on_progress=progress_monitor.update,
                    )

        return [
            (candidate.file, candidate.path)
            for candidates in download_candidates_by_association.values()
            for candidate in candidates
        ]
