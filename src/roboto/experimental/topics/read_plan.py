# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import pydantic

from ...domain.topics import RepresentationStorageFormat, TimelineSourceKind
from ...domain.topics.record import DataRange, FieldPath
from ...time import TimeUnit

PLAN_VERSION: int = 1
"""Version of the read plan format this SDK reads, which Roboto sets on every plan as ``ReadPlan.plan_version``.

``ReadPlan`` refuses any other version, so an SDK that reads an older format fails when it parses a newer plan
instead of misreading it.
"""


class TimeWindow(pydantic.BaseModel):
    """Interval of time in nanoseconds since the Unix epoch, inclusive at both ends.

    A read plan uses it for three intervals: the window the plan was resolved over (``ReadPlan.window``), the window
    that selects each partition's rows (``ReadPlanPartition.window``), and each partition's
    ``ReadPlanPartition.timeline_extent``. Because all three share this shape, a consumer can intersect any two of
    them directly.

    Building it raises ``pydantic.ValidationError`` when ``end`` is before ``start``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start: int
    """Inclusive start, in nanoseconds since the Unix epoch."""

    end: int
    """Inclusive end, in nanoseconds since the Unix epoch."""

    @pydantic.model_validator(mode="after")
    def _bounds_ordered(self) -> TimeWindow:
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class ReadPlanNamedArray(pydantic.BaseModel):
    """Array field of the plan's schema whose elements have names.

    Carried in ``ReadPlanSchemaRef.named_arrays``. Building it raises ``pydantic.ValidationError`` when
    ``element_names`` is empty or repeats a name.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    field_id: str
    """ID of the array's schema field, beginning with ``sf_``."""

    path: FieldPath
    """Components of the array field's path in the schema, in order from the schema root."""

    element_names: tuple[str, ...]
    """Name of each element of the array, in element order."""

    @pydantic.field_validator("element_names")
    @classmethod
    def _names_non_empty_and_distinct(cls, element_names: tuple[str, ...]) -> tuple[str, ...]:
        if not element_names:
            raise ValueError("a named array must name at least one element")
        if len(set(element_names)) != len(element_names):
            raise ValueError(f"element_names {list(element_names)!r} repeat a name")
        return element_names


