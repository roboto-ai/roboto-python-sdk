# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from .compat import StrEnum


class RobotoApiVersion(StrEnum):
    """Enumeration of supported Roboto API versions.

    This enum defines the available API versions for the Roboto platform. Each version
    represents a specific date-based API version that may include breaking changes,
    new features, or deprecations compared to previous versions.

    API versions follow the YYYY-MM-DD format and are used to ensure backward
    compatibility while allowing the platform to evolve. Clients should specify
    the API version they were designed for to ensure consistent behavior.
    """

    v2025_01_01 = "2025-01-01"
    v2025_07_14 = "2025-07-14"

    v2026_01_02 = "2026-01-02"
    """Release date for v0.35.0 of the Roboto Python SDK"""

    v2026_02_02 = "2026-02-02"
    """Content mode introduced for query APIs."""

    v2026_02_11 = "2026-02-11"
    """path_in_schema is now a required field on AddMessagePathRequest"""

    v2026_03_13 = "2026-03-13"
    """Query endpoints are now eventually consistent when using v2026_03_13 or later.
    Clients on older API versions maintain strong consistency for backward compatibility."""

    v2026_05_20 = "2026-05-20"
    """AgentSession and AI Chat are renamed to AgentThread across the SDK and REST API:
    ``chat_id`` / ``session_id`` become ``thread_id`` on the wire, ``/v1/ai/chats`` becomes
    ``/v1/ai/threads``, and agent ``invoke`` becomes ``launch`` (``POST /v1/ai/agents/{id}/launch``;
    the previous developer-only ``…/invoke`` URL was removed outright). Clients on older API
    versions continue to receive ``session_id`` in response bodies and can keep calling the
    legacy ``/v1/ai/chats`` paths, which are soft-deprecated aliases on the same handlers."""

    v2026_07_05 = "2026-07-05"
    """``PUT /v1/files/upload/<id>/progress`` responds with ``{uri, file_id}`` pairs instead of a
    bare file-id list, so upload clients can tell which created file belongs to which uploaded
    path. Clients on older API versions continue to receive the bare id list."""

    v2026_08_10 = "2026-08-10"
    """``GET /v1/datasets/tags``, ``GET /v1/events/tags``, and ``GET /v1/files/tags`` respond with a
    paginated ``{items, next_token}`` object (with optional ``search``/``limit``/``page_token``
    query parameters) instead of a bare string list, so tag autocomplete scales past the unique-tag
    cap. Clients on older API versions continue to receive the bare list."""

    v2026_08_27 = "2026-08-27"
    """``/v1/triggers`` speaks the v2 trigger shape (``events``/``once_per``/``targets`` from
    :mod:`roboto.domain.triggers`) instead of the legacy ``causes``/``for_each``/action-column
    shape, and rejects a caller-supplied ``service_user_id``. Clients on older API versions keep
    the legacy shape: their creates and updates are translated onto v2 triggers, responses are
    projected back, and triggers with no legacy representation (multiple targets, non-action
    targets, new event types) are filtered from lists and 404 on direct reads."""

    v2026_09_30 = "2026-09-30"
    """Agent thread messages can carry ``client_context`` content blocks: what the user was viewing
    when they sent the message, stored on the message itself. Clients on older API versions receive
    threads with those blocks removed, since their ``AgentContent`` union cannot parse them."""

    v2026_10_02 = "2026-10-02"
    """A file record can be a link: ``fs_type`` ``"link"`` and a ``roboto://`` uri pinning one version of another
    file. Clients on older API versions, whose ``FSType`` has only ``file`` and ``directory``, never receive one: links
    are dropped from file listings, and reading one directly by ID or path reports it as not found."""

    v2026_10_05 = "2026-10-05"
    """``POST /v2/topics/id/<topic_id>/read-plan`` states the bounds each partition's rows are selected in
    on a per-partition ``window``, instead of the ``extent`` it returned before.
    Clients on older API versions continue to receive ``extent``, set on every partition to the plan's own window;
    such a client selects rows by the plan's window alone.
    Two kinds of read are refused with HTTP 400 and a message to upgrade rather than served that way:
    a read scoped to a Session that holds a file over only part of the requested time span,
    and a read covering a file that packs several partitions' data.
    Either would otherwise return rows belonging to another Session, or to another partition packed into the same file.

    Adding files to a Session, removing them, and publishing metrics answer with one element per entry the
    request named, in the order it named them, each holding the entry's result or the error that refused
    it. An entry the platform refuses leaves the others in place: an add decides every refusal before writing
    anything and adds the rest together, and a remove removes together every file the Session holds and reports
    the rest as not held. A failure the platform did not anticipate, such as a timeout, adds or removes none of
    them. An add naming a file that does not exist is refused whole, before any entry is applied. A file entry
    states the window the Session holds the file over in the file's own timestamps, on ``min_file_timestamp_ns``
    and ``max_file_timestamp_ns``, and a call names at least one file. Listing a Session's files reports each
    file's window in Unix-epoch nanoseconds on ``min_wall_clock_timestamp_ns`` and
    ``max_wall_clock_timestamp_ns``.

    Clients on older API versions keep the earlier contract for these four calls. Listing a Session's files
    reports the same window on ``range_min_timestamp_ns`` and ``range_max_timestamp_ns``. A file entry carries
    the file's id, an optional ``data_range``, and a window in Unix-epoch nanoseconds on
    ``range_min_timestamp_ns`` and ``range_max_timestamp_ns``. Adds and removes accept a call naming no
    files and answer with the Session's refreshed record. An add stands or falls whole: when the platform
    refuses a file, it answers with the error for the first refused file and adds none of them, and a file
    named twice is added over its last entry. A remove stands or falls whole too, and skips a file the
    Session does not hold. Metric publication answers with a ``succeeded`` list and a ``failed`` list.
    ``succeeded`` holds one record per metric and Session, carrying the last value written when a call published
    the same pair more than once; each entry in ``failed`` is named by the metric name the caller submitted.
    """

    @staticmethod
    def latest() -> RobotoApiVersion:
        """Get the newest API version this build of the SDK knows about.

        Requests carry this version unless the caller names an older one.

        Returns:
            The most recent member of this enum.
        """
        return RobotoApiVersion.v2026_10_05

    def is_latest(self) -> bool:
        """Check if this API version is the latest available version.

        Returns:
            True if this version matches the latest API version, False otherwise.
        """
        return self == RobotoApiVersion.latest()

    def __str__(self) -> str:
        """Return the string representation of the API version.

        Returns:
            The API version string in YYYY-MM-DD format.
        """
        return self.value
