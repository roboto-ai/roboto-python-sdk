# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...domain.files import IngestionStatus
from ...pydantic.serializers import field_serializer_custom_field_values
from ..ingestion_runs import IngestionRun

MAX_INACTIVITY_MINUTES = 7 * 24 * 60
"""Longest inactivity a :py:class:`CompletionPolicy` may wait for: one week."""


class CompletionPolicy(pydantic.BaseModel):
    """When Roboto marks a session complete on its own.

    A session's completion policy is set when the session is created and can be changed with an
    update. Roboto marks the session complete once ``inactivity_minutes`` have passed since a file
    was last added to it, or since the policy was changed, whichever is later. A session
    that no file has been added to yet is not completed this way. Adding a file to a session Roboto
    completed puts it back in progress, and Roboto marks it complete again after the same inactivity.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    inactivity_minutes: int = pydantic.Field(ge=1, le=MAX_INACTIVITY_MINUTES)
    """Minutes without a new file after which Roboto marks the session complete."""


class SessionStatus(StrEnum):
    """Whether a session is still receiving files."""

    InProgress = "in_progress"
    """Files may still be added. Roboto does not announce the session ingested."""

    Complete = "complete"
    """All of the session's files have been added. Roboto announces ``session.ingested`` once every
    ingestable file in it is ingested."""


class SessionRecord(pydantic.BaseModel):
    """Wire-format row for a session: an operational time window of a Device such as a drone flight,
    a vehicle drive, or a robot run.

    A Session unifies the recordings and auxiliary data produced during its window;
    it may span many files or cover only a slice of one.

    ``min_timestamp_ns`` and ``max_timestamp_ns`` span every file the Session holds: each file supplies the
    time window stated for it or, without one, the time span of the data the Session takes from it. The
    platform recomputes them in the same write as any change to the Session's files or to the anchors of
    their data, so the row never disagrees with its contents.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    completed_at: typing.Optional[datetime.datetime] = None
    """When the session was last marked complete. ``None`` if it never was. Adding a file to a complete
    session puts it back in progress and keeps this value, so check ``status`` to tell whether the session
    is complete now."""

    completed_by: typing.Optional[str] = None
    """User ID or service account that last marked the session complete. ``None`` if it never was."""

    completes_at: typing.Optional[datetime.datetime] = None
    """When Roboto will mark the session complete unless another file is added first. ``None`` while the
    session is complete, has no completion policy, or has no files."""

    completion_policy: typing.Optional[CompletionPolicy] = None
    """When Roboto marks the session complete on its own. ``None``: the session is marked complete only
    by request."""

    created: typing.Optional[datetime.datetime] = None
    """When the session was created."""

    created_by: str
    """User ID or service account that created the session."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values for the custom fields defined on Sessions in this org.

    Every ``Ready`` custom field defined for ``(org_id, Session)`` appears as a
    key; values that have not been set surface as ``None`` rather than being
    absent. Empty when no custom fields are defined for the org.
    """

    description: typing.Optional[str] = None
    """Optional description of the Session."""

    ingested_at: typing.Optional[datetime.datetime] = None
    """When the session was last announced ingested. ``None`` until the first announcement."""

    ingestion_count: int = 0
    """How many times the session has been announced ingested. Each announcement fires a
    ``session.ingested`` event. A session is announced again when it is put back in progress and marked
    complete again, or when its ingestable files change while it is complete, once they are all ingested
    again. A file uploaded again, removed, or deleted changes them; editing a file's tags, metadata, or
    description does not."""

    max_timestamp_ns: typing.Optional[int] = None
    """Latest time covered by the Session, in Unix-epoch nanoseconds. ``None`` while none of its files
    supplies a time: the Session holds no files, or only files added without a time window whose topic data
    has no time span registered yet."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """User-supplied metadata.

    Sessions cannot be filtered or sorted by ``metadata`` keys;
    for queryable structured attributes, define a custom field on the ``Session`` entity type.
    """

    min_timestamp_ns: typing.Optional[int] = None
    """Earliest time covered by the Session, in Unix-epoch nanoseconds. ``None`` while none of its files
    supplies a time: the Session holds no files, or only files added without a time window whose topic data
    has no time span registered yet."""

    modified: typing.Optional[datetime.datetime] = None
    """When the Session was last modified."""

    modified_by: str
    """User ID or service account that last modified the Session."""

    name: typing.Optional[str] = pydantic.Field(default=None, max_length=120)
    """A short, human-readable name for the Session. If provided, must be 120 characters or less."""

    org_id: str
    """Organization that owns the Session."""

    session_id: str
    """Stable, unique identifier for the Session."""

    status: SessionStatus = SessionStatus.InProgress
    """Whether the session is in progress or complete. Adding a file to a complete session puts it back
    in progress."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """User-supplied tags.

    Sessions can be filtered by tag membership (e.g., ``tags CONTAINS '<tag>'``)
    but are not sortable by tag.
    """

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)


class SessionIngestionState(StrEnum):
    """Where a session's ingestion stands."""

    InProgress = "in_progress"
    """The session is in progress, so it is not announced ingested."""

    Processing = "processing"
    """The session is complete and at least one of its ingestable files is not ingested yet."""

    Ingested = "ingested"
    """The session is complete and every ingestable file in it is ingested."""