class ReadPlanSchemaRef(pydantic.BaseModel):
    """Reference to the one topic schema a read plan reads under, carried in ``ReadPlan.schema_``."""

    model_config = pydantic.ConfigDict(frozen=True)

    schema_id: str
    """ID of the topic schema, beginning with ``ts_``."""

    checksum: str
    """Checksum of the schema's content, by which a consumer can cache the schema."""

    named_arrays: tuple[ReadPlanNamedArray, ...] = ()
    """Every array field of the schema whose elements have names, whether or not the projection includes it.

    A reader takes element names from this field alone."""

    @pydantic.model_serializer(mode="wrap")
    def _serialize(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # Omit an empty named_arrays, so the output has only the keys known to SDK versions that do not read it.
        serialized = handler(self)
        if not self.named_arrays:
            serialized.pop("named_arrays", None)
        return serialized


class ReadPlanFieldRef(pydantic.BaseModel):
    """Schema field named by both its ID and its path in the schema.

    Carried in ``ReadPlanProjection.fields``, ``ReadPlanScanTask.subtree`` and ``ReadPlanTimestamp.field``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    field_id: str
    """ID of the schema field, beginning with ``sf_``."""

    path: FieldPath
    """Components of the field's path in the schema, in order from the schema root."""

    elements: typing.Optional[tuple[str, ...]] = None
    """Names of the elements of a projected named array that the read takes, or ``None`` for every element.

    Building a ``ReadPlan`` raises ``pydantic.ValidationError`` unless they are one or more distinct names that
    ``ReadPlanSchemaRef.named_arrays`` declares for the array at ``path``."""

    @pydantic.model_serializer(mode="wrap")
    def _serialize(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # Omit elements when it is None, so the output has only the keys known to SDK versions that do not read it.
        serialized = handler(self)
        if self.elements is None:
            serialized.pop("elements", None)
        return serialized


class ReadPlanTimestamp(pydantic.BaseModel):
    """Source of a partition's row timestamps: a schema field, or each message's log or publish time.

    Carried in ``ReadPlanPartition.timestamp``. Building it raises ``pydantic.ValidationError`` when:

    - ``field`` is set and ``kind`` is not ``"schema_field"``, or ``kind`` is ``"schema_field"`` and ``field`` is
      ``None``.
    - ``unit`` is set and ``kind`` is not ``"schema_field"``.
    - ``unit`` is not a :py:class:`~roboto.time.TimeUnit` value.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    kind: TimelineSourceKind
    """Kind of timeline source the timestamps come from.

    One of ``"schema_field"``, ``"message_log_time"`` or ``"message_publish_time"``.
    """

    field: typing.Optional[ReadPlanFieldRef] = None
    """Schema field the timestamps are read from, set exactly when ``kind`` is ``"schema_field"``."""

    unit: typing.Optional[str] = None
    """Unit of the timestamp field's stored values, as a ``TimeUnit`` value such as ``"ms"``.

    ``None`` when the schema records none. Set only when ``kind`` is ``"schema_field"``. A field whose stored type
    carries its own unit, such as a Parquet TIMESTAMP, is read in that unit. Any other numeric field is read in this
    unit, or in nanoseconds when it is ``None``, the unit of the plan's windows and offsets. Message log and publish
    times are always nanoseconds.
    """

    source_name: typing.Optional[str] = None
    """Name of the timeline source these timestamps come from.

    ``None`` in a plan from a version of Roboto that does not set it.

    Partitions under different schemas can have timeline sources of the same name. A shared name does not show that
    the sources describe the same events.
    """

    @pydantic.field_validator("unit")
    @classmethod
    def _unit_is_well_known(cls, unit: typing.Optional[str]) -> typing.Optional[str]:
        # Refuse an unknown unit when the plan is parsed, before a decoder calls TimeUnit(unit). Membership is tested
        # against the values because `unit in TimeUnit` raises TypeError for a non-member before Python 3.12, and the
        # SDK supports Python 3.10 and up.
        if unit is None or unit in {member.value for member in TimeUnit}:
            return unit

        accepted = ", ".join(repr(member.value) for member in TimeUnit)
        raise ValueError(f"unit {unit!r} is not a recognized TimeUnit; expected one of {accepted}")

    @pydantic.model_validator(mode="after")
    def _field_iff_schema_field(self) -> ReadPlanTimestamp:
        if (self.kind == "schema_field") != (self.field is not None):
            raise ValueError("'field' must be set exactly when kind is 'schema_field'")

        if self.unit is not None and self.kind != "schema_field":
            raise ValueError("'unit' may only be set when kind is 'schema_field'")

        return self


class ReadPlanProjection(pydantic.BaseModel):
    """Output fields a read plan resolves rows to: every field of the schema, or an explicit list.

    Carried in ``ReadPlan.projection``. It sets exactly one of ``all``, which leaves the field list implicit so the
    plan need not list a large schema, and ``fields``. Building it with both or neither raises
    ``pydantic.ValidationError``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    all: bool = False
    """Whether the projection covers every field of the schema."""

    fields: typing.Optional[tuple[ReadPlanFieldRef, ...]] = None
    """Fields the read is narrowed to, or ``None`` when ``all`` is true."""

    @classmethod
    def all_fields(cls) -> ReadPlanProjection:
        """Build a projection that covers every field of the schema."""
        return cls(all=True)

    @classmethod
    def narrowed(cls, fields: typing.Iterable[ReadPlanFieldRef]) -> ReadPlanProjection:
        """Build a projection narrowed to ``fields``."""
        return cls(all=False, fields=tuple(fields))

    @pydantic.model_validator(mode="after")
    def _exactly_one_form(self) -> ReadPlanProjection:
        if self.all and self.fields is not None:
            raise ValueError("projection cannot set both 'all' and 'fields'")
        if not self.all and self.fields is None:
            raise ValueError("projection must set either 'all' or 'fields'")
        return self

    @pydantic.model_serializer(mode="wrap")
    def _serialize(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # A wrap serializer, so the nested fields keep their own serializers and aliases and the caller's dump flags
        # (by_alias, exclude_none, mode) still apply; the output is then cut down to the one form set.
        serialized = handler(self)
        if self.all:
            return {"all": True}
        # The handler returns fields as a tuple in Python mode; a list makes model_dump match the JSON form.
        return {"fields": list(serialized["fields"])}


class ReadPlanObjectRef(pydantic.BaseModel):
    """Reference to the file a scan task reads, from which a consumer fetches the file's bytes.

    Carried in ``ReadPlanScanTask.object``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    fs_node_id: str
    """ID of the file.

    Every version of the file shares this ID, so a consumer that caches a file's bytes keys them by ``version`` too.
    """

    size_bytes: typing.Optional[int] = None
    """Size in bytes of the file at ``version``, or ``None`` when unknown."""

    version: typing.Optional[int] = None
    """Version of the file to read: the version that was current when Roboto built the plan.

    ``None`` when the file had no current version, or when the version of Roboto that built the plan does not report
    versions.
    """


class ReadPlanScanTask(pydantic.BaseModel):
    """File to open for a partition, with the topic to read from it and the format and transformations it is read with.

    Carried in ``ReadPlanPartition.scan_tasks``. A scan task reads one representation of the partition's data that
    meets the ``RepresentationSelector`` chosen for its subtree. Which of several matching representations Roboto
    picks may change between versions of Roboto; only the selector's criteria are guaranteed.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    subtree: typing.Optional[ReadPlanFieldRef] = None
    """Field subtree this scan task covers, or ``None`` for the whole schema."""

    precedence: int
    """Rank of this scan task among the partition's scan tasks.

    Where two scan tasks' subtrees contain the same field, the read takes it from the one with the higher precedence.
    """

    format: RepresentationStorageFormat
    """File format the representation's data is stored in, which selects the decoder a consumer applies."""

    transformations: tuple[str, ...] = ()
    """Transformations applied to the partition's data to produce the representation this scan task reads.

    Listed in the order applied. Empty for the original data.
    """

    object: ReadPlanObjectRef
    """File this scan task reads."""

    topic_name: typing.Optional[str] = None
    """Name of the topic whose records this scan task reads from its file.

    A file can hold several topics (an MCAP file does when its channels carry different topic names), so a reader
    selects the topic's records by this name. ``None`` when the plan does not name the topic; a reader then reads
    the file as holding a single topic.
    """


class ReadPlanPartition(pydantic.BaseModel):
    """Topic partition in a read plan, with the files to fetch for it and how to interpret their bytes.

    Carried in ``ReadPlan.partitions``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    topic_part_id: str
    """Unique ID of the topic partition."""

    time_offset_ns: int
    """Offset in nanoseconds that a consumer adds to each decoded row timestamp.

    The offset is the same for every row in the partition.
    """

    window: TimeWindow
    """Window this partition's rows are selected in, in nanoseconds since the Unix epoch.

    A consumer keeps only the rows whose stored timestamp, once ``time_offset_ns`` is added, falls inside this window,
    inclusive at both ends. It is the only time filter a read applies.

    It is the request's window intersected with the part of this partition's file that the read is restricted to, so
    it can be narrower than ``ReadPlan.window``: a read restricted to a session narrows it when the session holds the
    file over only part of the file's time span. The narrowing is stated per file, so every partition of one file
    carries the same window; ``data_range`` separates the partitions packed into one file.
    """

    timeline_extent: TimeWindow
    """Hint of where this partition's data lies in time: the first and last timestamps stored for it, inclusive.

    The extent is measured under the timeline source that this plan reads the partition's timestamps from, which
    ``timestamp`` describes. Both bounds already have ``time_offset_ns`` added, so they are in nanoseconds since the
    Unix epoch, like ``window``. A :py:class:`~roboto.domain.topics.TimelineExtentRecord` holds the same bounds before
    the offset is added.

    The extent reflects the partition as stored. Neither the requested window nor a session that holds only part of
    the file narrows the extent, so every plan that reads the partition under that timeline source carries the same
    extent while the stored bounds and offset stay unchanged. The data can have gaps between the two bounds.

    The extent is a hint, not a bound, so a row can lie outside it. Use it to order work or report progress, but never
    to choose rows. A read takes the rows in the partition's ``data_range``, then keeps those that lie in the
    partition's ``window``.

    Roboto lists a partition in a plan only when the partition's extent overlaps its ``window``. A read therefore
    returns no rows from a partition whose extent does not overlap the requested window, even a row inside that
    window.
    """

    timestamp: ReadPlanTimestamp
    """Source of this partition's row timestamps."""

    data_range: typing.Optional[DataRange] = None
    """Slice of the file this partition owns, as ``(start, end)``, or ``None`` for the whole file.

    ``start`` is the first owned position and ``end`` is one past the last, like a Python slice. Positions are in the
    addressing native to the file the slice was declared against: stored-row positions counted from 0, or nanoseconds
    of media time for video. Any slice a consumer decodes is a range of stored rows.

    A slice appears when one file packs several partitions' data (a LeRobot v3 data file, for example). Each of those
    partitions carries its own ``time_offset_ns`` and may cover the same instants as the partitions beside it in the
    file, so time alone cannot separate its rows from theirs. Restrict each scan task's decode to this slice before
    filtering by time, or the read returns the neighboring partitions' rows too.

    A scan task may name a transformed representation of the file the slice was declared against (see
    ``ReadPlanScanTask.transformations``) rather than that file itself. The slice still applies unchanged: a partition
    that owns a slice is served only by representations holding the same content at the same positions.
    """

    scan_tasks: tuple[ReadPlanScanTask, ...] = ()
    """Files the plan schedules for this partition.

    Each scan task covers the whole schema or a subtree. Where scan tasks overlap, the read takes each field from the
    highest-precedence scan task covering it.

    Projected data outside the subtrees these scan tasks cover is unavailable from this partition's planned files. The
    plan does not establish that its values are null. A reader must report missing coverage, and a reader that
    returns the data it has must distinguish unavailable fields from stored nulls.

    With no scan tasks, the plan names no file from which to read this partition's rows. The SDK's reader skips such a
    partition and names it in an ``UnreadableTopicPartitionsWarning``.
    """

    fs_node_id: typing.Optional[str] = None
    """ID of the file this partition's data was recorded in.

    A scan task can read a transformed representation of that file (see ``ReadPlanScanTask.transformations``), which
    is stored as a different file, so a scan task's ``object`` does not always name the recording a partition's rows
    came from; this ID does. ``None`` when the plan does not name the file.
    """


class UnreadableTopicPartitionsWarning(UserWarning):
    """A read skips partitions of a topic because the read plan gives them no scan tasks.

    ``Topic.get_data_as_record_batches`` issues it once per read, before it yields any row, and so do ``Topic.get_data``
    and ``Topic.get_data_as_df``, which read through it. A caller who needs every partition can make such a read fail
    with ``warnings.simplefilter("error", UnreadableTopicPartitionsWarning)``.
    """

    def __init__(self, topic_id: str, partitions: tuple[ReadPlanPartition, ...]) -> None:
        identifiers = ", ".join(partition.topic_part_id for partition in partitions)
        super().__init__(
            f"Skipping {len(partitions)} partition(s) of topic {topic_id} with no representation this read can use: "
            f"{identifiers}."
        )
        self.partitions = partitions
        """Skipped partitions, each of which names its file and window."""


class ReadPlan(pydantic.BaseModel):
    """Plan for a read of one topic over a time window: the files to fetch and how to interpret them.

    Response body of ``POST /v2/topics/id/{topic_id}/read-plan``, which Roboto returns for a ``ReadPlanRequest``.
    ``Topic.get_data_as_record_batches`` sends the request and reads the plan.

    Building it raises ``pydantic.ValidationError`` when:

    - ``plan_version`` is not ``PLAN_VERSION``.
    - ``window`` is ``None`` and the plan has partitions.
    - A projected field's ``elements`` is not as ``ReadPlanFieldRef.elements`` requires.
    """

    model_config = pydantic.ConfigDict(frozen=True, populate_by_name=True)

    plan_version: int = PLAN_VERSION
    """Format version of this plan, always ``PLAN_VERSION``."""

    topic_id: str
    """ID of the topic this plan reads."""

    window: typing.Optional[TimeWindow]
    """Time window the plan was resolved over.

    It holds the bounds the request gave, with :py:const:`~roboto.int64.INT64_MIN` or
    :py:const:`~roboto.int64.INT64_MAX` in place of a bound it omitted.

    A consumer filters rows by each partition's ``ReadPlanPartition.window``, not by this window, because a
    partition's window can be narrower.

    ``None`` only when the request omitted a bound and no partition of the topic lies in the window within the
    request's restrictions; the plan then has no partitions.
    """

    schema_: typing.Optional[ReadPlanSchemaRef] = pydantic.Field(default=None, alias="schema")
    """Schema the plan reads under. Serialized under the key ``schema``, and parsed from ``schema`` or ``schema_``.

    ``None`` when no partition of the topic lies in the window (within the request's restrictions), and the plan then
    has no partitions. A plan that names a schema may also have no partitions.
    """

    projection: ReadPlanProjection
    """Output fields a consumer projects decoded rows to."""

    partitions: tuple[ReadPlanPartition, ...] = ()
    """Partitions of the topic in the window, each with the files to fetch for it and how to interpret them.

    Ordered by when each file's data begins. Partitions of the same file are contiguous in this tuple, ordered by where
    their ``data_range`` slice starts in that file, so they arrive in the order their data sits in it. This orders
    whole partitions, not rows.
    """

    @pydantic.field_validator("plan_version")
    @classmethod
    def _recognized_version(cls, plan_version: int) -> int:
        if plan_version != PLAN_VERSION:
            raise ValueError(f"unrecognized plan_version {plan_version}; this consumer understands {PLAN_VERSION}")
        return plan_version

    @pydantic.model_validator(mode="after")
    def _partitions_have_a_window(self) -> ReadPlan:
        if self.window is None and self.partitions:
            raise ValueError("a plan with partitions must have a window")
        return self

    @pydantic.model_validator(mode="after")
    def _element_selections_name_declared_elements(self) -> ReadPlan:
        declared = (
            {tuple(array.path): array.element_names for array in self.schema_.named_arrays} if self.schema_ else {}
        )
        for field in self.projection.fields or ():
            if field.elements is None:
                continue
            names = declared.get(tuple(field.path))
            if names is None:
                raise ValueError(f"projected field {list(field.path)!r} selects elements of no named array")
            if not field.elements or len(set(field.elements)) != len(field.elements):
                raise ValueError(f"projected field {list(field.path)!r} must select one or more distinct elements")
            undeclared = [name for name in field.elements if name not in names]
            if undeclared:
                raise ValueError(f"projected field {list(field.path)!r} selects undeclared elements {undeclared!r}")
        return self

    @pydantic.model_serializer(mode="wrap")
    def _schema_under_alias(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # ConfigDict(serialize_by_alias=...) needs a newer pydantic than the SDK's minimum (2.5), so the
        # schema_ -> "schema" alias is applied here, giving the same keys whatever pydantic version or dump flags a
        # consumer uses.
        serialized = handler(self)
        if "schema_" in serialized:
            serialized["schema"] = serialized.pop("schema_")
        return serialized
