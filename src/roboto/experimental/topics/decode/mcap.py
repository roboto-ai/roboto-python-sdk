# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import decimal
import typing

from ....domain.topics.record import FieldPath
from ....exceptions import RobotoInternalException
from ....formats import FieldSelection
from ....formats.mcap import (
    END_OF_STREAM,
    Accessor,
    McapReader,
    Resolution,
    build_accessor,
    dialect_from_schema_encoding,
    getter_for,
    open_for_window,
    remap_time_fields,
)
from ....logging import default_logger
from ....storage import as_io_bytes
from ....time import TimeUnit
from ..read_plan import (
    ReadPlanScanTask,
    ReadPlanTimestamp,
    TimeWindow,
)
from .common import ScanTaskDecodeParams, disambiguated_timestamp_name, leaf_most
from .schema_tree import SchemaNode, SchemaTree
from .transpose import ColumnTransposer, record_batch_from_columns

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

logger = default_logger()

BATCH_ROW_COUNT = 1024
"""Row count per RecordBatch built from a decoded message stream."""


def mcap_decode_paths(tree: SchemaTree, timestamp: ReadPlanTimestamp) -> list[FieldPath]:
    """The leaf-most paths the reader must decode: every output column's leaves, plus the timestamp field.

    A schema-field timestamp outside the projection is decoded anyway (rows are
    keyed by it); the restricted tree has already excluded it from the output
    columns, so it gets no column even though it is read.
    """
    paths = [leaf.path for column in tree.columns for leaf in column.leaves()]
    if timestamp.kind == "schema_field" and timestamp.field is not None:
        paths.append(timestamp.field.path)
    return leaf_most(paths)


@dataclasses.dataclass(frozen=True)
class McapDecodePlan:
    """The fixed decode shape for one MCAP scan task, settled from the schema and projection.

    Everything here is independent of the message stream: the output columns and
    their Arrow types, the leaf-most paths to read, how the timestamp is sourced,
    and the disambiguated timestamp column name. No build strategy and no per-leaf
    classification — structure comes from the schema, so there is nothing to infer
    from a sample.
    """

    columns: tuple[SchemaNode, ...]
    """The output columns (top-level projected fields), in projection order."""

    decode_paths: list[FieldPath]
    """The leaf-most paths handed to the reader (column leaves plus the timestamp field)."""

    timestamp_path: FieldPath
    """The schema-field timestamp's path, or ``()`` for an envelope timestamp."""

    timestamp_name: str
    """The emitted timestamp column name, disambiguated from any output-column collision."""


def resolve_mcap_decode_plan(tree: SchemaTree, timestamp: ReadPlanTimestamp) -> McapDecodePlan:
    """Settle the fixed decode shape from a projection-restricted schema tree.

    Computed once, before the fetch, and reused for every message and batch.
    """
    return McapDecodePlan(
        columns=tree.columns,
        decode_paths=mcap_decode_paths(tree, timestamp),
        timestamp_path=timestamp.field.path if timestamp.field is not None else (),
        timestamp_name=disambiguated_timestamp_name(column.name for column in tree.columns),
    )


class _LazyAccessors:
    """Schema-derived leaf accessors, compiled lazily on the first message and pinned once resolved.

    The leaves' structural resolutions come from the schema, so they never sample.
    The only sample-dependent step is the ROS time-field name remap, which a first
    message past an empty sequence cannot fully observe; until every leaf's remap is
    resolved the accessors are recompiled per message (never pinned), mirroring the
    accessor cache's refusal to pin a speculative compile. Structure is always correct
    in the meantime — only time-field names may be provisional.
    """

    def __init__(self, resolutions: collections.abc.Sequence[Resolution]) -> None:
        self._resolutions = resolutions
        self._accessors: typing.Optional[list[Accessor]] = None
        self._pinned = False

    def run(
        self,
        message: typing.Any,
        getter: typing.Any,
        is_class_getter: bool,
        accumulator: dict[str, typing.Any],
    ) -> None:
        """Run every leaf accessor into ``accumulator``, recompiling until time-field names pin."""
        if self._accessors is None or not self._pinned:
            built: list[Accessor] = []
            pinned = True
            for resolution in self._resolutions:
                remapped, time_resolved = remap_time_fields(resolution, message, getter)
                built.append(build_accessor(remapped, getter, is_class_getter))
                pinned = pinned and time_resolved
            self._accessors = built
            self._pinned = pinned
        for accessor in self._accessors:
            accessor(message, accumulator)


def extract_row_timestamp(row: dict[str, typing.Any], timestamp: ReadPlanTimestamp) -> typing.Optional[int]:
    """Read the designated timestamp field out of a decoded row, normalized to nanoseconds."""
    if timestamp.field is None:
        return None
    value: typing.Any = row
    for component in timestamp.field.path:
        if not isinstance(value, dict) or component not in value:
            return None
        value = value[component]
    if not isinstance(value, (int, float)):
        return None

    unit = TimeUnit(timestamp.unit) if timestamp.unit is not None else TimeUnit.Nanoseconds
    multiplier = unit.nano_multiplier()
    if isinstance(value, float):
        # Route float timestamps through str -> Decimal, never value * multiplier: a float
        # multiply drops low-order nanosecond digits past 2**53. This mirrors the float
        # branch of roboto.time.to_epoch_nanoseconds, inlined to skip its per-call debug
        # log on this per-row path.
        return int(decimal.Decimal(str(value)) * multiplier)
    return int(value * multiplier)


