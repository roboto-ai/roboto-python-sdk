# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

import pydantic

from ...domain.topics.record import (
    _INT64_MAX,
    _INT64_MIN,
    CanonicalDataType,
    DataRange,
    RepresentationStorageFormat,
    TimelineSourceKind,
)
from ...sentinels import NotSet, NotSetType, is_set
from ...time import _EpochNanosecondsFromTime
from .schema import Schema

MAX_FILES_AND_TOPICS_PER_REQUEST = 500
"""Cap on how many files and topics one request may name, counting each file entry and each topic
declaration in it.

Each file and topic named costs the platform another round of writes, and a request has a fixed amount of
time to finish them all, so a request naming more than this is refused outright rather than left to run out
of time; split a larger batch across several calls. The request models below and in
:py:mod:`roboto.experimental.sessions` apply the cap when the request body is constructed, and the platform
checks it again on every call that declares files or topics, so a body built without these models is held to
the same cap.
"""

MESSAGE_ENVELOPE_TIMELINE_SOURCES: dict[str, tuple[TimelineSourceKind, str]] = {
    "mcap_log_time": ("message_log_time", "message_log_time"),
    "mcap_publish_time": ("message_publish_time", "message_publish_time"),
    "mp4_presentation_time": ("message_log_time", "presentation_time"),
}
"""Stored kind and stored name of each timeline source a container stamps on its records, keyed by declared ``kind``.

These sources sit in the message envelope rather than in the topic's data columns. The stored kind says which of the
envelope's two timestamps a source is, log time or publish time, and reads select a source by its stored name.

MCAP log time and MP4 presentation time each name the timeline their container stamps on every record it
holds: for MCAP, the instant the recorder wrote the record; for MP4, the instant the frame is shown. The
platform stores one such timeline per topic schema, so the two share a stored kind, differ only in the
name a read selects them by, and cannot both be declared on one topic.

The request models in this module check each declaration against the kind and name in this table, and the
platform stores the declaration under exactly those.
"""

_COLUMN_TIME_SOURCE_KIND = "field"
"""``kind`` of the one declared timeline source whose timestamps sit in the topic's own data columns.

Every other declared kind is a key of :py:data:`MESSAGE_ENVELOPE_TIMELINE_SOURCES`.
"""