class PendingIngestionFile(pydantic.BaseModel):
    """A file in a session that is ingestable and not ingested yet."""

    file_id: str
    """ID of the file."""
    relative_path: str
    """Path of the file within its dataset, device, or org."""
    ingestion_status: IngestionStatus
    """How much of the file's current version is ingested: not at all, or partly."""
    uploaded: typing.Optional[datetime.datetime] = None
    """When the file's current version was uploaded."""
    last_run: typing.Optional[IngestionRun] = None
    """The latest time an ingestion rule's trigger ran on the file. ``None`` when none has."""


class SkippedIngestionFile(pydantic.BaseModel):
    """A file in a session that is ingestable and not ingested, which the session no longer waits for.

    The skip covers the upload of the file that was current when it was made: editing the file's tags,
    metadata, or description keeps it, and uploading the file again ends it."""

    file_id: str
    """ID of the file."""
    relative_path: str
    """Path of the file within its dataset, device, or org."""
    skipped_at: typing.Optional[datetime.datetime] = None
    """When the session was told to stop waiting for the file."""
    skipped_by: typing.Optional[str] = None
    """User ID or service account that told the session to stop waiting for the file."""


class SessionIngestionStatus(pydantic.BaseModel):
    """Where a session stands in ingestion, with the files it is still waiting for.

    Response of ``GET /v1/sessions/id/<session_id>/ingestion``.
    """

    session_id: str
    """ID of the session."""
    state: SessionIngestionState
    """Whether the session is in progress, waiting for files to be ingested, or ingested."""
    ingestion_count: int
    """How many times the session has been announced ingested."""

    pending_files: list[PendingIngestionFile] = pydantic.Field(default_factory=list)
    """Ingestable files not ingested yet, which keep a complete session from being announced. Holds at
    most the first 100, ordered by path; :attr:`pending_file_count` counts them all."""

    pending_file_count: int = 0
    """How many ingestable files are not ingested yet, leaving out skipped ones."""

    failed_file_count: int = 0
    """Pending files whose latest ingestion run failed, or finished without ingesting the file. Counts only the
    files in :attr:`pending_files`, so at most 100."""

    ingested_file_count: int = 0
    """How many ingestable files are ingested."""

    not_ingestable_file_count: int = 0
    """How many files are not ingestable. The session never waits for them."""

    skipped_files: list[SkippedIngestionFile] = pydantic.Field(default_factory=list)
    """Ingestable files not ingested that the session was told to stop waiting for. At most the first 100;
    :attr:`skipped_file_count` counts them all."""

    skipped_file_count: int = 0
    """How many ingestable files not ingested the session was told to stop waiting for."""


class SessionIngestionSummary(pydantic.BaseModel):
    """Where one session's ingestion stands, in counts: what a sessions list shows per row.

    Response item of ``POST /v1/sessions/ingestion/summaries``.
    """

    session_id: str
    """ID of the session."""
    state: SessionIngestionState
    """Whether the session is in progress, waiting for files to be ingested, or ingested."""
    ingested_file_count: int = 0
    """How many ingestable files are ingested."""
    pending_file_count: int = 0
    """How many ingestable files are not ingested yet, leaving out skipped ones."""
    not_ingestable_file_count: int = 0
    """How many files are not ingestable. The session never waits for them."""
    skipped_file_count: int = 0
    """Ingestable files not ingested that the session no longer waits for."""
    failed_file_count: int = 0
    """Pending files whose latest ingestion run failed, or finished without ingesting the file. Counted among the
    first 100 pending files, as :attr:`SessionIngestionStatus.pending_files` lists them."""


class SkipWaitingResponse(pydantic.BaseModel):
    """Response of ``POST /v1/sessions/id/<session_id>/ingestion/skip``."""

    ingestion: SessionIngestionStatus
    """Where the session stands in ingestion after the skip."""
    not_in_session: list[str] = pydantic.Field(default_factory=list)
    """Requested file ids that are not in the session, so nothing was skipped for them."""


