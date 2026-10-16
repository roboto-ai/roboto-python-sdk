# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...domain.triggers import ActionInvocationSpec


class IngestionRuleRecord(pydantic.BaseModel):
    """Wire format of an ingestion rule: which file paths in an org are ingestable, and how they are ingested.

    A file whose path matches any of :attr:`include_patterns` and none of :attr:`exclude_patterns` is marked
    ingestable when it is created. The rule owns one trigger (:attr:`trigger_id`) that runs :attr:`invocation` on
    each matching upload while :attr:`auto_ingest` is on.
    """

    rule_id: str
    org_id: str
    name: str
    description: typing.Optional[str] = None
    include_patterns: list[str]
    """Git wildmatch patterns, e.g. ``**/*.mcap``. A file matching any of them is ingestable."""
    exclude_patterns: list[str] = pydantic.Field(default_factory=list)
    """Git wildmatch patterns. A file matching any of them is not ingestable by this rule."""
    invocation: typing.Optional[ActionInvocationSpec] = None
    """How each matching upload is ingested. The trigger passes the uploaded file as the first input, followed by
    whatever ``invocation.invocation_input`` selects. ``None`` only on a rule that does not auto-ingest."""
    auto_ingest: bool
    """Whether matching uploads are ingested automatically: whether the rule's trigger is enabled. Turning this off
    disables the trigger and leaves matching files ingestable."""
    trigger_id: typing.Optional[str] = None
    """The trigger that runs :attr:`invocation` on matching uploads, enabled while :attr:`auto_ingest` is on. Only
    the rule can enable, disable, edit or delete it. ``None`` while the rule has no invocation."""
    created: datetime.datetime
    created_by: str
    modified: datetime.datetime
    modified_by: str


class DefaultIngestionRuleRecord(pydantic.BaseModel):
    """Wire format of a rule Roboto offers every org as a starting point for a new rule, and whether the caller's
    org already has it.

    ``POST /v1/ingestion-rules/defaults`` creates those with :attr:`for_new_orgs` set that are not
    :attr:`already_present`.
    """

    name: str
    category: str = "Other"
    """The group the rule is listed under, such as ``ROS`` or ``Tabular``."""
    include_patterns: list[str]
    exclude_patterns: list[str] = pydantic.Field(default_factory=list)
    invocation: ActionInvocationSpec
    already_present: bool
    """Whether the org has a rule with this name, or a rule with one of these include patterns."""
    for_new_orgs: bool = True
    """Whether sign-up offers this rule and ``POST /v1/ingestion-rules/defaults`` creates it. When false, the rule is
    only offered as a starting point for a new rule."""
    needs_settings: bool = False
    """Whether the rule's action likely needs settings for the org's files, such as which column holds the
    timestamps, before it ingests them."""


class IngestFileOutcome(StrEnum):
    """What ``POST /v1/ingestion-rules/ingest`` did with one file."""

    Started = "started"
    """A matching rule's trigger started ingesting the file."""

    AlreadyRunning = "already_running"
    """An ingestion run on the file is still queued or running, so no new one was started."""

    NoMatchingRule = "no_matching_rule"
    """No rule in the file's org matches its path."""

    AutoIngestOff = "auto_ingest_off"
    """Rules match the file, but none of them auto-ingests."""

    NotStarted = "not_started"
    """A matching rule's trigger declined the file (it is disabled, say)."""

    NotFound = "not_found"
    """No such file in the caller's org, the caller may not edit it, or it is not in a dataset (rules apply only to
    dataset files)."""


class IngestFileResult(pydantic.BaseModel):
    file_id: str
    outcome: IngestFileOutcome
    rule_id: typing.Optional[str] = None
    """The rule whose trigger ran, or would have."""
    invocation_id: typing.Optional[str] = None
    """The invocation started, when :attr:`outcome` is ``started``."""


class ExistingFilesPreview(pydantic.BaseModel):
    """Files already uploaded that a rule matches, that are not ingested, and whose current upload no rule's trigger
    has run on: ones uploaded, or uploaded again, before the rule existed or while its auto-ingest was off. Editing a
    file's metadata or tags does not make it one of these.

    Response of ``GET /v1/ingestion-rules/<rule_id>/existing-files``.
    """

    count: int
    count_is_lower_bound: bool = False
    """Whether there may be more than :attr:`count`; counting stops after a fixed number of files."""
    sample_paths: list[str] = pydantic.Field(default_factory=list)
    """Up to 10 of the files' paths. Empty for a caller who is not an org admin."""
    complete_session_count: int = 0
    """Complete sessions holding any of these files. After a session's files are ingested, it is announced as fully
    ingested again, and the triggers on ``session.ingested`` start for it."""