class _DeclaredSourceBase(pydantic.BaseModel):
    """Fields every kind of declared timeline source carries.

    Every subclass declares a literal-typed ``kind`` discriminator defaulting to its own value, which is what
    the platform routes the entry by; a subclass that omits it raises ``TypeError`` at import.

    That ``kind`` also says where the timestamps sit: in the topic's own data columns
    (:py:data:`_COLUMN_TIME_SOURCE_KIND`) or in the message envelope (a key of
    :py:data:`MESSAGE_ENVELOPE_TIMELINE_SOURCES`). Every check on a declared source reads its ``kind`` to tell those
    two apart, so a subclass whose ``kind`` is neither raises ``TypeError`` at import.
    """

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    min_file_timestamp_ns: int = pydantic.Field(ge=_INT64_MIN, le=_INT64_MAX)
    """Time of the first message this file contributes on this timeline source, in nanoseconds, as the data
    itself carries it, stored in a signed 64-bit integer. A slice of a shared file states the bounds its own
    data carries: a LeRobot episode whose timestamp column restarts at 0 declares bounds from 0, while a
    slice of a video declares the presentation times its frames carry, which run from the start of the media.

    With no anchor covering the data, reads return these values exactly as declared. To place the data at the
    wall-clock time it happened, supply the anchor covering that data:
    :py:attr:`~roboto.experimental.sessions.FileDeclaration.anchor_ns` on the entry declaring it, or
    :py:attr:`FileTopicDeclaration.anchor_ns` when the topics are declared on the file itself.

    The value may be negative, but once its anchor is added the data must lie between the Unix epoch and the
    largest storable Unix-epoch nanosecond value (``2**63 - 1``): the platform refuses a declaration that would
    place it outside that span, and a later change of anchor that would move it there. A negative value
    therefore needs an anchor of at least its magnitude."""

    max_file_timestamp_ns: int = pydantic.Field(ge=_INT64_MIN, le=_INT64_MAX)
    """Time of the last message this file contributes on this timeline source, in nanoseconds, measured and
    stored the same way as ``min_file_timestamp_ns``."""

    is_default_for_reads: typing.Union[bool, NotSetType] = NotSet
    """Whether reads that name no timeline source resolve to this one:

    1. ``True`` makes this source the one they resolve to, and the source of this schema that held that
       role loses it.
    2. ``False`` takes the role off this source. Once no source of a schema holds it, every read of that
       schema must name a source.
    3. Left unset, every source already stored keeps the role it had. A schema the platform holds no source
       of takes the source reads resolve to from this request: the one the request marks ``True``, or, when
       it marks none, the first one the request leaves unset.

    Within one request, every declaration stating this flag for a source must state the same value, and at
    most one source of a schema may be marked ``True``; the platform refuses a request that breaks either rule
    before writing anything.

    A request that states this flag on any source, ``True`` or ``False``, needs the caller to have topic edit
    access in the org that owns the files, in addition to edit access to the files themselves:
    which source reads resolve to is shared by every file declared under the schema, not set per file.
    The platform refuses a caller without it with :py:exc:`~roboto.exceptions.RobotoUnauthorizedException`,
    before writing anything. A request that leaves the flag unset on every source does not need that access."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: typing.Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        kind_field = cls.model_fields.get("kind")
        if kind_field is None:
            raise TypeError(
                f'{cls.__name__} must declare a `kind: typing.Literal["x"] = "x"` field; without it the '
                "platform cannot route the entry to the timeline source it describes."
            )
        kind = kind_field.default
        if kind != _COLUMN_TIME_SOURCE_KIND and kind not in MESSAGE_ENVELOPE_TIMELINE_SOURCES:
            raise TypeError(
                f"{cls.__name__} declares kind {kind!r}, which says nothing about where its timestamps sit, "
                "so the checks that decide which containers can carry this source cannot place it. A source "
                f"reading the topic's own data columns declares {_COLUMN_TIME_SOURCE_KIND!r}; one reading the "
                "message envelope declares a kind listed in MESSAGE_ENVELOPE_TIMELINE_SOURCES."
            )

    @pydantic.model_validator(mode="after")
    def _force_discriminator_into_fields_set(self) -> "_DeclaredSourceBase":
        """Mark ``kind`` as explicitly set so it survives ``model_dump_json(exclude_unset=True)``.

        Requests go out with unset fields excluded. A ``kind`` left at its subclass default would be dropped
        from the body, and the platform would reject the entry as malformed for want of a discriminator.
        """
        self.__pydantic_fields_set__.add("kind")
        return self

    @pydantic.model_validator(mode="after")
    def _validate_bounds(self) -> "_DeclaredSourceBase":
        if self.min_file_timestamp_ns > self.max_file_timestamp_ns:
            raise ValueError("min_file_timestamp_ns must be <= max_file_timestamp_ns")
        return self


class SchemaFieldSource(_DeclaredSourceBase):
    """Timestamps read from a column of the topic's own data, such as a ``timestamp`` field."""

    kind: typing.Literal["field"] = "field"
    """Discriminator identifying this entry as timestamps read from a data column."""

    field_path: list[str] = pydantic.Field(min_length=1)
    """Path of the field holding this source's timestamps: the names from the schema root down to that field.
    The field must be declared on the topic's schema and typed
    :py:attr:`~roboto.domain.topics.record.CanonicalDataType.Timestamp`."""

    @pydantic.model_validator(mode="after")
    def _validate_field_path(self) -> "SchemaFieldSource":
        if any(not element for element in self.field_path):
            raise ValueError(
                f"field_path {self.field_path!r} has an empty element; name every field on the path from the "
                "schema root down to the timestamp field"
            )
        return self


class McapLogTimeSource(_DeclaredSourceBase):
    """MCAP's log time: when the recorder wrote each record to the file.

    MCAP carries these timestamps in its message envelope rather than in a data column, so this source names
    no field.
    """

    kind: typing.Literal["mcap_log_time"] = "mcap_log_time"
    """Discriminator identifying this entry as MCAP log time."""


class McapPublishTimeSource(_DeclaredSourceBase):
    """MCAP's publish time: when each message was published on the bus.

    MCAP carries these timestamps in its message envelope rather than in a data column, so this source names
    no field.
    """

    kind: typing.Literal["mcap_publish_time"] = "mcap_publish_time"
    """Discriminator identifying this entry as MCAP publish time."""


