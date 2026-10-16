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
"""The most paths one :class:`MatchIngestionRulesRequest` may ask about."""


def _validate_include_patterns(patterns: list[str]) -> list[str]:
    return _refuse_negations(validate_nonzero_gitpath_specs(patterns))


def _validate_exclude_patterns(patterns: list[str]) -> list[str]:
    if any(pattern.strip() == "" for pattern in patterns):
        raise ValueError("Exclude patterns must not be empty or just whitespace.")
    return _refuse_negations(patterns)


def _refuse_negations(patterns: list[str]) -> list[str]:
    for pattern in patterns:
        if pattern.startswith("!"):
            raise ValueError(
                f"Pattern {pattern!r} starts with '!'; list it under exclude_patterns without the '!' instead."
            )
    return patterns


class CreateIngestionRuleRequest(pydantic.BaseModel):
    """Request payload to create an ingestion rule."""

    name: str
    description: typing.Optional[str] = None
    include_patterns: list[str]
    exclude_patterns: list[str] = pydantic.Field(default_factory=list)
    invocation: typing.Optional[ActionInvocationSpec] = None
    """How each matching upload is ingested. Its ``invocation_input`` selects only inputs beyond the uploaded
    file, which the rule's trigger always passes first. Required when :attr:`auto_ingest` is on."""
    auto_ingest: bool = True

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
    """Request payload to change an ingestion rule. Only the fields present in the payload change."""

    name: typing.Optional[str] = None
    description: typing.Optional[str] = None
    include_patterns: typing.Optional[list[str]] = None
    exclude_patterns: typing.Optional[list[str]] = None
    invocation: typing.Optional[ActionInvocationSpec] = None
    """Replaces the rule's whole invocation when present."""
    auto_ingest: typing.Optional[bool] = None
    """Turning this on enables the rule's trigger, creating it if the rule had none; turning it off disables it."""

    @pydantic.field_validator("include_patterns")
    @classmethod
    def _validate_include_patterns(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        return _validate_include_patterns(value) if value is not None else value

    @pydantic.field_validator("exclude_patterns")
    @classmethod
    def _validate_exclude_patterns(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        return _validate_exclude_patterns(value) if value is not None else value


class MatchIngestionRulesRequest(pydantic.BaseModel):
    """Request payload to ask which of an org's ingestion rules match each of some file paths."""

    paths: list[str] = pydantic.Field(max_length=MAX_MATCH_PATHS)
    """File paths relative to their dataset, e.g. ``logs/run_1.mcap``."""


class MatchIngestionRulesResponse(pydantic.BaseModel):
    """The rules matching each requested path, oldest rule first. A path no rule matches maps to an empty list."""

    matches: dict[str, list[IngestionRuleRecord]]


MAX_INGEST_FILES = 100
"""Most files one ``POST /v1/ingestion-rules/ingest`` takes."""


class IngestFilesRequest(pydantic.BaseModel):
    """Request payload to ingest existing files now with the org's rules that match them."""

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_INGEST_FILES)


class IngestFilesResponse(pydantic.BaseModel):
    results: list[IngestFileResult]
    """One result per requested file, in request order."""


class LatestIngestionRunsRequest(pydantic.BaseModel):
    """Request payload to look up the latest ingestion run on each of some files."""

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_MATCH_PATHS)


class LatestIngestionRunsResponse(pydantic.BaseModel):
    runs: dict[str, IngestionRun]
    """The latest run per file id. A file whose current upload no rule's trigger has run on, or that the caller may
    not view, is absent."""
