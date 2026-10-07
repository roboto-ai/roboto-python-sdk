# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Request bodies for the session endpoints, and what a caller declares about sessions in them.

What the platform reports back is in :py:mod:`roboto.experimental.sessions.record`, and the types describing
a file's contents, independent of any session, live in :py:mod:`roboto.experimental.ingest`.
"""

import typing

import pydantic

from ...domain.topics.record import (
    _INT64_MAX,
    _INT64_MIN,
    DataRange,
)
from ...sentinels import NotSet, NotSetType
from ...time import _EpochNanosecondsFromTime
from ...updates import CustomFieldChangeset, MetadataChangeset
from ..ingest import (
    MAX_FILES_AND_TOPICS_PER_REQUEST,
    FileTopicDeclaration,
    TopicDeclaration,
)
from ..ingest.operations import _reject_files_named_in_different_storage_formats

MAX_SESSIONS_PER_REQUEST = 100
"""Cap on the number of sessions one request may declare on a device; split a larger batch across several
calls.

:py:class:`CreateSessionsRequest` applies the cap when the request body is constructed, and the platform
applies it again on arrival, so a body built by hand cannot exceed it either.
"""


class SessionAttributes(pydantic.BaseModel):
    """Descriptive attributes a caller can set on a session, whichever call creates it."""

    model_config = pydantic.ConfigDict(extra="ignore")

    description: typing.Optional[str] = None
    """Optional description of the Session."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to associate with the Session.

    Sessions cannot be filtered or sorted by ``metadata`` keys;
    for queryable structured attributes, define a custom field on the ``Session`` entity type.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to associate with the Session."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Initial values for Ready custom fields on this session.

    Each key must be the name of a :py:class:`~roboto.domain.custom_fields.CustomField`
    that is :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` for the
    caller's org and the :py:class:`~roboto.domain.custom_fields.TargetEntityType.Session`
    entity type; each value must satisfy the field's declared type. Names that are
    undefined or not ``Ready``, and values that don't match the field's type, are
    rejected with a structured error.
    """


class CreateSessionRequest(SessionAttributes):
    """Request body for ``POST /v1/sessions``.

    Creates a new session with zero, one, or many devices attached as subjects.
    """

    name: typing.Optional[str] = pydantic.Field(default=None, max_length=120)
    """Optional short name for the Session (max 120 characters)."""

    device_ids: list[str] = pydantic.Field(default_factory=list)
    """Devices to attach to the Session as subjects; empty creates a Session with no devices."""


class SessionUpdate(pydantic.BaseModel):
    """Partial update for a session.

    Fields left at ``NotSet`` are not modified.
    """

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New description for the Session. Set to ``None`` to clear the description."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Tag and metadata changes to merge into the Session (add, update, or remove fields and tags)."""

    name: typing.Optional[
        typing.Union[typing.Annotated[str, pydantic.StringConstraints(max_length=120)], NotSetType]
    ] = NotSet
    """New name for the Session (max 120 characters). Set to ``None`` to clear the name."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to apply to Ready custom-field values on this session.

    Each referenced field name must be a
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` custom field
    for this session's org and the
    :py:class:`~roboto.domain.custom_fields.TargetEntityType.Session` entity type;
    each ``set_fields`` value must satisfy the field's declared type. Names that
    are undefined or not ``Ready`` are rejected with a structured error. Field
    names not mentioned by the changeset are left unchanged.
    """


class AttachToDeviceRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/sessions/id/<session_id>/devices``.

    Attaches a device as a subject of the session.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    device_id: str


class FileDeclaration(pydantic.BaseModel):
    """One already-uploaded file and the topic data it carries.

    Everything here is true of the file and its recording whether or not any session ever names it, which is
    why :py:meth:`~roboto.domain.files.File.declare_topics` can state the same facts without naming a
    session. :py:class:`SessionFile` adds the one fact only a session can state: the window of the file's
    data that session holds.

    A file may contribute to any number of topics (a LeRobot parquet file typically carries several as
    columns of the same rows); declare them all on the one declaration for that file.

    Data range (``data_range``):

    * Use when one file is shared by several sessions and its own timestamps cannot tell the shared parts
      apart (for example, a LeRobot v3 data file, whose episodes each restart their timestamp column at 0).
      When they can tell them apart, name the slice by time instead, with the time window on
      :py:class:`SessionFile`.
    * ``(start, end)``: ``start`` is the first covered position; ``end`` is one past the last. Values are in
      the file's own units: stored-row positions (counted from 0), or nanoseconds of
      media time for video.
    * Leaving it unset covers the whole file.
    * Each topic's data in a file is stored as one or more partitions, and a topic declared over a range is
      registered as a partition over that range. Reading it returns only the positions in that range: a
      topic declared over ``(8, 20)`` of a 20-row file reads back 12 rows, not the file's 20.
    * Inside a session the range also decides which of the file's partitions the session admits; see
      :py:class:`SessionFile`.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="ignore")

    file_id: str = pydantic.Field(min_length=1)
    """Identifier of the already-uploaded file this declaration describes."""

    data_range: typing.Optional[DataRange] = None
    """The slice of the file this declaration describes, or ``None`` for the whole file."""

    anchor_ns: typing.Optional[_EpochNanosecondsFromTime] = pydantic.Field(default=None, gt=0, le=_INT64_MAX)
    """Optional wall-clock anchor for the data this declaration names: the real-world time, in nanoseconds
    since the Unix epoch, at which that data's time 0 occurred. It covers exactly what the declaration names,
    the slice named by :py:attr:`data_range` or the whole file when none is named, so a file holding several
    slices can give each of them the instant it happened. Must fall after the Unix epoch, and be small enough
    to fit in the signed 64-bit integer the platform stores it in. Also accepts any
    :py:data:`roboto.time.Time` at runtime, converted as :py:func:`roboto.time.to_epoch_nanoseconds` converts
    it: an ``int`` is nanoseconds, a ``float``, ``Decimal``, or numeric string is seconds, and a ``datetime``
    or ISO 8601 string is that instant. The field is typed ``int``, so convert with that function first to
    satisfy a type checker. When omitted on a declaration inside a
    :py:class:`SessionDeclaration`, the declaration takes that session's
    :py:attr:`~SessionDeclaration.anchor_ns` if one is set: ``None`` means "inherit", not "no anchor", so a
    declaration cannot opt out of a session-level anchor. With no anchor from either level, the data this
    declaration names keeps the anchor it already carries from an earlier declaration, and keeps an offset of
    0 when it carries none: its timestamps read exactly as declared. Nothing is inherited across slices: a
    slice with no anchor of its own never takes on a neighbor's instant, however the file's other slices are
    anchored."""

    topics: list[TopicDeclaration] = pydantic.Field(default_factory=list)
    """Topics this file contributes data to, each over the part of the file that carries it. Every topic
    sits inside the slice this declaration names: one declaring no
    :py:attr:`~roboto.experimental.ingest.TopicDeclaration.data_range` of its own covers all of it, and one
    declaring a range must sit within it. A topic and the slice it names identify one partition of the file,
    so each is declared at most once here. A topic's data is read from the files the topic lists in
    :py:attr:`~roboto.experimental.ingest.TopicDeclaration.representations`, and from this file only when the
    topic lists it there."""

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

            # A topic naming no range of its own covers whatever this declaration names, and a declaration
            # naming no slice names the whole file; either way the topic cannot reach outside it.
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
    """One already-uploaded file that belongs to a session, and the topic data it carries.

    Adds to :py:class:`FileDeclaration` the window of the file's data this session holds. Everything else
    the entry states is true of the file whichever session, if any, names it.

    The same entry states a file's place in a session however that session is composed: inside a
    :py:class:`SessionDeclaration` that creates the session whole, or handed to
    :py:meth:`~roboto.experimental.sessions.Session.add_files` afterwards. An entry with no topics attaches
    the file without registering topic data; topics can be declared for the same file later, through this
    entry again or through :py:meth:`~roboto.domain.files.File.declare_topics`.

    A topic listed here takes its anchor from this entry's :py:attr:`~FileDeclaration.anchor_ns`, which
    anchors everything the entry declares. A :py:class:`~roboto.experimental.ingest.FileTopicDeclaration`
    carrying an ``anchor_ns`` of its own is rejected here; state that anchor on the entry instead.

    Time window (``min_file_timestamp_ns`` and ``max_file_timestamp_ns``):

    * Values are nanoseconds as the file's own data carries them, measured the same way as the
      ``min_file_timestamp_ns`` a timeline source such as
      :py:class:`~roboto.experimental.ingest.SchemaFieldSource` declares. A slice of a shared file whose
      timestamp column restarts at 0 states bounds from 0.
    * Set both or set neither; a window with only one bound is rejected. The window is the closed interval
      ``[min_file_timestamp_ns, max_file_timestamp_ns]``, both endpoints included.
    * The window this entry gives the session is the smallest one enclosing these bounds and the bounds of
      every timeline source its topics declare. State them when the file's topics are not declared here, or
      when what belongs to the session runs past the declared topic data. Leave both unset for a window
      spanning whatever the entry's topic data spans, or, on an entry declaring no topics, the file's whole
      window.
    * The anchor covering this entry is added to the stored window, so re-anchoring the file moves the window
      along with the data it names. The bounds may be negative, but with the anchor added the window must lie
      between the Unix epoch and the largest storable Unix-epoch nanosecond value (``2**63 - 1``). The platform
      refuses an entry whose window would fall outside that span, an entry whose anchor would move a window
      another session declared over the same data outside it, and a later re-anchoring that would move this
      window outside it. The platform reports the window back in wall clock, on
      :py:attr:`~roboto.experimental.sessions.SessionFileView.min_wall_clock_timestamp_ns` and
      :py:attr:`~roboto.experimental.sessions.SessionFileView.max_wall_clock_timestamp_ns`.
    * Several sessions can share one file, each stating its own window. A session takes on the file's data
      that overlaps its window, and its own time bounds span the windows of all the files it holds; a read
      scoped to the session covers those bounds unless it names a window of its own.
    * The window this entry gives the session also trims a read of this file. A read scoped to this
      session returns only the rows of the file inside that window, however wide a window the read itself
      names, so a session holding part of a shared file reads back that part and not the whole file.

    Data range (``data_range``) inside a session:

    * The range decides which of the file's partitions this session admits. It admits a partition only
      when every one of its positions sits inside it; a partition reaching past either end is left out
      whole, never trimmed.
    * A range that cuts through a partition the file has already registered is refused by the platform
      rather than accepted to admit nothing of that partition.
    """

    min_file_timestamp_ns: typing.Optional[int] = pydantic.Field(default=None, ge=_INT64_MIN, le=_INT64_MAX)
    """Lower bound of the time window this entry states, in the file's own timestamps."""

    max_file_timestamp_ns: typing.Optional[int] = pydantic.Field(default=None, ge=_INT64_MIN, le=_INT64_MAX)
    """Upper bound of the time window this entry states, in the file's own timestamps."""

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
            # FileTopicDeclaration subclasses TopicDeclaration, so a topic built for File.declare_topics
            # can be handed to a session entry. Serializing this list under its declared TopicDeclaration
            # type would drop the anchor that topic carries, silently ignoring what the caller asked for.
            if isinstance(topic, FileTopicDeclaration) and topic.anchor_ns is not None:
                raise ValueError(
                    f"topic {topic.topic_name!r} carries an anchor_ns; inside a session entry this entry's "
                    "own anchor_ns anchors everything the entry declares, so state the anchor there"
                )
        return self

    @pydantic.model_validator(mode="before")
    @classmethod
    def _refuse_epoch_window_keys(cls, data: typing.Any) -> typing.Any:
        # These keys state a window in Unix epoch nanoseconds, which this entry does not take. Ignored like
        # other unknown keys, they would attach the file over its whole span with no error.
        if isinstance(data, dict) and ("range_min_timestamp_ns" in data or "range_max_timestamp_ns" in data):
            raise ValueError(
                "range_min_timestamp_ns and range_max_timestamp_ns are not accepted; state the window as "
                "min_file_timestamp_ns and max_file_timestamp_ns instead, in the file's own timestamps rather "
                "than Unix epoch nanoseconds (each epoch bound minus the anchor of the data it names)"
            )
        return data


