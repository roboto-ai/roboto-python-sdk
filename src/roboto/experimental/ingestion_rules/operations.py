# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...domain.triggers import ActionInvocationSpec
from ...pydantic.validators import validate_nonzero_gitpath_specs
from ..ingestion_runs import IngestionRun
from .record import IngestFileResult, IngestionRuleRecord

MAX_MATCH_PATHS = 200
"""Maximum number of paths in a ``MatchIngestionRulesRequest``, and of file IDs in a ``LatestIngestionRunsRequest``."""


def _validate_include_patterns(patterns: list[str]) -> list[str]:
    return _refuse_negations(validate_nonzero_gitpath_specs(patterns))


def _validate_exclude_patterns(patterns: list[str]) -> list[str]:
    if any(pattern.strip() == "" for pattern in patterns):
        raise ValueError("Exclude patterns must not be empty or just whitespace.")
    return _refuse_negations(patterns)


def _refuse_negations(patterns: list[str]) -> list[str]:
    """Reject a pattern starting with ``!``.

    A rule matches a path when any one include pattern matches it and no exclude pattern does, so a path to leave
    out belongs in ``exclude_patterns``.
    """
    for pattern in patterns:
        if pattern.startswith("!"):
            raise ValueError(
                f"Pattern {pattern!r} starts with '!'; list it under exclude_patterns without the '!' instead."
            )
    return patterns


class CreateIngestionRuleRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/ingestion-rules``.

    Only organization administrators may send it. A ``name`` another rule in the organization has raises
    ``RobotoConflictException``. An ``invocation`` Roboto cannot run, such as one naming an action that does not
    exist, raises ``RobotoInvalidRequestException``, and one whose ``upload_destination`` the caller cannot upload to
    raises ``RobotoUnauthorizedException``. Building it raises ``pydantic.ValidationError`` when:

    - ``include_patterns`` is empty or holds only blank patterns.
    - ``exclude_patterns`` holds a blank pattern.
    - A pattern starts with ``!``.
    - ``auto_ingest`` is on and ``invocation`` is ``None``.
    """

    name: str
    """Human-readable name of the rule, unique within its organization."""

    description: typing.Optional[str] = None
    include_patterns: list[str]
    """Gitignore-style patterns matched against each file's path within its dataset, such as ``**/*.mcap``.

    A file that any of them matches, and no exclude pattern matches, is ingestable.
    """

    exclude_patterns: list[str] = pydantic.Field(default_factory=list)
    """Gitignore-style patterns for files the rule leaves out even when an include pattern matches them.

    Defaults to none.
    """

    invocation: typing.Optional[ActionInvocationSpec] = None
    """Invocation of the action that ingests each matching upload.

    The rule's trigger passes the uploaded file as the first input, so ``invocation_input`` selects only the inputs
    after it. Required when ``auto_ingest`` is on.
    """

    auto_ingest: bool = True
    """Whether Roboto ingests matching uploads automatically, through the rule's trigger.

    When off, matching files are still marked ingestable.
    """

    @pydantic.field_validator("include_patterns")
    @classmethod
    def _validate_include_patterns(cls, value: list[str]) -> list[str]:
        return _validate_include_patterns(value)

    @pydantic.field_validator("exclude_patterns")
    @classmethod
    def _validate_exclude_patterns(cls, value: list[str]) -> list[str]:
        return _validate_exclude_patterns(value)

    @pydantic.model_validator(mode="after")
    def _require_invocation_to_auto_ingest(self) -> "CreateIngestionRuleRequest":
        if self.auto_ingest and self.invocation is None:
            raise ValueError("A rule that auto-ingests needs an invocation.")
        return self


class UpdateIngestionRuleRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/ingestion-rules/{rule_id}``.

    A field the request does not set is unchanged. Setting a field to ``None`` is not the same as leaving it out;
    each field says what ``None`` does. New patterns decide only for files uploaded afterward; files already uploaded
    keep whether they are ingestable.

    Only organization administrators may send it. A ``rule_id`` that matches no rule raises
    ``RobotoNotFoundException``, and a ``name`` another rule in the organization has raises
    ``RobotoConflictException``. A new ``invocation`` raises the exceptions ``CreateIngestionRuleRequest`` describes for
    one. Building it raises ``pydantic.ValidationError`` when ``include_patterns`` or ``exclude_patterns`` breaks the
    rules ``CreateIngestionRuleRequest`` gives for them.
    """

    name: typing.Optional[str] = None
    """Human-readable name of the rule, unique within its organization.

    ``None`` raises ``RobotoInvalidRequestException``.
    """

    description: typing.Optional[str] = None
    """Human-readable description of the rule. ``None`` clears it."""

    include_patterns: typing.Optional[list[str]] = None
    """Patterns that replace the rule's include patterns, as ``CreateIngestionRuleRequest.include_patterns`` describes.

    ``None`` raises ``RobotoInvalidRequestException``.
    """

    exclude_patterns: typing.Optional[list[str]] = None
    """Patterns that replace the rule's exclude patterns. ``None`` clears them."""

    invocation: typing.Optional[ActionInvocationSpec] = None
    """Invocation that replaces the rule's whole invocation.

    Setting one on a rule that has none creates the rule's trigger. ``None`` raises ``RobotoInvalidRequestException``.
    """

    auto_ingest: typing.Optional[bool] = None
    """Whether Roboto ingests matching uploads automatically.

    ``True`` enables the rule's trigger and ``False`` disables it. ``None`` leaves it unchanged. Turning it on for a
    rule with no invocation raises ``RobotoInvalidRequestException`` unless the request also sets ``invocation``.
    """

    @pydantic.field_validator("include_patterns")
    @classmethod
    def _validate_include_patterns(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        return _validate_include_patterns(value) if value is not None else value

    @pydantic.field_validator("exclude_patterns")
    @classmethod
    def _validate_exclude_patterns(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        return _validate_exclude_patterns(value) if value is not None else value


class MatchIngestionRulesRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/ingestion-rules/match``.

    Roboto reports which of the organization's ingestion rules match each path, deciding as it does when it marks an
    uploaded file ingestable. Building it raises ``pydantic.ValidationError`` when ``paths`` holds more than 200
    paths.
    """

    paths: list[str] = pydantic.Field(max_length=MAX_MATCH_PATHS)
    """File paths within their dataset, such as ``logs/run_1.mcap``, at most 200 (``MAX_MATCH_PATHS``)."""


class MatchIngestionRulesResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/ingestion-rules/match``."""

    matches: dict[str, list[IngestionRuleRecord]]
    """Rules that match each requested path, oldest rule first, keyed by the path as the request gave it.

    A path no rule matches, or one with a component that starts with a dot, maps to an empty list.
    """


MAX_INGEST_FILES = 100
"""Maximum number of file IDs in an ``IngestFilesRequest``."""


class IngestFilesRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/ingestion-rules/ingest``.

    Roboto ingests each file now with the organization's auto-ingesting rules that match it, as an upload of the file
    would have; this is also how a failed ingestion runs again. The caller needs edit access to each file. Building
    it raises ``pydantic.ValidationError`` when ``file_ids`` is empty or holds more than 100 IDs.
    """

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_INGEST_FILES)
    """IDs of the files to ingest, from 1 to 100 (``MAX_INGEST_FILES``)."""


class IngestFilesResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/ingestion-rules/ingest``."""

    results: list[IngestFileResult]
    """One result per entry of the request's ``file_ids``, in the same order."""


class LatestIngestionRunsRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/ingestion-rules/runs/latest``.

    Roboto returns the latest ingestion run on each file. Building it raises ``pydantic.ValidationError`` when
    ``file_ids`` is empty or holds more than 200 IDs.
    """

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_MATCH_PATHS)
    """IDs of the files to look up, from 1 to 200 (``MAX_MATCH_PATHS``)."""


class LatestIngestionRunsResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/ingestion-rules/runs/latest``."""

    runs: dict[str, IngestionRun]
    """Latest ingestion run on each file's current upload, keyed by file ID.

    A file the caller cannot view, or whose current upload no rule's trigger has run on, is absent.
    """