class Mp4PresentationTimeSource(_DeclaredSourceBase):
    """Presentation time: when each frame is shown, relative to the start of the media.

    These timestamps sit in the message envelope rather than in a data column, so this source names no field.
    The platform stores it as a message-envelope timeline source named ``presentation_time``,
    which is the name a read selects it by.

    Data declared with this source is readable from an MCAP of encoded frames whose messages' log times are the
    presentation times, when the topic lists that MCAP in :py:attr:`TopicDeclaration.representations`.
    The MP4 itself cannot be listed, since no storage format a representation can state describes it.
    A topic with no representations is registered, and a read of it returns no rows,
    as :py:attr:`TopicDeclaration.representations` describes.
    """

    kind: typing.Literal["mp4_presentation_time"] = "mp4_presentation_time"
    """Discriminator identifying this entry as MP4 presentation time."""


DeclaredTimelineSource = typing.Annotated[
    typing.Union[SchemaFieldSource, McapLogTimeSource, McapPublishTimeSource, Mp4PresentationTimeSource],
    pydantic.Field(discriminator="kind"),
]
"""One timeline source a file's topic data carries, with the bounds it spans in this file."""


class RepresentationDeclaration(pydantic.BaseModel):
    """One representation of a topic's data: a file a read of the topic can open, and how that file holds the data.

    Listed in :py:attr:`TopicDeclaration.representations` when a topic is declared, and in
    :py:attr:`TopicRepresentations.representations` when a topic's representations are replaced.
    The platform does not open the file when it is listed, so what this states is taken on trust,
    and a read of the topic that picks this representation opens ``file_id`` and decodes it as stated.

    Every file named by a representation that is untransformed, or whose every transformation is an ``encode``,
    must hold the topic's rows:

    1. At the same positions in each of those files, so a :py:attr:`TopicDeclaration.data_range` names the same
       rows whichever one a read opens. In an MCAP, positions count only the topic's own messages.
    2. Decoding to the topic's declared schema, carrying the timestamps its timeline sources describe: not
       rebased, not converted to other units, not rounded.

    A representation whose file breaks either is accepted, and reads of it return the wrong rows or fail.

    A representation covers the whole topic unless it states a :py:attr:`field_path`,
    in which case it covers that field and everything under it. Its file still holds every row, each with its
    timestamp: a read that takes fields from several files pairs those files row by row,
    and fails when their row numbers or timestamps differ.

    Four things identify a representation among those of one topic: what it covers (the whole topic, or one field),
    its :py:attr:`storage_format`, its :py:attr:`content_format` and its :py:attr:`transformations`.
    Over each part of a file it is declared on, a topic holds at most one representation per combination of the four:
    two with the same combination cannot be listed together, and one declared later takes the earlier one's place.

    A read decodes a ``PARQUET`` representation's file as Parquet; the file needs no ``.parquet`` extension.
    A read can decode an ``MCAP`` representation's file when all three of the following hold:

    1. The file is chunked and carries a summary section indexing those chunks.
    2. Exactly one of the file's channels carries the topic's name.
    3. That channel's schema is in an encoding the platform can decode: ``ros1msg``, ``ros2msg``, ``ros2idl``,
       ``omgidl``, ``jsonschema``, or ``json``.

    A recording holding several topics is therefore read one topic at a time, each from the channel carrying
    its name; the file's other channels are neither decoded nor checked.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="ignore")

    file_id: str = pydantic.Field(min_length=1)
    """File a read opens to get the topic's data: the file the topic is declared on, when its own bytes hold the
    data, or another file of the org, such as a per-topic MCAP converted out of a PX4 ULog.
    Its status must be :py:attr:`~roboto.domain.files.FileStatus.Available`, and the caller must be able to edit it.
    A read through the SDK or the web app downloads this file with the reader's own download permission on it,
    and Roboto's AI tools read it for anyone who can read the topic."""

    storage_format: RepresentationStorageFormat
    """Container ``file_id`` holds the data in. Within one request, every representation naming a file must state
    the same format for it, whichever of the request's topics, files or sessions lists it;
    a request stating two formats for one file is refused when it is built."""

    content_format: typing.Optional[str] = None
    """Format of the data inside the container, such as ``"jpeg"`` for re-encoded images or
    ``"compressedVideo"`` for passed-through video frames, or ``None`` when unspecified. A read names it through
    :py:attr:`~roboto.experimental.topics.RepresentationSelector.content_format`."""

    transformations: list[str] = pydantic.Field(default_factory=list)
    """The transformations applied to the topic's data to produce what ``file_id`` holds, in the order applied,
    as ``"<kind>:<param>"`` descriptors such as ``["downsample:0.7", "encode:jpeg"]``;
    :py:class:`~roboto.domain.topics.TransformationKind` lists the kinds. Empty for untransformed data.
    A read names them through :py:attr:`~roboto.experimental.topics.RepresentationSelector.transformations`,
    and with no selector the platform prefers the representation with the fewest.

    A representation can be read by row position when it is untransformed or every transformation is an ``encode``.
    One with any other transformation, such as a ``downsample``, cannot,
    and a read of a topic declared over a ``data_range`` never uses it:
    on such a topic, everything it covers must also be covered by representations that can.

    Within one topic, every representation naming a file must state the same transformations for it:
    a read that takes two representations from one file and finds their transformations differ raises
    :py:exc:`~roboto.exceptions.RobotoReadPlanExecutionException` with kind ``inconsistent-scan-tasks-on-file``."""

    field_path: typing.Optional[list[str]] = pydantic.Field(default=None, min_length=1)
    """Field of the topic's schema this representation covers, as the names from the schema root down to it.
    ``None``, the same as leaving it out, makes this a representation of the whole topic;
    an empty list and an empty name are refused.

    The path must equal the :py:attr:`~roboto.experimental.ingest.Field.path` of a field the topic's schema
    declares. That field may have fields under it, and the representation then covers those too.
    A level of the schema that only the paths of deeper fields pass through, with no field declared at it,
    cannot be named.

    A read takes each field from the representation covering the deepest field that contains it,
    so a representation of one field supplies that field whatever its transformations,
    and the representations of the whole topic supply the rest. A read asking for untransformed data
    (:py:meth:`RepresentationSelector.raw() <roboto.experimental.topics.RepresentationSelector.raw>`)
    leaves out every representation that states a transformation."""

    @pydantic.model_validator(mode="after")
    def _validate_field_path(self) -> "RepresentationDeclaration":
        if self.field_path is not None and any(not element for element in self.field_path):
            raise ValueError(
                f"field_path {self.field_path!r} has an empty element; name every field on the path from the "
                "schema root down to the field the representation covers"
            )
        return self