def _count_files_and_topics(entries: list[SessionFile]) -> int:
    """How many files and topics a set of entries declares, which is what the per-request cap bounds."""
    return len(entries) + sum(len(entry.topics) for entry in entries)


def _reject_repeated_file_ids(entries: list[SessionFile]) -> None:
    """Raise when two entries name the same file, which would contradict each other about what it carries.

    Args:
        entries: The entries to check, in the order the caller stated them.

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
    """Request body for ``POST /v1/sessions/id/<session_id>/files``.

    Adds one or more files to the session, each with whatever topic data it carries, and reports what became of
    each entry. The platform decides every refusal before writing anything, so an entry it refuses leaves the
    others added, and a failure it did not anticipate adds none of them.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    files: list[SessionFile] = pydantic.Field(min_length=1, max_length=MAX_FILES_AND_TOPICS_PER_REQUEST)
    """Files to include, each appearing exactly once and listing all of its topics. The entries and the
    topics on them count together toward ``MAX_FILES_AND_TOPICS_PER_REQUEST``."""

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
    """Request body for ``DELETE /v1/sessions/id/<session_id>/devices``.

    Detaches a device from the session; the session itself is not deleted.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    device_id: str


class RemoveFilesRequest(pydantic.BaseModel):
    """Request body for ``DELETE /v1/sessions/id/<session_id>/files``.

    Removes the listed files from the session and reports what became of each: a file the session does not
    hold is reported as its own entry rather than failing the call, and a failure the platform did not
    anticipate removes none of them.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    file_ids: list[str] = pydantic.Field(min_length=1, max_length=MAX_FILES_AND_TOPICS_PER_REQUEST)
    """Files to remove, each named at most once."""

    @pydantic.model_validator(mode="after")
    def _validate_unique_file_ids(self) -> "RemoveFilesRequest":
        seen: set[str] = set()
        for file_id in self.file_ids:
            if file_id in seen:
                raise ValueError(f"file {file_id!r} is named more than once; name each file at most once")
            seen.add(file_id)
        return self


class SetUnixOffsetRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/sessions/id/<session_id>/unix-offset``.

    Anchors the session's data to wall-clock time. See
    :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset` for the write's reach and its
    interaction with anchors already on the data.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    unix_epoch_offset_ns: _EpochNanosecondsFromTime
    """Wall-clock instant of stored time 0, in nanoseconds since the Unix epoch.
    Must fall after the Unix epoch, and must fit in the signed 64-bit integer the platform stores it in.
    Also accepts any :py:data:`roboto.time.Time` at runtime, converted as
    :py:func:`roboto.time.to_epoch_nanoseconds` converts it: an ``int`` is nanoseconds, a ``float``,
    ``Decimal``, or numeric string is seconds, and a ``datetime`` or ISO 8601 string is that instant. The
    field is typed ``int``, so convert with that function first to satisfy a type checker."""

    @pydantic.field_validator("unix_epoch_offset_ns")
    @classmethod
    def _check_offset(cls, value: int) -> int:
        if value == 0:
            raise ValueError(
                "unix_epoch_offset_ns must be positive; to return a session to an offset of 0, "
                "clear its anchor instead (DELETE /v1/sessions/id/<session_id>/unix-offset)"
            )
        if not 0 < value <= _INT64_MAX:
            raise ValueError("unix_epoch_offset_ns must be a time after the Unix epoch and below 2**63 ns")
        return value


class SessionDeclaration(SessionAttributes):
    """One session to create on a device, with the files composing it.

    Handed, one per session, to :py:meth:`~roboto.domain.devices.Device.create_sessions`.
    :py:meth:`~roboto.domain.devices.Device.create_session` builds one from its arguments for the
    single-session case.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: str = pydantic.Field(min_length=1, max_length=120)
    """Name of the session (max 120 characters), unique within the device: retrying a batch converges on the
    existing session with this name instead of creating a duplicate."""

    anchor_ns: typing.Optional[_EpochNanosecondsFromTime] = pydantic.Field(default=None, gt=0, le=_INT64_MAX)
    """Optional wall-clock anchor applied to every entry in this session that does not carry its own
    :py:attr:`FileDeclaration.anchor_ns`; each such entry then anchors the data it declares, which is its
    slice of the file when it names one. Takes the same values as :py:attr:`FileDeclaration.anchor_ns`, which
    states the range and the forms it accepts, what an anchor covers, and what an entry's data does when
    neither level states one."""

    files: list[SessionFile] = pydantic.Field(default_factory=list)
    """Files (and the topics they contribute to) composing this session. Each file appears exactly once,
    listing all of its topics."""

    @pydantic.model_validator(mode="after")
    def _validate_declared_files(self) -> "SessionDeclaration":
        _reject_repeated_file_ids(self.files)
        return self


class CreateSessionsRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/devices/id/<device_id>/sessions``.

    Creates up to ``MAX_SESSIONS_PER_REQUEST`` sessions on one device, each with its files, topics, and
    schemas, in a single call; the platform additionally rejects batches declaring more than
    ``MAX_FILES_AND_TOPICS_PER_REQUEST`` files and topics combined, counted across all sessions.

    A malformed batch is rejected whole, before anything is written. Past that point the platform decides
    every declaration's refusal before writing anything, writes the others together, and answers with one
    element per declaration, in the order they were declared; see
    :py:meth:`~roboto.domain.devices.Device.create_sessions` for what a declaration writes, what a refused one
    leaves behind, and what a resend of the same batch does.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    sessions: list[SessionDeclaration] = pydantic.Field(min_length=1, max_length=MAX_SESSIONS_PER_REQUEST)
    """Sessions to create, between 1 and ``MAX_SESSIONS_PER_REQUEST`` per request."""

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
