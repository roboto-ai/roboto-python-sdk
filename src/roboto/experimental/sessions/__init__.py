# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Sessions: operational time windows of a device, such as a drone flight, a vehicle drive, or a robot run.

Use :py:class:`~roboto.experimental.sessions.Session` to create sessions, add files to them, mark them complete, and
read their topic data. Pass :py:class:`~roboto.experimental.sessions.SessionDeclaration` to
:py:meth:`~roboto.domain.devices.Device.create_sessions` to create sessions with their files in one call, declaring
each file's topics with :py:class:`~roboto.experimental.ingest.TopicDeclaration`.
"""

from .operations import (
    MAX_INGESTION_SUMMARIES,
    MAX_SESSION_DEVICES_REQUEST,
    MAX_SESSIONS_PER_REQUEST,
    CreateSessionIfNotExistsRequest,
    FileDeclaration,
    SessionDeclaration,
    SessionDevicesRequest,
    SessionDevicesResponse,
    SessionFile,
    SessionIngestionSummariesRequest,
    SessionIngestionSummariesResponse,
    SkipWaitingRequest,
)
from .record import (
    CompletionPolicy,
    PendingIngestionFile,
    SessionDevice,
    SessionFileRecord,
    SessionFileView,
    SessionIngestionState,
    SessionIngestionStatus,
    SessionIngestionSummary,
    SessionRecord,
    SessionStatus,
    SessionTopicFieldStats,
    SessionTopicRecord,
    SessionTopicSchema,
    SessionTopicStats,
    SessionTopicStatsRun,
    SessionTopicStatsRunStatus,
    SkippedIngestionFile,
    SkipWaitingResponse,
)
from .session import Session

__all__ = (
    "MAX_INGESTION_SUMMARIES",
    "MAX_SESSION_DEVICES_REQUEST",
    "MAX_SESSIONS_PER_REQUEST",
    "CompletionPolicy",
    "CreateSessionIfNotExistsRequest",
    "FileDeclaration",
    "PendingIngestionFile",
    "Session",
    "SessionDeclaration",
    "SessionDevice",
    "SessionDevicesRequest",
    "SessionDevicesResponse",
    "SessionFile",
    "SessionFileRecord",
    "SessionFileView",
    "SessionIngestionState",
    "SessionIngestionStatus",
    "SessionIngestionSummariesRequest",
    "SessionIngestionSummariesResponse",
    "SessionIngestionSummary",
    "SessionRecord",
    "SessionStatus",
    "SessionTopicFieldStats",
    "SessionTopicRecord",
    "SessionTopicSchema",
    "SessionTopicStats",
    "SessionTopicStatsRun",
    "SessionTopicStatsRunStatus",
    "SkipWaitingRequest",
    "SkipWaitingResponse",
    "SkippedIngestionFile",
)
