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
"""Contract version stamped on every plan.

:py:class:`ReadPlan` validation refuses a plan whose version it does not
recognize, so a consumer on an older contract fails at parse time instead of
misreading a newer plan.
"""


class TimeWindow(pydantic.BaseModel):
    """An interval of time in absolute nanoseconds since the Unix epoch, inclusive at both ends.

    A read plan uses this type for three intervals: the window that the plan was resolved over
    (:py:attr:`ReadPlan.window`), the window that selects each partition's rows (:py:attr:`ReadPlanPartition.window`),
    and each partition's :py:attr:`ReadPlanPartition.timeline_extent`. Because all three share this shape, a consumer
    can intersect any two of them directly.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start: int
    """Inclusive lower bound, in nanoseconds."""

    end: int
    """Inclusive upper bound, in nanoseconds."""

    @pydantic.model_validator(mode="after")
    def _bounds_ordered(self) -> TimeWindow:
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class ReadPlanNamedArray(pydantic.BaseModel):
    """An array field of the plan's schema whose elements are named."""

    model_config = pydantic.ConfigDict(frozen=True)

    field_id: str
    """Identifier of the array's schema field."""

    path: FieldPath
    """The array field's path components within the schema."""

    element_names: tuple[str, ...]
    """Name of each element of the array, in element order; at least one, each distinct."""

    @pydantic.field_validator("element_names")
    @classmethod
    def _names_non_empty_and_distinct(cls, element_names: tuple[str, ...]) -> tuple[str, ...]:
        if not element_names:
            raise ValueError("a named array must name at least one element")
        if len(set(element_names)) != len(element_names):
            raise ValueError(f"element_names {list(element_names)!r} repeat a name")
        return element_names