class SessionFileRecord(pydantic.BaseModel):
    """Wire-format row for one file a Session holds, and the part of the file it holds.

    Time window contract (``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``):

    1. Set together or both ``None``; a window with only one bound is rejected on write.
    2. When both are ``None``, the Session holds the file's whole recorded time window.
    3. When both are set, ``min_wall_clock_timestamp_ns <= max_wall_clock_timestamp_ns``. Consumers
       iterating session data must keep only the file's data inside the closed interval
       ``[min_wall_clock_timestamp_ns, max_wall_clock_timestamp_ns]``.
    4. Values are nanoseconds since the Unix epoch, measured the same way as the parent Session's own bounds.
       A caller states this window in the file's own timestamps, on
       :py:class:`~roboto.experimental.sessions.SessionFile`; the platform adds the anchor covering the data
       the window names and reports the sum here, alongside the ``unix_epoch_offset_ns`` it added.

    Data range contract (``data_range``):

    1. ``None`` means the Session holds the whole file.
    2. ``(start, end)``: ``start`` is the first covered position; ``end`` is one past the last, with
       ``0 <= start < end``. Values are in the file's own units: stored-row positions (counted from 0), or
       nanoseconds of media time for video.
    3. Used when one file is shared by several sessions; the range names the slice of the file that belongs
       to this session.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When this file was added to the session."""

    created_by: str
    """User ID or service account that added this file to the session."""

    data_range: typing.Optional[tuple[int, int]] = None
    """The slice of the file the Session holds, as ``(start, end)`` in the file's own units, or ``None`` when
    it holds the whole file. ``start`` is the first covered position; ``end`` is one past the last."""

    fs_node_id: str
    """Identifier of the file."""

    max_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Upper bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file up to the end of its recorded time window;
    paired with ``min_wall_clock_timestamp_ns``."""

    min_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Lower bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file from the beginning of its recorded time window;
    paired with ``max_wall_clock_timestamp_ns``."""

    modified: typing.Optional[datetime.datetime] = None
    """When this file's place in the session was last modified."""

    modified_by: str
    """User ID or service account that last modified this file's place in the session."""

    session_id: str
    """Identifier of the session holding this file."""

    unix_epoch_offset_ns: typing.Optional[int] = None
    """Wall-clock instant of stored time 0 for the file's data the Session holds, in nanoseconds since the
    Unix epoch: what the platform added to the file's own timestamps to reach
    ``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``, and what to subtract to read any
    other instant back in the file's own timestamps. ``None`` when that data includes nothing registered,
    and when it sits at more than one instant, which leaves no single offset to report."""


class SessionFileView(pydantic.BaseModel):
    """One row of the ``GET /v1/sessions/id/<session_id>/files`` response: a file's place in a Session joined
    with display fields of the file itself.

    These fields come from the session's composition: ``file_id``, the optional time window
    ``min_wall_clock_timestamp_ns`` / ``max_wall_clock_timestamp_ns`` in Unix-epoch nanoseconds, the optional
    ``data_range`` slice (the window and the slice both under the contracts documented on
    :py:class:`SessionFileRecord`), and the ``unix_epoch_offset_ns`` the platform added to reach that window.
    Every other field is read from the file itself when the files are listed, and describes the file rather
    than its place in the session: ``created`` is when the file was created, not when it joined the session.
    None of those fields is part of a write.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When the file was created."""

    data_range: typing.Optional[tuple[int, int]] = None
    """The slice of the file the Session holds, as ``(start, end)`` in the file's own units, or ``None`` when
    it holds the whole file. ``start`` is the first covered position; ``end`` is one past the last."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset that contains the file."""

    file_id: str
    """Stable, unique identifier of the file."""

    max_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Upper bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file up to the end of its recorded time window;
    paired with ``min_wall_clock_timestamp_ns``."""

    min_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Lower bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file from the beginning of its recorded time window;
    paired with ``max_wall_clock_timestamp_ns``."""

    ingestable: typing.Optional[bool] = None
    """Whether the file is meant to be ingested: its path matched one of its org's ingestion rules when its
    current version was created, or it has since been partly or fully ingested."""

    ingestion_status: typing.Optional[IngestionStatus] = None
    """How much of the contributing file has been ingested."""

    modified: typing.Optional[datetime.datetime] = None
    """When the file was last modified."""

    name: typing.Optional[str] = None
    """Name of the file (the final segment of ``relative_path``)."""

    origination: typing.Optional[str] = None
    """Provenance of the file, e.g. an invocation id or upload source."""

    relative_path: typing.Optional[str] = None
    """Path of the file within its dataset."""

    size: typing.Optional[int] = None
    """Size of the file in bytes."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the file."""

    unix_epoch_offset_ns: typing.Optional[int] = None
    """Wall-clock instant of stored time 0 for the file's data the Session holds, in nanoseconds since the
    Unix epoch: what the platform added to the file's own timestamps to reach
    ``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``, and what to subtract to read any
    other instant back in the file's own timestamps. ``None`` when that data includes nothing registered,
    and when it sits at more than one instant, which leaves no single offset to report."""