def _reject_representations_alike_in_all_but_file(
    representations: collections.abc.Iterable[RepresentationDeclaration],
) -> None:
    """Raise when two of one topic's representations agree on every attribute other than ``file_id``.

    Over each part of a file a topic is declared on, the platform stores at most one representation per thing
    covered (the whole topic, or one field), storage format, content format and transformations,
    so it would store the second of two such representations in place of the first.
    A representation of the whole topic and a representation of one field differ in what they cover,
    so both can be listed.

    Args:
        representations: The representations one topic lists.

    Raises:
        ValueError: Two representations agree on every attribute other than ``file_id``, whether or not they name
            the same file.
    """
    file_by_attributes_but_file: dict[
        tuple[typing.Optional[tuple[str, ...]], RepresentationStorageFormat, typing.Optional[str], tuple[str, ...]],
        str,
    ] = {}
    for representation in representations:
        attributes_but_file = (
            None if representation.field_path is None else tuple(representation.field_path),
            representation.storage_format,
            representation.content_format,
            tuple(representation.transformations),
        )
        if attributes_but_file in file_by_attributes_but_file:
            covered = "the whole topic" if representation.field_path is None else f"field {representation.field_path!r}"
            raise ValueError(
                f"two representations, naming files {file_by_attributes_but_file[attributes_but_file]!r} and "
                f"{representation.file_id!r}, both cover {covered} under the same storage format, content format "
                "and transformations; the platform stores one representation per such combination for a topic "
                "and slice, so list at most one of them"
            )
        file_by_attributes_but_file[attributes_but_file] = representation.file_id