class ReadPlanSchemaRef(pydantic.BaseModel):
    """Identifies the single topic schema the plan uses."""

    model_config = pydantic.ConfigDict(frozen=True)

    schema_id: str
    """Identifier of the resolved topic schema."""

    checksum: str
    """Checksum of the schema's content. A consumer can cache the schema by this value."""

    named_arrays: tuple[ReadPlanNamedArray, ...] = ()
    """Every array field of the schema whose elements are named, whether or not the projection lists its fields.

    A reader takes element names from here alone."""

    @pydantic.model_serializer(mode="wrap")
    def _serialize(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # A schema without named arrays keeps the wire shape it had before they existed.
        serialized = handler(self)
        if not self.named_arrays:
            serialized.pop("named_arrays", None)
        return serialized


class ReadPlanFieldRef(pydantic.BaseModel):
    """A schema field named by both its id and its path components in the schema."""

    model_config = pydantic.ConfigDict(frozen=True)

    field_id: str
    """Identifier of the schema field."""

    path: FieldPath
    """The field's path components within the schema, from the root to the field."""

    elements: typing.Optional[tuple[str, ...]] = None
    """For a projected named array, the names of the elements the read takes; ``None`` takes every element.

    :py:class:`ReadPlan` validation requires one or more distinct names the plan's schema declares for the array."""

    @pydantic.model_serializer(mode="wrap")
    def _serialize(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # A field ref without an element selection keeps the wire shape it had before selections existed.
        serialized = handler(self)
        if self.elements is None:
            serialized.pop("elements", None)
        return serialized


class ReadPlanTimestamp(pydantic.BaseModel):
    """Where a partition's row timestamps come from.

    Timestamps are either read out of a schema field (``kind`` is
    ``"schema_field"``, and ``field`` names which one) or taken from the
    storage envelope (message log or publish time), in which case no schema
    field is involved and ``field`` is ``None``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    kind: TimelineSourceKind
    """How timestamps are sourced: from a schema field, or from the storage envelope."""

    field: typing.Optional[ReadPlanFieldRef] = None
    """The schema field timestamps are read from; set exactly when ``kind`` is ``"schema_field"``."""

    unit: typing.Optional[str] = None
    """Time unit of the designated field's stored values (a :py:class:`~roboto.time.TimeUnit` value, e.g. ``"ms"``).

    Only meaningful for a ``"schema_field"`` source, and only set when the schema declares the
    field's unit. ``None`` when the schema does not record one; a consumer then treats
    non-self-describing values as nanoseconds, the unit the plan's windows and offsets are recorded in.
    Envelope-derived timestamps (message log/publish time) are always assumed nanoseconds.
    """

    source_name: typing.Optional[str] = None
    """Name of the timeline source these timestamps belong to.

    Partitions under different schemas can have timeline sources of the same name. A shared name doesn't show that
    the sources describe the same events. ``None`` in a plan from a Roboto deployment that predates this field.
    """

    @pydantic.field_validator("unit")
    @classmethod
    def _unit_is_well_known(cls, unit: typing.Optional[str]) -> typing.Optional[str]:
        # Reject a malformed unit at the wire boundary, not later in the decode-side TimeUnit(unit)
        # call. None stays valid: it means the schema records no unit. Membership is checked against
        # the enum's values because `unit in TimeUnit` raises TypeError for a non-member before
        # Python 3.12, and this package supports Python 3.10 and up.
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
    """The output fields the plan resolves rows to.

    The projection takes exactly one of two forms: either every field in the
    schema (``all`` is true, and the field list is left implicit so the plan
    need not enumerate a large schema) or an explicit ``fields`` list.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    all: bool = False
    """True when the projection covers every field in the schema."""

    fields: typing.Optional[tuple[ReadPlanFieldRef, ...]] = None
    """The resolved field set when the read is narrowed; ``None`` when ``all`` is true."""

    @classmethod
    def all_fields(cls) -> ReadPlanProjection:
        """Return a projection covering every field in the schema."""
        return cls(all=True)

    @classmethod
    def narrowed(cls, fields: typing.Iterable[ReadPlanFieldRef]) -> ReadPlanProjection:
        """Return a projection narrowed to an explicit field set."""
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
        # Wrap, not plain, so nested fields keep honoring their own serializers, aliases, and the
        # caller's dump flags (by_alias, exclude_none, mode); the default handler serializes every
        # field, then this narrows the output to the one form _exactly_one_form admits.
        serialized = handler(self)
        if self.all:
            return {"all": True}
        # _exactly_one_form guarantees `fields` is set on the narrowed form. Coerce to a list to
        # preserve the prior wire shape in Python mode (the handler hands back a tuple here).
        return {"fields": list(serialized["fields"])}


class ReadPlanObjectRef(pydantic.BaseModel):
    """Points to the file backing a scan task. A consumer fetches the file's bytes from it."""

    model_config = pydantic.ConfigDict(frozen=True)

    fs_node_id: str
    """Identifier of the backing file. Every version of the file shares this id, so a consumer that caches a file's
    bytes keys them by :py:attr:`version` too."""

    size_bytes: typing.Optional[int] = None
    """Size in bytes of the file at :py:attr:`version`; ``None`` when unknown."""

    version: typing.Optional[int] = None
    """Version of the file to read: the version that was current when the service built the plan. ``None`` when the
    file had no current version, or when the service that built the plan doesn't report versions."""


class ReadPlanScanTask(pydantic.BaseModel):
    """One file to open, with the topic to read from it and the format and transformations needed to interpret it.

    Which of the representations satisfying the governing selector backs a scan
    task is service policy and may change between releases; only the selector's
    hard-filter matching rule is contract.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    subtree: typing.Optional[ReadPlanFieldRef] = None
    """The field subtree this scan task covers; ``None`` covers the whole schema."""

    precedence: int
    """Where two scan tasks' subtrees contain the same field, the read takes it from the higher-precedence one."""

    format: RepresentationStorageFormat
    """The format the bytes are stored in; selects the decoder a consumer applies."""

    transformations: tuple[str, ...] = ()
    """Transformations applied to produce this variant, in order; empty on the original."""

    object: ReadPlanObjectRef
    """The single file this scan task resolves to."""

    topic_name: typing.Optional[str] = None
    """Name of the topic whose records this scan task reads from its file.

    A file can hold several topics (an MCAP file does when its channels carry different topic names), so a reader
    selects the topic's records by this name. ``None`` when the plan does not name the topic; a reader then reads
    the file as holding a single topic.
    """


class ReadPlanPartition(pydantic.BaseModel):
    """Everything needed to fetch and interpret one in-window partition's bytes."""

    model_config = pydantic.ConfigDict(frozen=True)

    topic_part_id: str
    """Identifier of the partition."""

    time_offset_ns: int
    """Offset a consumer adds to each decoded row timestamp; the same for every row in the partition."""

    window: TimeWindow
    """The window this partition's rows are selected in, in absolute Unix-epoch nanoseconds.

    A consumer keeps only the rows whose stored timestamp, once ``time_offset_ns`` is added, falls inside
    this window, inclusive on both ends. It is the only time filter a read applies.

    It is the caller's window intersected with the part of this partition's backing file the read is
    scoped to, so it can be narrower than :py:attr:`ReadPlan.window`: a read scoped to a Session narrows
    it when the Session holds that file over only part of the file's time span. The narrowing is stated
    per file, so every partition backed by one file carries the same window;
    :py:attr:`ReadPlanPartition.data_range` separates the partitions packed into one file.
    """

    timeline_extent: TimeWindow
    """A hint of where this partition's data lies in time: the first and last timestamps stored for it, inclusive.

    The extent is measured under the timeline source that this plan reads the partition's timestamps from, which
    :py:attr:`timestamp` describes. Both bounds already have :py:attr:`time_offset_ns` added, so they are in absolute
    Unix-epoch nanoseconds, like :py:attr:`window`. A :py:class:`~roboto.domain.topics.TimelineExtentRecord` holds the
    same bounds before the offset is added.

    The extent reflects the partition as stored. Neither the requested window nor a Session that holds only part of
    the file narrows the extent, so every plan that reads the partition under that timeline source carries the same
    extent while the stored bounds and offset stay unchanged. The data can have gaps between the two bounds.

    The extent is a hint, not a bound, so a row can lie outside it. Use it to order work or report progress, but never
    to choose rows. A read takes the rows in the partition's :py:attr:`data_range`, then keeps those that lie in the
    partition's :py:attr:`window`.

    The service lists a partition in a plan only when the partition's extent overlaps its :py:attr:`window`. A read
    therefore returns no rows from a partition whose extent does not overlap the requested window, even a row inside
    that window.
    """

    timestamp: ReadPlanTimestamp
    """Where this partition's row timestamps come from."""

    data_range: typing.Optional[DataRange] = None
    """The slice of the file this partition owns, as ``(start, end)``, or ``None`` for the whole file.

    ``start`` is the first owned position and ``end`` is one past the last, like a Python slice.
    Positions are in the addressing native to the file the slice was declared against: stored-row
    positions counted from 0, or nanoseconds of media time for video. Any slice a
    consumer decodes is a range of stored rows.

    A slice appears when one file packs several partitions' data (a LeRobot v3 data file, for
    example). Each of those partitions carries its own ``time_offset_ns`` and may cover the same
    instants as the partitions beside it in the file, so time alone cannot separate its rows from
    theirs. Restrict each scan task's decode to this slice before filtering by time, or the read
    returns the neighboring partitions' rows too.

    A scan task may name a transformed representation of the file the slice was declared against
    (see :py:attr:`ReadPlanScanTask.transformations`) rather than that file itself. The slice still
    applies unchanged: a partition that owns a slice is served only by representations holding the
    same content at the same positions.
    """

    scan_tasks: tuple[ReadPlanScanTask, ...] = ()
    """The files the plan schedules for this partition.

    Each scan task covers the whole schema or a subtree. Where tasks overlap,
    the read takes each field from the highest-precedence task covering it.

    Projected data outside the subtrees covered by these tasks is unavailable
    from this partition's planned files. The plan does not establish that its
    values are null. A reader must report missing coverage, and a reader that
    returns the supplied data must distinguish unavailable fields from stored
    nulls.

    With no scan tasks, the plan names no file from which to read this
    partition's rows. For the SDK reader's behavior, see
    :py:meth:`~roboto.experimental.topics.Topic.get_data_as_record_batches`.
    """

    fs_node_id: typing.Optional[str] = None
    """Identifier of the file this partition's data was recorded in.

    A scan task can read a transformed representation of that file (see
    :py:attr:`ReadPlanScanTask.transformations`), which is stored as a different file, so a scan task's
    ``object`` does not always name the recording a partition's rows came from; this id does.
    ``None`` when the plan does not name the file.
    """


class UnreadableTopicPartitionsWarning(UserWarning):
    """Warns that a read skips partitions of a topic because the plan gives them no scan tasks.

    ``execute_read_plan`` issues it once, before any row. A caller who needs every partition can make such a read fail
    with ``warnings.simplefilter("error", UnreadableTopicPartitionsWarning)``.
    """

    def __init__(self, topic_id: str, partitions: tuple[ReadPlanPartition, ...]) -> None:
        identifiers = ", ".join(partition.topic_part_id for partition in partitions)
        super().__init__(
            f"Skipping {len(partitions)} partition(s) of topic {topic_id} with no representation this read can use: "
            f"{identifiers}."
        )
        self.partitions = partitions
        """The skipped partitions, which name each one's file and window."""


class ReadPlan(pydantic.BaseModel):
    """Resolves a read of one topic over a time window into the files to fetch and how to interpret them."""

    model_config = pydantic.ConfigDict(frozen=True, populate_by_name=True)

    plan_version: int = PLAN_VERSION
    """Contract version of this plan. Validation refuses a version this model does not recognize."""

    topic_id: str
    """The topic this plan reads."""

    window: typing.Optional[TimeWindow]
    """The time window the plan was resolved over: the bounds the request gave, with the signed 64-bit minimum or
    maximum in place of a bound it omitted.

    A consumer filters rows by each partition's :py:attr:`ReadPlanPartition.window`, not by this window, because a
    partition's window can be narrower.

    ``None`` only when the request omitted a bound and no partition of the topic lies in the window within the
    request's restrictions; the plan then has no partitions.
    """

    schema_: typing.Optional[ReadPlanSchemaRef] = pydantic.Field(default=None, alias="schema")
    """The schema the plan reads under. Serializes as ``schema``.

    ``None`` when no partition of the topic lies in the window (within the request's restrictions), and the plan then
    has no partitions. A plan that names a schema may also have no partitions.
    """

    projection: ReadPlanProjection
    """The output fields a consumer projects decoded rows to."""

    partitions: tuple[ReadPlanPartition, ...] = ()
    """One entry per partition in the window, each its own fetch-and-interpret plan.

    Ordered by when each file's data begins. Partitions backed by the same file are contiguous in this
    tuple, ordered by where their ``data_range`` slice starts in that file, so they arrive in the order
    their data sits in it. This orders whole partitions, not rows.
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
        # The SDK's pydantic floor (>=2.5) predates ConfigDict(serialize_by_alias=...),
        # so the `schema_` -> "schema" alias is applied here to keep the wire shape
        # identical no matter which pydantic version, or dump flags, a consumer uses.
        serialized = handler(self)
        if "schema_" in serialized:
            serialized["schema"] = serialized.pop("schema_")
        return serialized
