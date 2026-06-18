# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import pydantic

from ...domain.topics import RepresentationStorageFormat, TimelineSourceKind
from ...domain.topics.record import FieldPath
from ...time import TimeUnit

PLAN_VERSION: int = 1
"""Contract version stamped on every plan.

:py:class:`ReadPlan` validation refuses a plan whose version it does not
recognize, so a consumer on an older contract fails at parse time instead of
misreading a newer plan.
"""


class TimeWindow(pydantic.BaseModel):
    """A closed time window in nanoseconds since the Unix epoch; both bounds inclusive.

    The same shape serves any window the read path carries — the absolute window a plan resolves over,
    and a partition's stored-time window once ``time_offset_ns`` is applied. The bounds' time domain is
    fixed by the context that holds the window, not by this type.
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


class ReadPlanSchemaRef(pydantic.BaseModel):
    """Identifies the single topic schema the plan uses."""

    model_config = pydantic.ConfigDict(frozen=True)

    schema_id: str
    """Identifier of the resolved topic schema."""

    checksum: str
    """Checksum of the schema's content. A consumer can cache the schema by this value."""


class ReadPlanFieldRef(pydantic.BaseModel):
    """A schema field named by both its id and its path components in the schema."""

    model_config = pydantic.ConfigDict(frozen=True)

    field_id: str
    """Identifier of the schema field."""

    path: FieldPath
    """The field's path components within the schema, from the root to the field."""


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
    field's unit. ``None`` when the schema does not record one;
    a consumer then treats non-self-describing values as nanoseconds, matching how the plan's extents are recorded.
    Envelope-derived timestamps (message log/publish time) are always assumed nanoseconds.
    """

    @pydantic.field_validator("unit")
    @classmethod
    def _unit_is_well_known(cls, unit: typing.Optional[str]) -> typing.Optional[str]:
        # Reject a malformed unit at the wire boundary, not later in the decode-side TimeUnit(unit)
        # call. None stays valid: it means the schema records no unit.
        if unit is not None and unit not in TimeUnit:
            accepted = ", ".join(repr(member.value) for member in TimeUnit)
            raise ValueError(f"unit {unit!r} is not a recognized TimeUnit; expected one of {accepted}")

        return unit

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


class ReadPlanExtent(pydantic.BaseModel):
    """A partition's time bounds, clipped to the plan window."""

    model_config = pydantic.ConfigDict(frozen=True)

    min: int
    """Inclusive lower bound, in absolute Unix-epoch nanoseconds."""

    max: int
    """Inclusive upper bound, in absolute Unix-epoch nanoseconds."""

    @pydantic.model_validator(mode="after")
    def _bounds_ordered(self) -> ReadPlanExtent:
        if self.max < self.min:
            raise ValueError("max must be greater than or equal to min")
        return self


class ReadPlanObjectRef(pydantic.BaseModel):
    """Points to the file backing a scan task. A consumer fetches the file's bytes from it."""

    model_config = pydantic.ConfigDict(frozen=True)

    fs_node_id: str
    """Identifier of the backing file. This id is stable, so a consumer can cache on it."""

    size_bytes: typing.Optional[int] = None
    """The source object's size in bytes."""


class ReadPlanScanTask(pydantic.BaseModel):
    """One file to open, with the format and transformations needed to interpret it.

    Which of the representations satisfying the governing selector backs a scan
    task is service policy and may change between releases; only the selector's
    hard-filter matching rule is contract.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    subtree: typing.Optional[ReadPlanFieldRef] = None
    """The field subtree this scan task covers; ``None`` covers the whole schema."""

    precedence: int
    """Where two scan tasks' subtrees overlap, the one with the higher precedence wins."""

    format: RepresentationStorageFormat
    """The format the bytes are stored in; selects the decoder a consumer applies."""

    transformations: tuple[str, ...] = ()
    """Transformations applied to produce this variant, in order; empty on the original."""

    object: ReadPlanObjectRef
    """The single file this scan task resolves to."""


class ReadPlanPartition(pydantic.BaseModel):
    """Everything needed to fetch and interpret one in-window partition's bytes."""

    model_config = pydantic.ConfigDict(frozen=True)

    topic_part_id: str
    """Identifier of the partition."""

    time_offset_ns: int
    """Offset a consumer adds to each decoded row timestamp; the same for every row in the partition."""

    extent: ReadPlanExtent
    """The partition's time bounds, clipped to the window."""

    timestamp: ReadPlanTimestamp
    """Where this partition's row timestamps come from."""

    scan_tasks: tuple[ReadPlanScanTask, ...] = ()
    """The files to read for this partition; empty when the partition has no readable data.

    A partition's rows may be shredded across several scan tasks (record-shredding style), each owning a
    subtree of the schema; the read path reassembles each row per leaf, the highest-precedence scan task
    winning where subtrees overlap. The common case is a single scan task covering the whole schema.
    """


class ReadPlan(pydantic.BaseModel):
    """Resolves a read of one topic over a time window into the files to fetch and how to interpret them."""

    model_config = pydantic.ConfigDict(frozen=True, populate_by_name=True)

    plan_version: int = PLAN_VERSION
    """Contract version of this plan. Validation refuses a version this model does not recognize."""

    topic_id: str
    """The topic this plan reads."""

    window: TimeWindow
    """The time window the plan resolves over."""

    schema_: typing.Optional[ReadPlanSchemaRef] = pydantic.Field(default=None, alias="schema")
    """The resolved schema on a non-empty plan. Serializes as ``schema``.

    ``None`` exactly when the plan is empty: the window contains no partitions,
    or a ``schema_id``/``schema_checksum`` matches no in-window partition
    (data may exist in the window under a different schema).
    """

    projection: ReadPlanProjection
    """The output fields a consumer projects decoded rows to."""

    partitions: tuple[ReadPlanPartition, ...] = ()
    """One entry per partition in the window, each its own fetch-and-interpret plan."""

    @pydantic.field_validator("plan_version")
    @classmethod
    def _recognized_version(cls, plan_version: int) -> int:
        if plan_version != PLAN_VERSION:
            raise ValueError(f"unrecognized plan_version {plan_version}; this consumer understands {PLAN_VERSION}")
        return plan_version

    @pydantic.model_serializer(mode="wrap")
    def _schema_under_alias(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # The SDK's pydantic floor (>=2.5) predates ConfigDict(serialize_by_alias=...),
        # so the `schema_` -> "schema" alias is applied here to keep the wire shape
        # identical no matter which pydantic version, or dump flags, a consumer uses.
        serialized = handler(self)
        if "schema_" in serialized:
            serialized["schema"] = serialized.pop("schema_")
        return serialized
