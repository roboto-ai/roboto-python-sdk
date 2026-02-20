# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import math
import typing

from ....compat import import_optional_dependency
from ....time import TimeUnit
from ..record import MessagePathRecord
from .timestamp import Timestamp

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


def compute_time_filter_mask(
    timestamps: "pyarrow.Array",
    start_time: typing.Optional[int] = None,
    end_time: typing.Optional[int] = None,
) -> typing.Optional["pyarrow.BooleanArray"]:
    """
    Compute a boolean mask indicating which rows fall within the specified time range.
    Returns None if no time filtering is needed (both start_time and end_time are None).
    """
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    if start_time is None and end_time is None:
        return None

    masks: list["pyarrow.BooleanArray"] = []
    if start_time is not None:
        # Temporal filtering is inclusive of start time
        masks.append(pc.greater_equal(timestamps, start_time))

    if end_time is not None:
        # Temporal filtering is exclusive of end time
        masks.append(pc.less(timestamps, end_time))

    if len(masks) == 1:
        return masks[0]

    # Combine masks using Kleene logic (a null value means “unknown”, and an unknown value ‘and’ false is always false)
    return pc.and_kleene(masks[0], masks[1])


def extract_timestamps(
    table: "pyarrow.Table",
    timestamp: Timestamp,
) -> "pyarrow.Int64Array":
    """
    Extract timestamps in nanoseconds since Unix epoch from the table's timestamp column.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    timestamp_values: "pyarrow.Array" = table.column(timestamp.field.name).combine_chunks()
    data_type = timestamp.field.type

    # Short-circuit if timestamp message path column is already in target format/unit
    if pa.types.is_int64(data_type) and timestamp.unit() == TimeUnit.Nanoseconds:
        return typing.cast("pyarrow.Int64Array", timestamp_values)

    # Derive nanoseconds since unix epoch as int64 from timestamp message path column
    timestamps_as_ns: "pyarrow.Int64Array"
    if pa.types.is_timestamp(data_type):
        timestamps_as_ns = pc.cast(timestamp_values, pa.timestamp("ns", "UTC"))
        # timestamps are internally stored as 64-bit integers
        # https://arrow.apache.org/docs/python/timestamps.html#arrow-pandas-timestamps
        timestamps_as_ns = typing.cast("pyarrow.Int64Array", timestamps_as_ns.view(pa.int64()))
    elif pa.types.is_floating(data_type):
        multiplier = pa.scalar(timestamp.unit().nano_multiplier())
        # Ensure double precision to avoid overflow
        timestamps_as_doubles = pc.cast(timestamp_values, pa.float64())
        scaled = pc.multiply_checked(timestamps_as_doubles, multiplier)
        timestamps_as_ns = pc.trunc(scaled).cast(pa.int64())
    elif pa.types.is_decimal(data_type):
        # Find narrowest precision decimal that multiplier will fit into.
        # Result of scaling will be a decimal array with precision
        # equal to `sum(timestamp_precision + multipier_precision) + 1`.
        # Without casting multiplier to smallest possible decimal,
        # pyarrow will cast it to the same type as the timestamp values,
        # leading to an error like (e.g.):
        #   > pyarrow.lib.ArrowInvalid: Decimal precision out of range [1, 38]: 39
        nano_multiplier = timestamp.unit().nano_multiplier()
        multiplier_precision = int(math.log10(nano_multiplier)) + 1
        multiplier = pa.scalar(nano_multiplier, pa.decimal64(multiplier_precision, 0))
        scaled = pc.multiply_checked(timestamp_values, multiplier)
        timestamps_as_ns = scaled.cast(pa.int64())
    elif pa.types.is_integer(data_type):
        multiplier = pa.scalar(timestamp.unit().nano_multiplier())
        scaled = pc.multiply_checked(timestamp_values, multiplier)
        timestamps_as_ns = scaled.cast(pa.int64())
    else:
        raise TypeError(
            f"Roboto does not support timestamps formatted as {data_type}. "
            "This is likely an issue with data ingestion. Please contact Roboto support."
        )

    return timestamps_as_ns


def extract_timestamp_field(schema: "pyarrow.Schema", timestamp_message_path: MessagePathRecord) -> Timestamp:
    """Aggregate timestamp info into a helper utility for handling time-based data operations."""
    arrow_field = schema.field(timestamp_message_path.source_path)
    return Timestamp(field=arrow_field, message_path=timestamp_message_path)


def should_read_row_group(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: Timestamp,
    start_time: typing.Optional[int] = None,
    end_time: typing.Optional[int] = None,
) -> bool:
    """
    Determine whether a Parquet row group contains data within the requested time range.
    Used to short-circuit requesting column chunks from the given row group if not relevant.
    """
    for col_idx in range(row_group_metadata.num_columns):
        col_chunk_meta = row_group_metadata.column(col_idx)
        if col_chunk_meta.path_in_schema != timestamp.field.name:
            continue

        stats = col_chunk_meta.statistics
        if stats is None:
            # Without column chunk statistics,
            # we can't know without reading the row group whether it has relevant data
            return True

        max_val = stats.max
        if start_time is not None and max_val is not None and start_time > timestamp.to_epoch_nanoseconds(max_val):
            # Target window of data starts "after" the data contained by this row group
            return False

        min_val = stats.min
        if end_time is not None and min_val is not None and end_time < timestamp.to_epoch_nanoseconds(min_val):
            # Target window of data ends "before" the data contained by this row group
            return False

        return True

    # Couldn't figure out the answer by looking at file metadata, so read the row group
    return True


def _list_ancestor_column(
    schema: "pyarrow.Schema",
    path_in_schema: list[str],
) -> typing.Optional[str]:
    """Return the column path of the nearest list ancestor, or ``None``.

    Walks *path_in_schema* through the Arrow *schema*, checking each intermediate
    field.  If any intermediate field is a list (or large-list) type, returns the
    dot-joined path up to and including that list field — which is the column name
    that should be passed to ``read_row_group(columns=...)`` instead of the full
    leaf path.

    Top-level fields (single-element paths) are never considered nested inside a
    list, so this always returns ``None`` for them.

    Examples::

        # points: list<item: struct<x: int64, y: int64>>
        _list_ancestor_column(schema, ["points", "x"])  # → "points"

        # outer: struct<inner: list<item: struct<x: int64>>>
        _list_ancestor_column(schema, ["outer", "inner", "x"])  # → "outer.inner"

        # position: struct<x: float64, y: float64>
        _list_ancestor_column(schema, ["position", "x"])  # → None
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    if len(path_in_schema) <= 1:
        return None

    current_type = schema.field(path_in_schema[0]).type
    for idx, part in enumerate(path_in_schema[1:], start=1):
        if pa.types.is_list(current_type) or pa.types.is_large_list(current_type):
            return ".".join(path_in_schema[:idx])
        if pa.types.is_struct(current_type):
            current_type = current_type.field(part).type
        else:
            break
    return None


def resolve_columns(
    schema: "pyarrow.Schema",
    message_paths: collections.abc.Iterable[MessagePathRecord],
) -> list[str]:
    """Build a deduplicated list of column names safe for ``read_row_group(columns=...)``.

    Children of list-type columns are replaced by their list ancestor's column name
    because PyArrow's prefix-based nested column selection does not work through list
    wrapper nodes in the physical Parquet schema.  Selecting the parent list column
    already returns its full nested structure.

    This is important because the message-path-to-representation mappings returned by
    the server contain only *leaf* message paths.  For a column like
    ``points: list<struct<x, y>>``, only ``points.x`` and ``points.y`` appear in the
    mapping — the parent ``points`` record is absent.  This function derives the
    correct parent column name from the child's ``path_in_schema``.

    Children of struct-type columns are preserved because PyArrow can resolve them via
    dot-separated prefix matching (e.g. ``"position.x"`` selects the ``x`` child of
    the ``position`` struct).
    """
    columns: list[str] = []
    seen: set[str] = set()
    for mp in message_paths:
        ancestor = _list_ancestor_column(schema, mp.path_in_schema)
        col = ancestor if ancestor is not None else mp.source_path
        if col not in seen:
            columns.append(col)
            seen.add(col)
    return columns
