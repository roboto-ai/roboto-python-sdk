# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Request and response models for an org's ingestion rules, which decide which uploaded files are ingested
and with which action.

A rule has path patterns and the action that ingests matching files. A file whose path a rule matches when it
is uploaded is ingestable, and while the rule's ``auto_ingest`` is on, Roboto runs that action on it. There is
no client class yet: call the ``/v1/ingestion-rules`` endpoints with :py:class:`~roboto.http.RobotoClient`.

Examples:
    List the org's rules:

    >>> from roboto.experimental.ingestion_rules import IngestionRuleRecord
    >>> from roboto.http import RobotoClient
    >>> rules = (
    ...     RobotoClient.defaulted()
    ...     .get("v1/ingestion-rules")
    ...     .to_record_list(IngestionRuleRecord, json_path=["data", "items"])
    ... )
"""

from ..ingestion_runs import IngestionRun, IngestionRunStatus
from .matching import IngestionPathRule
from .operations import (
    MAX_INGEST_FILES,
    MAX_MATCH_PATHS,
    CreateIngestionRuleRequest,
    IngestFilesRequest,
    IngestFilesResponse,
    LatestIngestionRunsRequest,
    LatestIngestionRunsResponse,
    MatchIngestionRulesRequest,
    MatchIngestionRulesResponse,
    UpdateIngestionRuleRequest,
)
from .record import (
    DefaultIngestionRuleRecord,
    ExistingFilesPreview,
    IngestFileOutcome,
    IngestFileResult,
    IngestionRuleRecord,
)

__all__ = (
    "MAX_INGEST_FILES",
    "MAX_MATCH_PATHS",
    "CreateIngestionRuleRequest",
    "DefaultIngestionRuleRecord",
    "ExistingFilesPreview",
    "IngestFileOutcome",
    "IngestFileResult",
    "IngestFilesRequest",
    "IngestFilesResponse",
    "IngestionPathRule",
    "IngestionRuleRecord",
    "IngestionRun",
    "IngestionRunStatus",
    "LatestIngestionRunsRequest",
    "LatestIngestionRunsResponse",
    "MatchIngestionRulesRequest",
    "MatchIngestionRulesResponse",
    "UpdateIngestionRuleRequest",
)
