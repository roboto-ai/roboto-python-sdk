# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compose sessions: the operational time windows of a device, and the files that belong to them.

A session can be created empty and composed file by file, or declared whole, with its files and the topic
data they carry, in one call. The types describing a file's contents live in
:py:mod:`roboto.experimental.ingest`.
"""

from .operations import (
    MAX_INGESTION_SUMMARIES,
    MAX_SESSIONS_PER_REQUEST,
    CreateSessionIfNotExistsRequest,
    FileDeclaration,
    SessionDeclaration,
    SessionFile,
    SessionIngestionSummariesRequest,
    SessionIngestionSummariesResponse,
    SkipWaitingRequest,
)
from .record import (
    CompletionPolicy,
    PendingIngestionFile,
    SessionFileRecord,
    SessionFileView,
    SessionIngestionState,
    SessionIngestionStatus,
    SessionIngestionSummary,
    SessionRecord,
    SessionStatus,
    SkippedIngestionFile,
    SkipWaitingResponse,
)
from .session import Session

__all__ = (
    "MAX_INGESTION_SUMMARIES",
    "MAX_SESSIONS_PER_REQUEST",
    "CompletionPolicy",
    "CreateSessionIfNotExistsRequest",
    "FileDeclaration",
    "PendingIngestionFile",
    "Session",
    "SessionDeclaration",
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
    "SkipWaitingRequest",
    "SkipWaitingResponse",
    "SkippedIngestionFile",
)