def stored_timestamp_for_message(
    timestamp: ReadPlanTimestamp,
    timestamp_accessors: typing.Optional[_LazyAccessors],
    message: typing.Any,
    log_time: typing.Union[int, float],
    publish_time: typing.Union[int, float],
) -> typing.Optional[int]:
    """The message's stored-time timestamp, or ``None`` when it carries no designated value.

    Envelope timestamps (log time, publish time) are taken straight off the reader
    and coerced to ``int`` (the reader types them ``int | float`` only to carry its
    ``math.inf`` end-of-stream sentinel, which a real message never bears); a
    schema-field timestamp is read through its accessors and normalized to
    nanoseconds. Only a schema-field message that lacks the field returns ``None`` —
    the caller skips such messages.
    """
    if timestamp.kind == "message_log_time":
        return int(log_time)
    if timestamp.kind == "message_publish_time":
        return int(publish_time)
    if timestamp_accessors is None:
        return None
    getter = getter_for(message)
    ts_accumulator: dict[str, typing.Any] = {}
    timestamp_accessors.run(message, getter, not isinstance(message, dict), ts_accumulator)
    return extract_row_timestamp(ts_accumulator, timestamp)


def decode_mcap_batches(
    scan_task: ReadPlanScanTask,
    timestamp: ReadPlanTimestamp,
    window: TimeWindow,
    projection_paths: collections.abc.Sequence[FieldPath],
    schema_tree: typing.Optional[SchemaTree],
    params: ScanTaskDecodeParams,
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Build nested RecordBatches directly from decoded MCAP messages, typed from the schema.

    The column set, order, and Arrow types are fixed from the schema tree restricted
    to the projection: one column per projected top-level field, every batch. Each
    column's value is extracted per message through schema-derived accessors and
    transposed into a typed Arrow column. An unprojected timestamp field simply gets
    no column (the restricted tree excludes it); it is still decoded to key the rows.

    Batches come out in the reader's native chunk order (its cross-chunk log-time
    sort is skipped), which is the file's persisted order — the order the partition
    overlay and cross-partition concatenation rely on (see
    :py:meth:`DecodedScanTask.batches`).

    Raises:
        RobotoInternalException: No schema tree was supplied; production always
            supplies one resolved from the topic's schema.
    """
    if schema_tree is None:
        raise RobotoInternalException("MCAP decode requires a schema tree; none was supplied.")

    tree = schema_tree.restrict(projection_paths)
    plan = resolve_mcap_decode_plan(tree, timestamp)

    column_leaves = [leaf for column in plan.columns for leaf in column.leaves()]
    column_accessors = _LazyAccessors([tree.resolution_for(leaf) for leaf in column_leaves])
    timestamp_accessors = (
        _LazyAccessors([tree.resolution_for_path(timestamp.field.path)])
        if timestamp.kind == "schema_field" and timestamp.field is not None
        else None
    )

    transposers: list[ColumnTransposer] = []
    timestamps: list[int] = []

    def build() -> "pyarrow.RecordBatch":
        fields: list["pyarrow.Field"] = []
        arrays: list["pyarrow.Array"] = []
        for transposer in transposers:
            field, array = transposer.column()
            fields.append(field)
            arrays.append(array)

        return record_batch_from_columns(plan.timestamp_name, timestamps, fields, arrays)

    start = window.start
    end = window.end

    signed_url = params.signed_url_resolver(scan_task.object.fs_node_id)
    if timestamp.kind == "message_log_time":
        # The chunk index and the message iterator are both keyed by log time,
        # so the window can bound the fetch and the iteration directly. The
        # mcap iterator's end bound is exclusive; the window is inclusive.
        http_reader = open_for_window(signed_url, start_time=start, end_time=end + 1)
    else:
        # Timestamps come from somewhere other than the log time, so log-time
        # bounds cannot be trusted to window-filter; read everything and
        # filter per message below.
        http_reader = open_for_window(signed_url)

    try:
        reader = McapReader(
            stream=as_io_bytes(http_reader),
            fields=[FieldSelection(path_in_schema=path) for path in plan.decode_paths],
            start_time=start if timestamp.kind == "message_log_time" else None,
            end_time=end + 1 if timestamp.kind == "message_log_time" else None,
            log_time_order=False,
        )

        # The column types depend on the dialect, which is read from the message schema encoding.
        dialect = dialect_from_schema_encoding(reader.schema_encoding)
        transposers = [ColumnTransposer(column, dialect) for column in plan.columns]

        while reader.has_next:
            envelope = reader.next_envelope_timestamp
            log_time = envelope.log_time
            publish_time = envelope.publish_time
            message = reader.next_decoded()
            if message is END_OF_STREAM:
                continue

            stored_timestamp = stored_timestamp_for_message(
                timestamp, timestamp_accessors, message, log_time, publish_time
            )
            if stored_timestamp is None:
                logger.debug(
                    "Skipping message without designated timestamp field in file %s",
                    scan_task.object.fs_node_id,
                )
                continue
            if stored_timestamp < start or stored_timestamp > end:
                continue

            getter = getter_for(message)
            accumulator: dict[str, typing.Any] = {}
            column_accessors.run(message, getter, not isinstance(message, dict), accumulator)

            timestamps.append(stored_timestamp)
            for column, transposer in zip(plan.columns, transposers):
                transposer.append_row(accumulator.get(column.name))

            if len(timestamps) >= BATCH_ROW_COUNT:
                yield build()
                timestamps = []
                for transposer in transposers:
                    transposer.reset()
        if timestamps:
            yield build()

    finally:
        http_reader.close()