def _reject_files_named_under_different_transformations(
    representations: collections.abc.Iterable[RepresentationDeclaration],
) -> None:
    """Raise when two of one topic's representations name the same file under different transformations.

    A read fails when two representations it takes from one file state different transformations:
    an untransformed representation of the whole topic beside a re-encoded representation of one field, say.

    Args:
        representations: The representations one topic lists.

    Raises:
        ValueError: Two representations name one file under different transformations.
    """
    transformations_by_file: dict[str, list[str]] = {}
    for representation in representations:
        stated = transformations_by_file.setdefault(representation.file_id, representation.transformations)
        if stated != representation.transformations:
            raise ValueError(
                f"file {representation.file_id!r} is named by representations stating transformations {stated!r} "
                f"and {representation.transformations!r}; a read that takes both from the file fails, so state "
                "the same transformations on every representation of the topic that names it"
            )


def _reject_files_named_in_different_storage_formats(
    representations: collections.abc.Iterable[RepresentationDeclaration],
) -> None:
    """Raise when representations of one request state two storage formats for the same file.

    A file holds its bytes in one format, so the two statements contradict each other whichever topics make
    them.

    Args:
        representations: Every representation the request lists, across all of its topics.

    Raises:
        ValueError: Two representations name the same file in different storage formats.
    """
    format_by_file: dict[str, RepresentationStorageFormat] = {}
    for representation in representations:
        stated = format_by_file.setdefault(representation.file_id, representation.storage_format)
        if stated != representation.storage_format:
            raise ValueError(
                f"file {representation.file_id!r} is named by representations stating storage formats "
                f"{stated.value!r} and {representation.storage_format.value!r}; a file holds its bytes in one "
                "storage format, so state the same one on every representation that names it"
            )


