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
from ...domain.topics import TopicIdentityRecord
from ...domain.topics.record import FieldPath
from ...pydantic.serializers import field_serializer_custom_field_values
from ..ingestion_runs import IngestionRun

MAX_INACTIVITY_MINUTES = 7 * 24 * 60
"""Maximum inactivity of a ``CompletionPolicy``, in minutes: 10,080, one week."""


class CompletionPolicy(pydantic.BaseModel):
    """Rule by which Roboto marks a session complete after a period with no new files.

    Carried in ``SessionRecord.completion_policy``. Set it when you create a session, with
    :py:meth:`~roboto.experimental.sessions.Session.create`, or change it with
    :py:meth:`~roboto.experimental.sessions.Session.update`. Building one raises ``pydantic.ValidationError`` when
    ``inactivity_minutes`` is less than 1 or more than 10,080 (``MAX_INACTIVITY_MINUTES``).

    Roboto marks the session complete once ``inactivity_minutes`` have passed since a file was last added to it, or
    since the policy was changed, whichever is later. A session that no file has been added to yet is not completed
    this way. Adding a file to a session Roboto completed puts it back in progress, and Roboto marks it complete again
    after the same inactivity.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    inactivity_minutes: int = pydantic.Field(ge=1, le=MAX_INACTIVITY_MINUTES)
    """Number of minutes without a new file after which Roboto marks the session complete, from 1 to 10,080."""


class SessionStatus(StrEnum):
    """Status of a session: whether more of its files are expected."""

    InProgress = "in_progress"
    """Session that may still gain files. Roboto does not announce an in-progress session ingested."""

    Complete = "complete"
    """Session whose files have all been added, marked complete by request or by its completion policy.

    Roboto announces it ingested, with a ``session.ingested`` platform event, once every ingestable file it waits
    for is ingested.
    """


class SessionRecord(pydantic.BaseModel):
    """Data record of a session, as the Roboto API returns it.

    A session is an operational time window of a device, such as a drone flight, a vehicle drive, or a robot run. It
    groups the recordings and other data produced during that window, and can span many files or hold only part of
    one. :py:class:`~roboto.experimental.sessions.Session` wraps this record with methods that act on the session, and
    exposes it as :py:attr:`~roboto.experimental.sessions.Session.record`. Building a record raises
    ``pydantic.ValidationError`` when ``name`` is longer than 120 characters.

    Roboto announces a complete session ingested, with a ``session.ingested`` platform event, once every
    :py:attr:`~roboto.domain.files.FileRecord.ingestable` file it waits for is ingested. ``ingested_at`` and
    ``ingestion_count`` record those announcements.

    ``min_timestamp_ns`` and ``max_timestamp_ns`` span every file the session holds: each file supplies the time
    window stated for it or, without one, the time span of the data the session takes from it. Roboto recomputes
    them in the same write as any change to the session's files or to the wall-clock anchors of their data, so they
    always match the session's files.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    completed_at: typing.Optional[datetime.datetime] = None
    """Time the session was last marked complete, or ``None`` if it never has been.

    Adding a file to a complete session puts it back in progress and keeps this value, so read ``status`` to tell
    whether the session is complete now.
    """

    completed_by: typing.Optional[str] = None
    """Principal that last marked the session complete, or ``None`` if the session never has been.

    The principal is in the same ``<type>:<id>`` form as ``created_by``, and is Roboto's own system user when Roboto
    made the change.
    """

    completes_at: typing.Optional[datetime.datetime] = None
    """Time Roboto will mark the session complete unless another file is added first.

    ``None`` while the session is complete, has no completion policy, or has no files.
    """

    completion_policy: typing.Optional[CompletionPolicy] = None
    """Rule by which Roboto marks the session complete on its own, or ``None`` if the session has none.

    A session without one is marked complete only by request, with
    :py:meth:`~roboto.experimental.sessions.Session.complete`.
    """

    created: typing.Optional[datetime.datetime] = None
    """Time the session was created."""

    created_by: str
    """Principal that created the session, as ``<type>:<id>``, such as ``user:<user_id>``."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the custom fields the organization defines for sessions, keyed by field name.

    Every session custom field in the :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state appears
    as a key, mapped to ``None`` when the session has no value for it. Fields in any other state are absent, so the
    map is empty when no session custom field is in that state.
    """

    description: typing.Optional[str] = None
    """Human-readable description of the session, or ``None`` if it has none."""

    ingested_at: typing.Optional[datetime.datetime] = None
    """Time Roboto last announced the session ingested, or ``None`` if it never has."""

    ingestion_count: int = 0
    """Number of times Roboto has announced the session ingested.

    Roboto announces a session again when it is put back in progress and marked complete again, or when its
    ingestable files change while it is complete, once they are all ingested again. Uploading a file again, removing
    it, or deleting it changes them; editing a file's tags, metadata, or description does not.
    """

    max_timestamp_ns: typing.Optional[int] = None
    """Latest time covered by the session, in nanoseconds since the Unix epoch.

    ``None`` while none of its files supplies a time: the session holds no files, or only files added without a time
    window whose topic data has no time span registered yet.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the session.

    Sessions cannot be filtered or sorted by metadata keys. To query a structured attribute of sessions, define a
    custom field for sessions instead.
    """

    min_timestamp_ns: typing.Optional[int] = None
    """Earliest time covered by the session, in nanoseconds since the Unix epoch.

    ``None`` while none of its files supplies a time: the session holds no files, or only files added without a time
    window whose topic data has no time span registered yet.
    """

    modified: typing.Optional[datetime.datetime] = None
    """Time the session was last modified."""

    modified_by: str
    """Principal that last modified the session, in the same ``<type>:<id>`` form as ``created_by``.

    It is Roboto's own system user when Roboto made the change.
    """

    name: typing.Optional[str] = pydantic.Field(default=None, max_length=120)
    """Human-readable name of the session, at most 120 characters, or ``None`` if it has none.

    Roboto does not require names to be unique.
    """

    org_id: str
    """ID of the organization that owns the session."""

    session_id: str
    """Unique ID of the session, beginning with ``se_``."""

    status: SessionStatus = SessionStatus.InProgress
    """Status of the session: whether more of its files are expected.

    Adding a file to a complete session puts it back in progress.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the session.

    A RoboQL query can filter sessions by tag, as in ``tags CONTAINS '<tag>'``, but cannot sort them by tag.
    """

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)


