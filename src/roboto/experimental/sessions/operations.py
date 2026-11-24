# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...domain.topics.record import DataRange
from ...int64 import INT64_MAX
from ...sentinels import NotSet, NotSetType
from ...time import _EpochNanosecondsFromTime
from ...updates import CustomFieldChangeset, MetadataChangeset
from ..ingest import (
    MAX_FILES_AND_TOPICS_PER_REQUEST,
    FileTopicDeclaration,
    TopicDeclaration,
)
from ..ingest.operations import (
    _FileWindowBoundNs,
    _reject_files_named_in_different_storage_formats,
)
from .record import CompletionPolicy, SessionDevice, SessionIngestionSummary

MAX_SESSIONS_PER_REQUEST = 100
"""Maximum number of sessions one call to :py:meth:`~roboto.domain.devices.Device.create_sessions` may declare.

Split a larger batch across several calls. ``CreateSessionsRequest`` applies the limit when the request body is built,
and Roboto applies it again when the request arrives, so a body built by hand is held to it too.
"""


class SessionAttributes(pydantic.BaseModel):
    """Descriptive attributes of a session that a request creating the session can set.

    ``CreateSessionRequest`` and ``SessionDeclaration`` take these fields.
    """

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    description: typing.Optional[str] = None
    """Human-readable description of the session."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the session.

    Sessions cannot be filtered or sorted by metadata keys; to query sessions by an attribute, define a custom field for
    sessions.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the session."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Initial values for the session's custom fields, keyed by field name. ``None`` sets none.

    Each name must be a :py:class:`~roboto.domain.custom_fields.CustomField` defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Session` in the organization the session is created in,
    with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
    field's declared type. Otherwise Roboto refuses the session with ``RobotoIllegalArgumentException``.
    """

    completion_policy: typing.Optional[typing.Union[CompletionPolicy, NotSetType]] = NotSet
    """When Roboto marks the session complete on its own.

    Left unset (``NotSet``), the session takes its organization's default completion policy, if the organization has
    one. ``None`` means Roboto marks the session complete only when asked to, by
    :py:meth:`~roboto.experimental.sessions.Session.complete`, whatever the organization's default.
    """


class CreateSessionRequest(SessionAttributes):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.create`.

    Every request creates a new session, with zero or more devices attached. A ``name`` longer than 120 characters
    raises ``pydantic.ValidationError``.
    """

    name: typing.Optional[str] = pydantic.Field(default=None, max_length=120)
    """Human-readable name of the session, at most 120 characters. ``None`` leaves the session unnamed."""

    device_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the devices to attach to the session. Defaults to none."""


class CreateSessionIfNotExistsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.create_if_not_exists`.

    Roboto creates the session only when no session matches a RoboQL query. That method describes how several matches
    and concurrent requests are resolved.
    """

    match_roboql_query: str
    """RoboQL query that looks for an existing session in the organization.

    When sessions match, the response is the first of them and nothing is created.
    """

    create_request: CreateSessionRequest
    """Properties of the session to create when no session matches ``match_roboql_query``."""


class SessionUpdate(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.update`.

    A field left at its default (``NotSet`` or ``None``) is unchanged. A ``name`` longer than 120 characters raises
    ``pydantic.ValidationError``.
    """

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """Human-readable description of the session. ``None`` clears it."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the session's tags and metadata."""

    name: typing.Optional[
        typing.Union[typing.Annotated[str, pydantic.StringConstraints(max_length=120)], NotSetType]
    ] = NotSet
    """Human-readable name of the session, at most 120 characters. ``None`` clears it."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to the session's custom-field values.

    Each field name the changeset references must be a custom field defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Session` in the session's organization, with status
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each ``set_fields`` value must match that
    field's declared type. Otherwise the request fails with ``RobotoIllegalArgumentException``. Fields the changeset
    does not name are unchanged.
    """

    completion_policy: typing.Optional[typing.Union[CompletionPolicy, NotSetType]] = NotSet
    """Completion policy of the session.

    ``None`` removes it, so Roboto marks the session complete only when asked to, by
    :py:meth:`~roboto.experimental.sessions.Session.complete`.

    On a session in progress that has files, setting a policy restarts its inactivity: Roboto marks the session
    complete :py:attr:`~roboto.experimental.sessions.CompletionPolicy.inactivity_minutes` from now, unless a file is
    added first. A complete session stays complete; the policy applies once a file is added to it, which puts it back
    in progress.
    """


class AttachToDeviceRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.attach_to_device`."""

    model_config = pydantic.ConfigDict(extra="ignore")

    device_id: str
    """ID of the device to attach to the session."""


class FileDeclaration(pydantic.BaseModel):
    """Declaration of one uploaded file and the topic data it carries, independent of any session.

    ``SessionFile`` builds on it to state the file's place in a session. Every field here states a fact about the file
    and its recording that holds whichever session, if any, names the file, which is why
    :py:meth:`~roboto.domain.files.File.declare_topics` can state the same facts without naming a session.

    A file can carry data for any number of topics (a LeRobot parquet file usually carries several, as columns of the
    same rows); declare all of them on the file's one declaration.

    Data range (``data_range``):

    * Use one when several sessions share a file and the file's own timestamps cannot tell their parts apart, such as
      a LeRobot v3 data file, whose episodes each restart their timestamp column at 0. When the timestamps can tell
      the parts apart, state each part by time instead, with the time window on ``SessionFile``.
    * ``(start, end)``: ``start`` is the first position covered and ``end`` is one past the last. Positions are in the
      file's own units: stored-row positions counted from 0, or nanoseconds of media time for video.
    * Leaving it unset covers the whole file.
    * Roboto stores each topic's data in a file as one or more partitions, and registers a topic declared over a range
      as a partition over that range. Reading the topic returns only the positions in that range: a topic declared
      over ``(8, 20)`` of a 20-row file reads back 12 rows, not 20.
    * Inside a session, the range also decides which of the file's partitions the session includes; see
      ``SessionFile``.

    Building it raises ``pydantic.ValidationError`` when:

    * ``file_id`` is empty.
    * ``anchor_ns`` does not fall after the Unix epoch, is larger than ``2**63 - 1``, or is a value
      :py:func:`~roboto.time.to_epoch_nanoseconds` refuses.
    * ``topics`` declares one topic twice over the same part of the file.
    * A topic's ``data_range`` reaches outside this declaration's ``data_range``.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="ignore")

    file_id: str = pydantic.Field(min_length=1)
    """ID of the uploaded file this declaration describes."""

    data_range: typing.Optional[DataRange] = None
    """Part of the file this declaration describes, as ``(start, end)``, or ``None`` for the whole file."""

    anchor_ns: typing.Optional[_EpochNanosecondsFromTime] = pydantic.Field(default=None, gt=0, le=INT64_MAX)
    """Wall-clock time at which time 0 of the data this declaration names occurred, in nanoseconds since the Unix epoch.

    The anchor covers exactly what the declaration names: the part of the file ``data_range`` names, or the whole file
    when it names none, so a file holding several parts can give each the instant it happened.

    It must fall after the Unix epoch and be at most ``2**63 - 1`` (:py:const:`~roboto.int64.INT64_MAX`). Any
    :py:const:`~roboto.time.Time` is also accepted, converted as :py:func:`~roboto.time.to_epoch_nanoseconds` converts
    it: an ``int`` is nanoseconds, a ``float``, ``decimal.Decimal``, or numeric string is seconds, and a
    ``datetime.datetime`` or ISO 8601 string is that instant. The field is typed ``int``, so convert with that function
    first to satisfy a type checker.

    ``None`` takes an anchor from elsewhere rather than removing one:

    * Inside a ``SessionDeclaration``, the declaration takes that session's ``anchor_ns`` when one is set, and cannot
      opt out of it.
    * With no anchor at either level, the data keeps the anchor an earlier declaration gave it, or an offset of 0 when
      it has none, so its timestamps read exactly as declared.
    * Nothing is inherited across parts of a file: a part with no anchor of its own never takes another part's
      instant.
    """

    topics: list[TopicDeclaration] = pydantic.Field(default_factory=list)
    """Topics this file carries data for, each over the part of the file that holds it.

    A topic with no :py:attr:`~roboto.experimental.ingest.TopicDeclaration.data_range` of its own covers everything
    this declaration names, and one with a range must stay within this declaration's ``data_range``. A topic and its
    range identify one partition of the file, so each pair appears at most once. Roboto reads a topic's data from the
    files listed in its :py:attr:`~roboto.experimental.ingest.TopicDeclaration.representations`, and from this file
    only when it is listed there.
    """

    @pydantic.model_validator(mode="after")
    def _check_declared_topics(self) -> "FileDeclaration":
        declared_topic_slices: set[tuple[str, typing.Optional[DataRange]]] = set()
        for topic in self.topics:
            topic_slice = (topic.topic_name, topic.data_range)
            if topic_slice in declared_topic_slices:
                raise ValueError(
                    f"topic {topic.topic_name!r} is declared more than once over the same part of the file; "
                    "a topic and the slice it names identify one partition of the file, so declare it at most "
                    "once, with everything that partition carries"
                )
            declared_topic_slices.add(topic_slice)

            # A topic with no range covers whatever this declaration names, and a declaration with no range names
            # the whole file; either way the topic stays inside it.
            if topic.data_range is None or self.data_range is None:
                continue
            if topic.data_range[0] < self.data_range[0] or topic.data_range[1] > self.data_range[1]:
                raise ValueError(
                    f"topic {topic.topic_name!r} declares data range {topic.data_range!r}, which reaches "
                    f"outside the slice {self.data_range!r} this declaration names; a topic of this file "
                    "covers part of the slice the declaration names, never more"
                )
        return self


class SessionFile(FileDeclaration):
    """One uploaded file in a session, with the topic data it carries and the window of that data the session holds.

    It adds the time window to ``FileDeclaration``; everything else it states holds whichever session, if any, names
    the file. The same entry states a file's place in a session however the session is built: inside a
    ``SessionDeclaration`` that creates the session with its files, or passed to
    :py:meth:`~roboto.experimental.sessions.Session.add_files` afterwards. An entry with no topics attaches the file
    without registering topic data; its topics can be declared later, with this entry again or with
    :py:meth:`~roboto.domain.files.File.declare_topics`.

    Topics listed here take their anchor from this entry's ``anchor_ns``, which anchors everything the entry declares.
    State the anchor there, not on a :py:class:`~roboto.experimental.ingest.FileTopicDeclaration`.

    Time window (``min_file_timestamp_ns`` and ``max_file_timestamp_ns``):

    * Values are nanoseconds as the file's own data carries them, measured as a timeline source such as
      :py:class:`~roboto.experimental.ingest.SchemaFieldSource` measures its ``min_file_timestamp_ns``. A part of a
      shared file whose timestamp column restarts at 0 states bounds from 0.
    * Set both or neither. The window is the closed interval ``[min_file_timestamp_ns, max_file_timestamp_ns]``.
    * The window the entry gives the session is the smallest one enclosing these bounds and the bounds of every
      timeline source its topics declare. State the bounds when the file's topics are not declared here, or when the
      session's part of the file runs past the declared topic data. Leave both unset for a window spanning the entry's
      topic data, or, on an entry declaring no topics, the whole file.
    * Roboto adds the anchor covering this entry to the stored window, so re-anchoring the file moves the window with
      its data. The bounds may be negative, but with the anchor added the window must lie between the Unix epoch and
      ``2**63 - 1`` nanoseconds after it (:py:const:`~roboto.int64.INT64_MAX`). Roboto refuses an entry whose window
      would fall outside that span, an entry whose anchor would move another session's window over the same data
      outside it, and a later re-anchoring that would move this window outside it. Roboto reports the window in
      wall-clock time, as :py:attr:`~roboto.experimental.sessions.SessionFileView.min_wall_clock_timestamp_ns` and
      :py:attr:`~roboto.experimental.sessions.SessionFileView.max_wall_clock_timestamp_ns`.
    * Several sessions can share one file, each stating its own window. A session holds the file's data that overlaps
      its window, and the session's own time bounds span the windows of all its files. A read scoped to the session
      covers those bounds unless it names a window of its own.
    * A read scoped to the session returns only the rows of this file inside the window, however wide a window the
      read names, so a session holding part of a shared file reads back that part alone.

    Data range (``data_range``) inside a session:

    * The session includes one of the file's partitions only when every position of the partition lies inside the
      range; a partition reaching past either end is left out whole, never trimmed.
    * Roboto refuses a range that cuts through a partition the file already has, rather than accepting it and
      including nothing of that partition.

    Building it raises ``pydantic.ValidationError`` in the cases ``FileDeclaration`` lists, and when:

    * Only one of ``min_file_timestamp_ns`` and ``max_file_timestamp_ns`` is set, or ``min_file_timestamp_ns`` is
      greater than ``max_file_timestamp_ns``.
    * A bound does not fit in a signed 64-bit integer.
    * A topic is a ``FileTopicDeclaration`` with its own ``anchor_ns``.
    * The input has a ``range_min_timestamp_ns`` or ``range_max_timestamp_ns`` key. Those keys state a window in
      nanoseconds since the Unix epoch; this entry takes its window in the file's own timestamps.
    """

    min_file_timestamp_ns: typing.Optional[_FileWindowBoundNs] = None
    """Inclusive start of the time window, in nanoseconds of the file's own timestamps.

    ``None``, with ``max_file_timestamp_ns`` also ``None``, spans the entry's topic data.
    """

    max_file_timestamp_ns: typing.Optional[_FileWindowBoundNs] = None
    """Inclusive end of the time window, in the same form. ``None`` only together with ``min_file_timestamp_ns``."""

    @pydantic.model_validator(mode="after")
    def _check_window(self) -> "SessionFile":
        if (self.min_file_timestamp_ns is None) != (self.max_file_timestamp_ns is None):
            raise ValueError("min_file_timestamp_ns and max_file_timestamp_ns must be set together or both omitted")
        if (
            self.min_file_timestamp_ns is not None
            and self.max_file_timestamp_ns is not None
            and self.min_file_timestamp_ns > self.max_file_timestamp_ns
        ):
            raise ValueError("min_file_timestamp_ns must be <= max_file_timestamp_ns")
        return self

    @pydantic.model_validator(mode="after")
    def _check_topics_state_no_anchor(self) -> "SessionFile":
        for topic in self.topics:
            # FileTopicDeclaration subclasses TopicDeclaration, so a topic built for File.declare_topics can be
            # passed to a session entry. Serializing this list as TopicDeclaration would drop that topic's anchor
            # without an error.
            if isinstance(topic, FileTopicDeclaration) and topic.anchor_ns is not None:
                raise ValueError(
                    f"topic {topic.topic_name!r} carries an anchor_ns; inside a session entry this entry's "
                    "own anchor_ns anchors everything the entry declares, so state the anchor there"
                )
        return self

    @pydantic.model_validator(mode="before")
    @classmethod
    def _refuse_epoch_window_keys(cls, data: typing.Any) -> typing.Any:
        # These keys state a window in Unix epoch nanoseconds, which this entry does not take. Ignored like other
        # unknown keys, they would attach the file over its whole span with no error.
        if isinstance(data, dict) and ("range_min_timestamp_ns" in data or "range_max_timestamp_ns" in data):
            raise ValueError(
                "range_min_timestamp_ns and range_max_timestamp_ns are not accepted; state the window as "
                "min_file_timestamp_ns and max_file_timestamp_ns instead, in the file's own timestamps rather "
                "than Unix epoch nanoseconds (each epoch bound minus the anchor of the data it names)"
            )
        return data


def _count_files_and_topics(entries: list[SessionFile]) -> int:
    """Count the files and topics the entries declare, which ``MAX_FILES_AND_TOPICS_PER_REQUEST`` bounds."""
    return len(entries) + sum(len(entry.topics) for entry in entries)


def _reject_repeated_file_ids(entries: list[SessionFile]) -> None:
    """Reject entries that name the same file twice, which would contradict each other about what it carries.

    Args:
        entries: Entries to check.

    Raises:
        ValueError: Two entries name the same file.
    """
    seen: set[str] = set()
    for entry in entries:
        if entry.file_id in seen:
            raise ValueError(
                f"file {entry.file_id!r} appears in more than one entry; "
                "declare each file once, listing all of its topics on that entry"
            )
        seen.add(entry.file_id)


class AddFilesRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.add_files`.

    Building it raises ``pydantic.ValidationError`` when:

    * ``files`` is empty, or its entries and their topics number more than 500 together
      (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`).
    * Two entries name the same file.
    * Representations name one file in two storage formats.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    files: list[SessionFile] = pydantic.Field(min_length=1, max_length=MAX_FILES_AND_TOPICS_PER_REQUEST)
    """Files to add to the session, each appearing once and listing all of its topics."""

    @pydantic.model_validator(mode="after")
    def _validate_declared_files(self) -> "AddFilesRequest":
        declared = _count_files_and_topics(self.files)
        if declared > MAX_FILES_AND_TOPICS_PER_REQUEST:
            raise ValueError(
                f"the request declares {declared} files and topics; at most "
                f"{MAX_FILES_AND_TOPICS_PER_REQUEST} are accepted per request, so split the files across "
                "several calls"
            )
        _reject_repeated_file_ids(self.files)
        _reject_files_named_in_different_storage_formats(
            representation for entry in self.files for topic in entry.topics for representation in topic.representations
        )
        return self


class DetachFromDeviceRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.detach_from_device`."""

    model_config = pydantic.ConfigDict(extra="ignore")

    device_id: str
    """ID of the device to detach from the session."""


class SkipWaitingRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.skip_waiting_for`.

    Building it raises ``pydantic.ValidationError`` when ``file_ids`` is empty or names more than 1,000 files.
    """

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=1000)
    """IDs of the session's files to stop waiting for.

    A file not in the session is listed in :py:attr:`~roboto.experimental.sessions.SkipWaitingResponse.not_in_session`
    and nothing is skipped for it.
    """


class RemoveFilesRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.remove_files`.

    Building it raises ``pydantic.ValidationError`` when ``file_ids`` is empty, names more than 500 files
    (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`), or names a file more than once.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_FILES_AND_TOPICS_PER_REQUEST)
    """IDs of the files to remove from the session, each named once."""

    @pydantic.model_validator(mode="after")
    def _validate_unique_file_ids(self) -> "RemoveFilesRequest":
        seen: set[str] = set()
        for file_id in self.file_ids:
            if file_id in seen:
                raise ValueError(f"file {file_id!r} is named more than once; name each file at most once")
            seen.add(file_id)
        return self


class SetUnixOffsetRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset`.

    That method describes which data the anchor reaches and how it replaces anchors already on the data. Building it
    raises ``pydantic.ValidationError`` when ``unix_epoch_offset_ns`` does not fall after the Unix epoch, is larger
    than ``2**63 - 1``, or is a value :py:func:`~roboto.time.to_epoch_nanoseconds` refuses.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    unix_epoch_offset_ns: _EpochNanosecondsFromTime
    """Wall-clock time of stored time 0, in nanoseconds since the Unix epoch.

    Any :py:const:`~roboto.time.Time` is also accepted, converted as :py:func:`~roboto.time.to_epoch_nanoseconds`
    converts it: an ``int`` is nanoseconds, a ``float``, ``decimal.Decimal``, or numeric string is seconds, and a
    ``datetime.datetime`` or ISO 8601 string is that instant. The field is typed ``int``, so convert with that function
    first to satisfy a type checker.
    """

    @pydantic.field_validator("unix_epoch_offset_ns")
    @classmethod
    def _check_offset(cls, value: int) -> int:
        if value == 0:
            raise ValueError(
                "unix_epoch_offset_ns must be positive; to return a session to an offset of 0, "
                "clear its anchor instead (DELETE /v1/sessions/id/<session_id>/unix-offset)"
            )
        if not 0 < value <= INT64_MAX:
            raise ValueError("unix_epoch_offset_ns must be a time after the Unix epoch and below 2**63 ns")
        return value


class SessionDeclaration(SessionAttributes):
    """Declaration of one session to create on a device, with the files that make it up.

    Pass a list of them to :py:meth:`~roboto.domain.devices.Device.create_sessions`;
    :py:meth:`~roboto.domain.devices.Device.create_session` builds one from its arguments.

    Building it raises ``pydantic.ValidationError`` when:

    * ``name`` is empty or longer than 120 characters.
    * ``anchor_ns`` does not fall after the Unix epoch, is larger than ``2**63 - 1``, or is a value
      :py:func:`~roboto.time.to_epoch_nanoseconds` refuses.
    * Two entries in ``files`` name the same file.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: str = pydantic.Field(min_length=1, max_length=120)
    """Human-readable name of the session, from 1 to 120 characters, unique within the device.

    The name identifies the session the declaration creates or reuses, so resending a batch reuses the session already
    under this name instead of creating a second one.
    """

    anchor_ns: typing.Optional[_EpochNanosecondsFromTime] = pydantic.Field(default=None, gt=0, le=INT64_MAX)
    """Wall-clock time at which time 0 of the session's data occurred, for every entry that states no anchor of its own.

    Each such entry then anchors the data it declares, which is its part of the file when it names one. It takes the
    same values as ``FileDeclaration.anchor_ns``, which says which values it accepts, what an anchor covers, and what an
    entry's data does when neither level states one. ``None`` leaves each entry to its own ``anchor_ns``.
    """

    files: list[SessionFile] = pydantic.Field(default_factory=list)
    """Files that make up the session, with the topics each carries data for. Defaults to none.

    Each file appears once, listing all of its topics.
    """

    @pydantic.model_validator(mode="after")
    def _validate_declared_files(self) -> "SessionDeclaration":
        _reject_repeated_file_ids(self.files)
        return self


class CreateSessionsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.devices.Device.create_sessions`.

    That method describes what a declaration writes, what a refused one leaves behind, and what resending the same batch
    does.

    Building it raises ``pydantic.ValidationError`` when:

    * ``sessions`` is empty or holds more than 100 declarations (``MAX_SESSIONS_PER_REQUEST``).
    * The declarations name more than 500 files and topics together
      (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`).
    * Two declarations have the same ``name``.
    * Representations name one file in two storage formats.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    sessions: list[SessionDeclaration] = pydantic.Field(min_length=1, max_length=MAX_SESSIONS_PER_REQUEST)
    """Sessions to create, one declaration each."""

    @pydantic.model_validator(mode="after")
    def _validate_declared_sessions(self) -> "CreateSessionsRequest":
        declared = sum(_count_files_and_topics(declaration.files) for declaration in self.sessions)
        if declared > MAX_FILES_AND_TOPICS_PER_REQUEST:
            raise ValueError(
                f"the request declares {declared} files and topics across its sessions; at most "
                f"{MAX_FILES_AND_TOPICS_PER_REQUEST} are accepted per request, so split the sessions across "
                "several calls"
            )
        seen: set[str] = set()
        for declaration in self.sessions:
            if declaration.name in seen:
                raise ValueError(
                    f"session {declaration.name!r} is declared more than once in this batch; "
                    "within one device, the declared name identifies the session a declaration "
                    "creates or reuses, so each batch must declare a name at most once"
                )
            seen.add(declaration.name)
        _reject_files_named_in_different_storage_formats(
            representation
            for declaration in self.sessions
            for entry in declaration.files
            for topic in entry.topics
            for representation in topic.representations
        )
        return self


MAX_INGESTION_SUMMARIES = 100
"""Maximum number of sessions one request to ``POST /v1/sessions/ingestion/summaries`` may name.

:py:meth:`~roboto.experimental.sessions.Session.ingestion_summaries` splits a longer list across several requests.
"""


class SessionIngestionSummariesRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.experimental.sessions.Session.ingestion_summaries`.

    Building it raises ``pydantic.ValidationError`` when ``session_ids`` is empty or names more than 100 sessions
    (``MAX_INGESTION_SUMMARIES``).
    """

    session_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_INGESTION_SUMMARIES)
    """IDs of the sessions to summarize."""


class SessionIngestionSummariesResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.experimental.sessions.Session.ingestion_summaries`."""

    summaries: list[SessionIngestionSummary]
    """One summary per requested session, in request order.

    Sessions outside the organization the caller acts in are left out.
    """


MAX_SESSION_DEVICES_REQUEST = 100
"""Maximum number of sessions one request to ``POST /v1/sessions/devices`` may name."""


class SessionDevicesRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/sessions/devices``.

    Building it raises ``pydantic.ValidationError`` when ``session_ids`` is empty or names more than 100 sessions
    (``MAX_SESSION_DEVICES_REQUEST``).
    """

    session_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_SESSION_DEVICES_REQUEST)
    """IDs of the sessions whose devices to list."""


class SessionDevicesResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/sessions/devices``."""

    devices: dict[str, list[SessionDevice]]
    """Devices attached to each requested session, sorted by device ID and keyed by session ID.

    A session with no devices, or outside the organization the caller acts in, has no key.
    """
