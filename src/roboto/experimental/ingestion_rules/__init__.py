# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Ingestion rules: path patterns that mark an organization's files ingestable, and the action that ingests them.

While a rule's ``auto_ingest`` is on, Roboto runs the rule's action on each upload of a file the rule matches.
``IngestionRuleRecord`` holds a rule; ``CreateIngestionRuleRequest`` and ``UpdateIngestionRuleRequest`` create and
update one, ``IngestFilesRequest`` ingests files already uploaded, and ``IngestionPathRule`` tests a path against a
rule's patterns without a request to Roboto. Send the models to the routes under ``/v1/ingestion-rules`` with
:py:class:`~roboto.http.RobotoClient`: for example,
``RobotoClient.defaulted().get("v1/ingestion-rules").to_record_list(IngestionRuleRecord, json_path=["data", "items"])``
lists the organization's rules. No SDK method sends or returns these models.
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