class SessionIngestionState(StrEnum):
    """Ingestion state of a session: whether it is in progress, waiting for files to be ingested, or ingested.

    Only files that are :py:attr:`~roboto.domain.files.FileRecord.ingestable`, and that the session was not told to
    stop waiting for, decide the state.
    """

    InProgress = "in_progress"
    """Session in progress, which Roboto does not announce ingested."""

    Processing = "processing"
    """Complete session with at least one file it waits for that is not ingested yet."""

    Ingested = "ingested"
    """Complete session whose files it waits for are all ingested."""


class PendingIngestionFile(pydantic.BaseModel):
    """Ingestable file of a session that is not ingested yet, which the session waits for.

    Carried in ``SessionIngestionStatus.pending_files``.
    """

    file_id: str
    """ID of the file."""
    relative_path: str
    """Path of the file from the root of its dataset's, device's, or organization's files."""
    ingestion_status: IngestionStatus
    """How much of the file's current version is ingested.

    Either none of it (:py:attr:`~roboto.domain.files.IngestionStatus.NotIngested`) or part of it
    (``PartlyIngested``).
    """
    uploaded: typing.Optional[datetime.datetime] = None
    """Time the file's current version was uploaded."""
    last_run: typing.Optional[IngestionRun] = None
    """Latest run of an ingestion rule's trigger on the file's current version, or ``None`` if none has run."""


class SkippedIngestionFile(pydantic.BaseModel):
    """Ingestable file of a session that is not ingested, which the session was told to stop waiting for.

    Carried in ``SessionIngestionStatus.skipped_files``.
    :py:meth:`~roboto.experimental.sessions.Session.skip_waiting_for` stops a session waiting for a file. The skip
    covers the version of the file that was current when it was made: editing the file's tags, metadata, or
    description keeps it, and uploading the file again ends it.
    """

    file_id: str
    """ID of the file."""
    relative_path: str
    """Path of the file from the root of its dataset's, device's, or organization's files."""
    skipped_at: typing.Optional[datetime.datetime] = None
    """Time the session was told to stop waiting for the file."""
    skipped_by: typing.Optional[str] = None
    """Principal that told the session to stop waiting for the file.

    It is written as ``<type>:<id>``, such as ``user:<user_id>``.
    """