class TopicDeclaration(pydantic.BaseModel):
    """A topic a file contributes data to.

    The platform registers the data from the declaration alone, never opening the file, so the declaration
    states the topic's name, the structure of its rows, the bounds of every timeline source those rows
    carry, and which part of the file they occupy.

    List a file's topic declarations on the
    :py:class:`~roboto.experimental.sessions.SessionFile` for that file; that entry anchors everything it
    declares. To register a file's topic data without naming a session, through
    :py:meth:`~roboto.domain.files.File.declare_topics`, build a :py:class:`FileTopicDeclaration` instead;
    with no enclosing entry to anchor it, that form carries its own anchor.

    The file a topic is declared on is the one its data belongs to: the data's slices, bounds and anchors,
    and the windows sessions hold it over, are all stated against that file. Which files a read opens to get
    the data is a separate statement, :py:attr:`representations`, so data can belong to a file the platform
    cannot decode (a PX4 ULog, a ROS ``.bag``, a CSV) and be read from files converted out of it.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    topic_name: str = pydantic.Field(min_length=1)
    """Topic this file (or slice of it) contributes data to. Topic names are unique within an org;
    files declaring the same name contribute to the same topic."""

    topic_schema: Schema
    """Structure of the topic's data. Repeat the same schema on every file that uses it; the platform
    stores each distinct schema once, so repetition costs nothing extra."""

    timeline_sources: list[DeclaredTimelineSource] = pydantic.Field(min_length=1)
    """Timeline sources this file's topic data carries, each with its own bounds. Data timestamped several
    ways (a message's publish time and the time the recorder wrote it, say) declares one entry per source;
    data timestamped one way declares a list of one. Reads pick a source by name, and resolve to the one
    marked ``is_default_for_reads`` when they do not."""

    data_range: typing.Optional[DataRange] = None
    """The part of the file this topic's data occupies, as ``(start, end)``: ``start`` is the first
    covered position, and ``end`` is one past the last. Set this when one file packs a topic's data into
    slices, such as a single episode inside a LeRobot v3 data file. Omit it when the data covers whatever
    encloses this declaration: the slice claimed by the
    :py:class:`~roboto.experimental.sessions.SessionFile` carrying it, or the whole file when the topics are
    declared on the file itself through :py:meth:`~roboto.domain.files.File.declare_topics`. A range set
    inside a :py:class:`~roboto.experimental.sessions.SessionFile` must sit within that entry's own
    :py:attr:`~roboto.experimental.sessions.FileDeclaration.data_range`.

    Values are in the file's own units: stored-row positions (counted from 0), or
    nanoseconds of the file's media time for video. Each file uses exactly one of the two, so the pair
    needs no unit marker; which one applies follows from the file's format. A read applies the range to the
    file it opens, and it opens only files named by representations that can be read by row position,
    as :py:attr:`RepresentationDeclaration.transformations` describes: each of those files must hold the same rows
    at the same positions. Over a range, everything a topic's representations cover must be covered by ones that
    can be read by row position; the platform refuses the declaration otherwise."""

    representations: list[RepresentationDeclaration] = pydantic.Field(default_factory=list)
    """The files a read of this topic's data opens, each with how it holds that data.
    List the file the topic is declared on here, naming its ``file_id``, when its own bytes are readable;
    list other files when the data is read from them, such as the per-topic MCAPs converted out of a PX4 ULog.
    A topic may list several, and a read picks among them by
    :py:class:`~roboto.experimental.topics.RepresentationSelector`.

    A topic with no representations is still registered: its data counts toward the bounds of every session
    holding the file, and a read of it returns no rows, or is refused when the read's
    :py:class:`~roboto.experimental.topics.RepresentationSelector` sets a criterion.
    A video, or a proprietary log with no file converted out of it, is declared that way.

    Redeclaring the topic over the same part of the file adds the representations listed to the ones it has.
    A listed representation takes the place of the stored one that covers what it covers (the whole topic,
    or the same field) under the same storage format, content format and transformations,
    and of every stored one that names the same file, whatever that one covers;
    every other stored representation stays. Redeclaring the topic with the new files a conversion wrote
    therefore replaces each stored representation with the listed one that differs from it only in its ``file_id``;
    redeclaring it with a file uploaded again in another storage format replaces the stored representation that
    names that file; and resending the same declaration leaves the stored representations as they are.
    To remove a representation, or to replace a topic's representations outright,
    use :py:meth:`~roboto.domain.files.File.set_representations`.

    A representation of one field is stored against that field of the schema it was declared under.
    While one is stored, the platform refuses a declaration of the topic over the same part of the file with a
    changed :py:attr:`topic_schema`, unless the declaration lists a representation that takes the stored one's
    place. To change the schema, list the representation of that field again in the same declaration,
    or remove it first with :py:meth:`~roboto.domain.files.File.set_representations`.

    Refused when the model is built:

    1. Two representations covering the same thing (both the whole topic, or the same field) under the same
       storage format, content format and transformations.
    2. Two representations naming one file under different transformations.
    3. A representation whose :py:attr:`~RepresentationDeclaration.field_path` names no field of
       :py:attr:`topic_schema`.
    4. A ``PARQUET`` representation on a topic declaring any timeline source but :py:class:`SchemaFieldSource`:
       the others take their timestamps from the message envelope, which a Parquet file does not have."""

    @pydantic.field_validator("representations")
    @classmethod
    def _validate_representations(
        cls, representations: list[RepresentationDeclaration]
    ) -> list[RepresentationDeclaration]:
        _reject_representations_alike_in_all_but_file(representations)
        _reject_files_named_under_different_transformations(representations)
        return representations

    @pydantic.model_validator(mode="after")
    def _validate_representation_field_paths_name_schema_fields(self) -> "TopicDeclaration":
        declared_paths = {tuple(field.path) for field in self.topic_schema.fields}
        for representation in self.representations:
            if representation.field_path is not None and tuple(representation.field_path) not in declared_paths:
                raise ValueError(
                    f"a representation of topic {self.topic_name!r}, naming file {representation.file_id!r}, states "
                    f"field_path {representation.field_path!r}, which does not match any field declared on the "
                    "topic's schema; declare that field on topic_schema, or name the path of a field it declares"
                )
        return self

    @pydantic.model_validator(mode="after")
    def _validate_message_envelope_sources_have_no_parquet_representation(self) -> "TopicDeclaration":
        if not any(
            representation.storage_format is RepresentationStorageFormat.PARQUET
            for representation in self.representations
        ):
            return self
        for source in self.timeline_sources:
            if source.kind in MESSAGE_ENVELOPE_TIMELINE_SOURCES:
                raise ValueError(
                    f"topic {self.topic_name!r} declares the {source.kind!r} timeline source and lists a "
                    f"representation whose storage_format is {RepresentationStorageFormat.PARQUET.value!r}; those "
                    "timestamps sit in the message envelope, and a Parquet file has none. Declare a "
                    "SchemaFieldSource naming the field that holds the timestamps, or list only representations "
                    f"whose storage_format is {RepresentationStorageFormat.MCAP.value!r}."
                )
        return self

    @pydantic.model_validator(mode="after")
    def _validate_timeline_sources(self) -> "TopicDeclaration":
        declared_fields = {tuple(field.path): field for field in self.topic_schema.fields}

        first_kind_by_stored_key: dict[tuple[str, ...], str] = {}
        seen_stored_names: set[str] = set()
        defaults = 0
        for entry in self.timeline_sources:
            if is_set(entry.is_default_for_reads) and entry.is_default_for_reads:
                defaults += 1

            if isinstance(entry, SchemaFieldSource):
                stored_source_key: tuple[str, ...] = ("schema_field", *entry.field_path)
                stored_name = ".".join(entry.field_path)
                field = declared_fields.get(tuple(entry.field_path))
                if field is None:
                    raise ValueError(
                        f"timeline source {entry.field_path!r} on topic {self.topic_name!r} does not match any "
                        "field declared on the topic's schema; declare that field on topic_schema, or name the "
                        "path of a field it declares"
                    )
                if field.canonical_data_type is not CanonicalDataType.Timestamp:
                    raise ValueError(
                        f"timeline source {entry.field_path!r} on topic {self.topic_name!r} names a field typed "
                        f"{field.canonical_data_type.value!r}; a field a timeline source reads must be "
                        f"declared {CanonicalDataType.Timestamp.value!r}"
                    )
            else:
                stored_kind, stored_name = MESSAGE_ENVELOPE_TIMELINE_SOURCES[entry.kind]
                stored_source_key = (stored_kind,)

            # The stored key identifies the timeline source the platform stores an entry as; the stored name is
            # what a read selects it by. An entry can collide with an earlier one on either without colliding on
            # the other, so both are tracked.
            earlier_kind = first_kind_by_stored_key.get(stored_source_key)
            if earlier_kind == entry.kind:
                raise ValueError(
                    f"topic {self.topic_name!r} declares the same timeline source twice; each timeline source "
                    "a topic carries is declared once, with the bounds it spans in this file"
                )
            if earlier_kind is not None:
                raise ValueError(
                    f"topic {self.topic_name!r} declares both {earlier_kind!r} and {entry.kind!r}; the platform "
                    "stores one timeline for the timestamps a container stamps on its records, so a topic may "
                    "declare at most one of them"
                )
            first_kind_by_stored_key[stored_source_key] = entry.kind

            if stored_name in seen_stored_names:
                raise ValueError(
                    f"topic {self.topic_name!r} declares two timeline sources that reads would both select as "
                    f"{stored_name!r}; each of a topic's timeline sources is stored under a distinct name"
                )
            seen_stored_names.add(stored_name)

        if defaults > 1:
            raise ValueError(
                f"topic {self.topic_name!r} marks {defaults} timeline sources as the default for reads; at "
                "most one timeline source of a topic can be the one reads use when they do not name one"
            )
        return self


class FileTopicDeclaration(TopicDeclaration):
    """One topic a file contributes data to, declared on the file itself rather than inside a session.

    Adds to :py:class:`TopicDeclaration` the wall-clock instant the data was captured at, which a topic
    declared inside a session takes from the entry enclosing it.
    """

    anchor_ns: typing.Optional[_EpochNanosecondsFromTime] = pydantic.Field(default=None, gt=0, le=_INT64_MAX)
    """Optional wall-clock anchor for the data this declaration names: the real-world time, in nanoseconds
    since the Unix epoch, at which that data's time 0 occurred. Must fall after the Unix epoch, and be small
    enough to fit in the signed 64-bit integer the platform stores it in. Also accepts any
    :py:data:`roboto.time.Time` at runtime, read as :py:func:`roboto.time.to_epoch_nanoseconds` reads it;
    convert with that function first to satisfy a type checker. When omitted, the data keeps the anchor it
    already carries from an earlier declaration, and keeps an offset of 0 when it carries none: its
    timestamps read exactly as declared.

    An anchor covers the whole slice named by ``data_range``, not this topic alone, so every topic
    declared over that slice moves to it; two declarations sharing a slice may not name different
    anchors."""


class DeclareTopicsRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/files/id/<file_id>/topics``.

    Registers the topic data one already-uploaded file carries, without naming a session. The platform
    applies each declaration on its own and reports what became of each, so one it refuses leaves the
    others in place. Nothing here is scoped to a session, so calls naming different files run
    concurrently.

    Resending an identical request is safe: a topic plus the slice of the file it names identifies the data a
    declaration registers, so a resend finds what the first attempt registered and reuses it rather than
    registering the data twice.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    topics: list[FileTopicDeclaration] = pydantic.Field(min_length=1, max_length=MAX_FILES_AND_TOPICS_PER_REQUEST)
    """Topics this file contributes data to, between 1 and ``MAX_FILES_AND_TOPICS_PER_REQUEST`` per request.
    One entry per topic and slice of the file: a file carrying one topic across three slices declares three
    entries, and a file whose rows carry four topics at once declares four entries over the same slice."""

    @pydantic.model_validator(mode="after")
    def _validate_declared_topics(self) -> "DeclareTopicsRequest":
        _reject_files_named_in_different_storage_formats(
            representation for topic in self.topics for representation in topic.representations
        )
        anchor_by_range: dict[typing.Optional[DataRange], int] = {}
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

            if topic.anchor_ns is None:
                continue
            stated = anchor_by_range.setdefault(topic.data_range, topic.anchor_ns)
            if stated != topic.anchor_ns:
                raise ValueError(
                    f"topic {topic.topic_name!r} anchors the same part of the file at {topic.anchor_ns} "
                    f"while another topic anchors it at {stated}; an anchor covers the whole slice it "
                    "names, so the topics sharing a slice must agree on the instant it was captured at"
                )
        return self


class TopicRepresentations(pydantic.BaseModel):
    """The complete set of representations one topic's data on a file is read from.

    Handed to :py:meth:`~roboto.domain.files.File.set_representations`, which leaves the topic, over the part of
    the file ``data_range`` names, with exactly these representations.
    :py:class:`RepresentationDeclaration` states what the file each one names must hold.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    topic_name: str = pydantic.Field(min_length=1)
    """Topic whose representations are replaced. It must already be declared on the file."""

    data_range: typing.Optional[DataRange] = None
    """The part of the file over which the topic's representations are replaced,
    or ``None`` for data declared over the whole file.
    It must equal a range the topic is already declared over on the file:
    the topic's :py:attr:`TopicDeclaration.data_range`, or, for a topic that stated none inside a
    :py:class:`~roboto.experimental.sessions.SessionFile`, that entry's
    :py:attr:`~roboto.experimental.sessions.FileDeclaration.data_range`."""

    representations: list[RepresentationDeclaration]
    """The representations the topic ends up with; its representations not listed are removed,
    those of one field included. An empty list removes every representation: the topic stays registered and still
    counts toward the bounds of every session holding the file, but reads of it return no rows.
    Two representations may not cover the same thing (both the whole topic, or the same field) under the same
    storage format, content format and transformations, or name one file under different transformations;
    both are refused when the model is built.
    :py:meth:`~roboto.domain.files.File.set_representations` states what the platform refuses."""

    @pydantic.field_validator("representations")
    @classmethod
    def _validate_representations(
        cls, representations: list[RepresentationDeclaration]
    ) -> list[RepresentationDeclaration]:
        _reject_representations_alike_in_all_but_file(representations)
        _reject_files_named_under_different_transformations(representations)
        return representations


class SetRepresentationsRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/files/id/<file_id>/representations``.

    Replaces the representations of the topics it names on one file, the one the topics were declared on.
    The request is all or nothing: the platform checks every entry before writing any,
    and one refused entry refuses the whole request.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    topics: list[TopicRepresentations] = pydantic.Field(min_length=1, max_length=MAX_FILES_AND_TOPICS_PER_REQUEST)
    """One entry per topic and slice whose representations to replace,
    between 1 and ``MAX_FILES_AND_TOPICS_PER_REQUEST`` per request; split a larger set across several requests.
    Topics not named keep their representations."""

    @pydantic.model_validator(mode="after")
    def _validate_entries(self) -> "SetRepresentationsRequest":
        listed_topic_slices: set[tuple[str, typing.Optional[DataRange]]] = set()
        for entry in self.topics:
            topic_slice = (entry.topic_name, entry.data_range)
            if topic_slice in listed_topic_slices:
                raise ValueError(
                    f"topic {entry.topic_name!r} is listed more than once over the same part of the file; each "
                    "entry states the complete set of representations of one topic and slice, so list each at "
                    "most once"
                )
            listed_topic_slices.add(topic_slice)
        _reject_files_named_in_different_storage_formats(
            representation for entry in self.topics for representation in entry.representations
        )
        return self
