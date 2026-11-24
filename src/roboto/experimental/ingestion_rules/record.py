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
    """Data record of an ingestion rule, as ``GET /v1/ingestion-rules/{rule_id}`` returns it.

    An ingestion rule decides which files in an organization's datasets are ingestable, and which action ingests them.
    ``GET /v1/ingestion-rules``, ``POST /v1/ingestion-rules`` and ``PUT /v1/ingestion-rules/{rule_id}`` also return
    it.

    When a file is created in a dataset, Roboto marks it ingestable if its path matches any of ``include_patterns``
    and none of ``exclude_patterns``; a path with a component starting with a dot never matches. The rule owns one
    trigger, ``trigger_id``, which runs ``invocation`` on each upload of a matching file while ``auto_ingest`` is on.
    """

    rule_id: str
    org_id: str
    name: str
    """Human-readable name of the rule, unique within its organization."""
    description: typing.Optional[str] = None
    include_patterns: list[str]
    """Gitignore-style patterns, such as ``**/*.mcap``, for the files the rule makes ingestable."""
    exclude_patterns: list[str] = pydantic.Field(default_factory=list)
    """Gitignore-style patterns for the files the rule leaves out, even when they match ``include_patterns``."""
    invocation: typing.Optional[ActionInvocationSpec] = None
    """How the rule's trigger invokes an action on each matching upload.

    ``None`` on a rule that does not auto-ingest. The trigger passes the uploaded file as the first input, followed by
    whatever ``invocation.invocation_input`` selects.
    """
    auto_ingest: bool
    """Whether the rule's trigger is enabled, so that Roboto ingests each matching upload as it arrives.

    Turning it off disables the trigger; Roboto still marks matching files ingestable.
    """
    trigger_id: typing.Optional[str] = None
    """ID of the trigger that runs ``invocation`` on matching uploads, or ``None`` while the rule has no invocation.

    Roboto refuses direct edits to the trigger: it changes only when the rule is updated, and deleting the rule deletes
    it.
    """
    created: datetime.datetime
    created_by: str
    """ID of the user who created the rule."""
    modified: datetime.datetime
    modified_by: str
    """ID of the user who last modified the rule."""


class DefaultIngestionRuleRecord(pydantic.BaseModel):
    """Item of the response body of ``GET /v1/ingestion-rules/defaults``: a rule Roboto offers as a starting point.

    Roboto lists only the defaults whose action the caller's organization can invoke, from the Action Hub or among
    its own actions. ``POST /v1/ingestion-rules/defaults`` creates, with ``auto_ingest`` on, each listed default that
    has ``for_new_orgs`` set and is not ``already_present``.
    """

    name: str
    """Human-readable name of the rule, which a rule created from it takes."""
    category: str = "Other"
    """Group the rule is listed under, such as ``ROS`` or ``Tabular``."""
    include_patterns: list[str]
    exclude_patterns: list[str] = pydantic.Field(default_factory=list)
    invocation: ActionInvocationSpec
    already_present: bool
    """Whether the organization has a rule with this name, or a rule with one of these include patterns."""
    for_new_orgs: bool = True
    """Whether sign-up offers this rule and ``POST /v1/ingestion-rules/defaults`` creates it.

    When false, the rule is offered only as a starting point for a new rule.
    """
    needs_settings: bool = False
    """Whether the rule's action likely needs settings for the organization's files before it can ingest them.

    One such setting is which column holds the timestamps.
    """


class IngestFileOutcome(StrEnum):
    """Outcome of asking Roboto to ingest one file with ``POST /v1/ingestion-rules/ingest``."""

    Started = "started"
    """A matching rule's trigger started ingesting the file."""

    AlreadyRunning = "already_running"
    """An ingestion run on the file is still queued or running, so no new one was started."""

    NoMatchingRule = "no_matching_rule"
    """No rule in the file's organization matches its path."""

    AutoIngestOff = "auto_ingest_off"
    """Rules match the file, but none of them auto-ingests."""

    NotStarted = "not_started"
    """The matching rules' triggers ran, but none of them started ingesting the file."""

    NotFound = "not_found"
    """No file has this ID in a dataset of the caller's organization, or the caller cannot edit it.

    Rules apply only to files in datasets.
    """


class IngestFileResult(pydantic.BaseModel):
    """Result of ingesting one file with ``POST /v1/ingestion-rules/ingest``.

    Carried in ``IngestFilesResponse.results``.
    """

    file_id: str
    outcome: IngestFileOutcome
    rule_id: typing.Optional[str] = None
    """ID of the oldest matching rule that auto-ingests, or of the oldest matching rule when none does.

    ``None`` when ``outcome`` is ``NotFound`` or ``NoMatchingRule``.
    """
    invocation_id: typing.Optional[str] = None
    """ID of the invocation that ingests the file, set only when ``outcome`` is ``Started``."""


class ExistingFilesPreview(pydantic.BaseModel):
    """Response body of ``GET /v1/ingestion-rules/{rule_id}/existing-files``.

    Counts the files already in the organization's datasets that the rule matches, that are not ingested, and whose
    current upload no rule's trigger has run on: files uploaded, or uploaded again, before the rule existed or while
    its ``auto_ingest`` was off. Editing a file's metadata or tags does not add it to the count.
    ``POST /v1/ingestion-rules/{rule_id}/existing-files/ingest`` returns it too, and starts ingesting those files in
    the background.
    """

    count: int
    """Number of the files, or a lower bound on it when ``count_is_lower_bound`` is set."""
    count_is_lower_bound: bool = False
    """Whether there may be more files than ``count``, because Roboto stops counting after a fixed number of files."""
    sample_paths: list[str] = pydantic.Field(default_factory=list)
    """Paths of up to 10 of the files.

    Empty unless the caller is an administrator of the organization or a Roboto administrator.
    """
    complete_session_count: int = 0
    """Number of complete sessions that hold any of the files.

    Once their files are ingested, Roboto emits a
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.SessionIngested` platform event for each of these
    sessions, which starts the triggers that subscribe to it.
    """