class SessionIngestionStatus(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.experimental.sessions.Session.ingestion_status`.

    Ingestion state of a session, with the files it still waits for. Also carried in
    ``SkipWaitingResponse.ingestion``. Files deleted from Roboto are left out of every list and count.
    """

    session_id: str
    """ID of the session."""
    state: SessionIngestionState
    """Ingestion state of the session: whether it is in progress, waiting for files to be ingested, or ingested."""
    ingestion_count: int
    """Number of times Roboto has announced the session ingested."""

    pending_files: list[PendingIngestionFile] = pydantic.Field(default_factory=list)
    """Ingestable files not ingested yet that the session waits for, the first 100 by path.
    ``pending_file_count`` counts them all."""

    pending_file_count: int = 0
    """Number of ingestable files not ingested yet that the session waits for."""

    failed_file_count: int = 0
    """Number of files in ``pending_files`` whose latest ingestion run did not ingest them, so at most 100.

    A run counts when it failed, or finished without ingesting any of the file.
    """

    ingested_file_count: int = 0
    """Number of ingestable files that are ingested."""

    not_ingestable_file_count: int = 0
    """Number of files that are not ingestable, which the session never waits for."""

    skipped_files: list[SkippedIngestionFile] = pydantic.Field(default_factory=list)
    """Ingestable files not ingested that the session was told to stop waiting for, the first 100 by path.
    ``skipped_file_count`` counts them all."""

    skipped_file_count: int = 0
    """Number of ingestable files not ingested that the session was told to stop waiting for."""


class SessionIngestionSummary(pydantic.BaseModel):
    """Ingestion state of one session, in counts.

    :py:meth:`~roboto.experimental.sessions.Session.ingestion_summaries` returns one per session. Unlike
    ``SessionIngestionStatus``, it lists no files. Files deleted from Roboto are left out of every count.
    """

    session_id: str
    """ID of the session."""
    state: SessionIngestionState
    """Ingestion state of the session: whether it is in progress, waiting for files to be ingested, or ingested."""
    ingested_file_count: int = 0
    """Number of ingestable files that are ingested."""
    pending_file_count: int = 0
    """Number of ingestable files not ingested yet that the session waits for."""
    not_ingestable_file_count: int = 0
    """Number of files that are not ingestable, which the session never waits for."""
    skipped_file_count: int = 0
    """Number of ingestable files not ingested that the session was told to stop waiting for."""
    failed_file_count: int = 0
    """Number of files the session waits for whose latest ingestion run did not ingest them.

    A run counts when it failed, or finished without ingesting any of the file. Only the first 100 files by path
    that the session waits for are counted.
    """


class SessionDevice(pydantic.BaseModel):
    """Device attached to a session, with its device type.

    Carried in :py:attr:`~roboto.experimental.sessions.SessionDevicesResponse.devices`.
    """

    device_id: str
    """ID of the device."""
    device_type_id: typing.Optional[str]
    """ID of the device's type, or ``None`` if the device has none."""


class SkipWaitingResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.experimental.sessions.Session.skip_waiting_for`."""

    ingestion: SessionIngestionStatus
    """Ingestion state of the session after the skip."""
    not_in_session: list[str] = pydantic.Field(default_factory=list)
    """IDs of requested files that are not in the session, for which nothing was skipped."""


class SessionFileRecord(pydantic.BaseModel):
    """Data record of one file a session holds, and the part of the file it holds.

    No SDK method or Roboto route uses this model. :py:meth:`~roboto.experimental.sessions.Session.list_files` yields
    ``SessionFileView`` instead, which describes the time window and data range the same way.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """Time the file was added to the session."""

    created_by: str
    """Principal that added the file to the session, as ``<type>:<id>``, such as ``user:<user_id>``."""

    data_range: typing.Optional[tuple[int, int]] = None
    """Part of the file the session holds, or ``None`` when it holds the whole file.

    The part is ``(start, end)`` in the file's own units. ``start`` is the first position held; ``end`` is one past
    the last.
    """

    fs_node_id: str
    """ID of the file."""

    max_wall_clock_timestamp_ns: typing.Optional[int] = None
    """End of the time window of the file the session holds, or ``None`` when it holds the file's whole time span.

    The end is inclusive, in nanoseconds since the Unix epoch.
    """

    min_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Start of the time window of the file the session holds, or ``None`` when it holds the file's whole time span.

    The start is inclusive, in nanoseconds since the Unix epoch.
    """

    modified: typing.Optional[datetime.datetime] = None
    """Time the file's place in the session was last modified."""

    modified_by: str
    """Principal that last modified the file's place in the session.

    It is in the same ``<type>:<id>`` form as ``created_by``.
    """

    session_id: str
    """ID of the session holding the file."""

    unix_epoch_offset_ns: typing.Optional[int] = None
    """Wall-clock time of time 0 of the file's data the session holds, in nanoseconds since the Unix epoch.

    Roboto added it to the file's own timestamps to compute ``min_wall_clock_timestamp_ns`` and
    ``max_wall_clock_timestamp_ns``; subtract it from a wall-clock time to read that time in the file's own
    timestamps. ``None`` when that data has no registered time span, or when its parts have different offsets.
    """


class SessionFileView(pydantic.BaseModel):
    """Data record of a file a session holds, as the Roboto API returns it.

    :py:meth:`~roboto.experimental.sessions.Session.list_files` yields these, and
    :py:meth:`~roboto.experimental.sessions.Session.add_file` and
    :py:meth:`~roboto.experimental.sessions.Session.add_files` return them. ``file_id``, ``data_range``, the time
    window and ``unix_epoch_offset_ns`` describe the part of the file the session holds. Every other field describes
    the file itself: ``created``, for example, is when the file was created, not when it joined the session.

    Time window (``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``):

    - Both are set or both are ``None``. When both are ``None``, the session holds the file's whole time span.
    - When both are set, the window is the closed interval ``[min_wall_clock_timestamp_ns,
      max_wall_clock_timestamp_ns]``, and a read scoped to the session returns only the file's data inside it.
    - Values are nanoseconds since the Unix epoch. You state the window in the file's own timestamps, on
      :py:class:`~roboto.experimental.sessions.SessionFile`, and Roboto reports it here with the data's wall-clock
      anchor added (``unix_epoch_offset_ns``, when the data has one anchor).

    Data range (``data_range``):

    - ``None`` means the session holds the whole file.
    - ``(start, end)`` names the part of a file several sessions share that belongs to this session. ``start`` is
      the first position held and ``end`` is one past the last, with ``0 <= start < end``. Values are in the file's
      own units: stored-row positions counted from 0, or nanoseconds of media time for video.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """Time the file was created."""

    data_range: typing.Optional[tuple[int, int]] = None
    """Part of the file the session holds, or ``None`` when it holds the whole file.

    The part is ``(start, end)`` in the file's own units. ``start`` is the first position held; ``end`` is one past
    the last.
    """

    dataset_id: typing.Optional[str] = None
    """ID of the dataset that contains the file."""

    file_id: str
    """Unique ID of the file, beginning with ``fl_``."""

    max_wall_clock_timestamp_ns: typing.Optional[int] = None
    """End of the time window of the file the session holds, or ``None`` when it holds the file's whole time span.

    The end is inclusive, in nanoseconds since the Unix epoch.
    """

    min_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Start of the time window of the file the session holds, or ``None`` when it holds the file's whole time span.

    The start is inclusive, in nanoseconds since the Unix epoch.
    """

    ingestable: typing.Optional[bool] = None
    """Whether the file is meant to be ingested.

    The meaning is the one :py:attr:`~roboto.domain.files.FileRecord.ingestable` describes.
    """

    ingestion_status: typing.Optional[IngestionStatus] = None
    """How much of the file's data has been ingested into topics."""

    modified: typing.Optional[datetime.datetime] = None
    """Time the file was last modified."""

    name: typing.Optional[str] = None
    """Name of the file, the final component of ``relative_path``."""

    origination: typing.Optional[str] = None
    """Free-form description of what added the file, such as the SDK version or the user that uploaded it."""

    relative_path: typing.Optional[str] = None
    """Path of the file from the root of its dataset's, device's, or organization's files."""

    size: typing.Optional[int] = None
    """Size of the file's content in bytes."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the file."""

    unix_epoch_offset_ns: typing.Optional[int] = None
    """Wall-clock time of time 0 of the file's data the session holds, in nanoseconds since the Unix epoch.

    Roboto added it to the file's own timestamps to compute ``min_wall_clock_timestamp_ns`` and
    ``max_wall_clock_timestamp_ns``; subtract it from a wall-clock time to read that time in the file's own
    timestamps. ``None`` when that data has no registered time span, or when its parts have different offsets.
    """


class SessionTopicSchema(pydantic.BaseModel):
    """Schema that a topic's data in a session is recorded with.

    Carried in ``SessionTopicRecord.schemas``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    checksum: str
    """Checksum of the schema's fields, unique within an organization."""

    name: typing.Optional[str] = None
    """Name of the schema, such as ``"sensor_msgs/msg/Imu"``, or ``None`` if it was recorded without one."""

    schema_id: str
    """Unique ID of the schema."""


class SessionTopicRecord(TopicIdentityRecord):
    """Data record of a topic whose data a session holds, with that data's schemas, time span and counts.

    :py:meth:`~roboto.experimental.sessions.Session.list_topics` yields topics whose ``record`` is this model.
    """

    end_time_ns: typing.Optional[int] = None
    """Latest time of the topic's data in the session, in nanoseconds since the Unix epoch.

    ``None`` when that data carries no timestamps.
    """

    file_count: int = 0
    """Number of the session's files that carry data of the topic."""

    message_count: typing.Optional[int] = None
    """Number of messages of the topic the session holds, from the topic statistics Roboto computes for the session.

    ``None`` until those statistics are computed, when topic statistics are not available in the session's
    organization, and when the count could not be determined.
    """

    schemas: list[SessionTopicSchema] = pydantic.Field(default_factory=list)
    """Schemas the topic's data in the session is recorded with; most topics have one.

    They are listed in the order Roboto first ingested the topic's data under each from the session's files.
    """

    start_time_ns: typing.Optional[int] = None
    """Earliest time of the topic's data in the session, in nanoseconds since the Unix epoch.

    ``None`` when that data carries no timestamps.
    """


class SessionTopicFieldStats(pydantic.BaseModel):
    """Statistics of one field of a topic over a session's data.

    Carried in ``SessionTopicStats.fields``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    path: FieldPath
    """Path of the field in its schema, from the schema root to the leaf.

    For one element of an array field declared with element names, the path is the array's path followed by the
    element's name, such as ``("action", "main_gripper")``.
    """

    stats: dict[str, float] = pydantic.Field(default_factory=dict)
    """Each statistic computed for the field, by name.

    A numeric field has ``count``, ``min``, ``max``, ``mean``, ``median``, ``sum``, ``stddev``, ``p25``, ``p75``,
    ``p95`` and ``p99``; a boolean one has ``count``, ``true_count`` and ``false_count``. A statistic that was not
    computed is absent.
    """


class SessionTopicStats(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.experimental.sessions.Session.get_topic_stats`.

    Statistics of one topic over a session's data, grouped by field.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    fields: list[SessionTopicFieldStats] = pydantic.Field(default_factory=list)
    """One entry per field of the topic that has statistics, ordered by path.

    The elements of a named array are the exception: they follow the array's path in the order its names were
    declared.
    """

    message_count: typing.Optional[int] = None
    """Number of messages of the topic the session holds, or ``None`` when that count was not computed."""

    topic_id: str
    """ID of the topic."""


class SessionTopicStatsRunStatus(StrEnum):
    """Status of a topic statistics run: where the latest run Roboto triggered on a session stands."""

    NotRun = "not_run"
    """No run was triggered for the session.

    For example, the session was never announced ingested, or was announced before Roboto computed topic statistics
    in its organization.
    """

    Scheduled = "scheduled"
    """Roboto has not yet started the run for the session's announcement as ingested in the last five minutes.

    Roboto reports this only while the organization's session-metrics trigger is enabled.
    """

    Running = "running"
    """Roboto is starting the ``session_metrics`` action, or the action is queued or running."""

    Failed = "failed"
    """The action failed or was cancelled, or Roboto could not start it."""

    Finished = "finished"
    """The action finished.

    It can leave some topics without statistics: when the session's topics would have more than 10,000 statistics
    in all, the topics with the most fields are left out until the rest fit.
    """


class SessionTopicStatsRun(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.experimental.sessions.Session.get_topic_stats_run`.

    Latest run of the ``session_metrics`` action that Roboto triggered on a session. Roboto triggers one each time
    the session is announced ingested, but only while the organization's session-metrics trigger (named
    ``roboto-session-metrics``) is installed and enabled. Runs of the action started by hand are not included.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    status: SessionTopicStatsRunStatus
    """Status of the run: where it stands.

    When Roboto triggered no run on the session's latest announcement and none is ``Scheduled``, this describes the
    run on the newest earlier announcement that has one, which computed statistics from the session's files as they
    were then.
    """

    started: typing.Optional[datetime.datetime] = None
    """Time Roboto last tried to start the run, or ``None`` when the run is ``Scheduled`` or ``NotRun``."""

    invocation_id: typing.Optional[str] = None
    """ID of the action invocation the run started, or ``None`` when the run has started none.

    It is ``None`` while Roboto is still starting the run, when no run was triggered, and when Roboto could not
    start one.
    """
