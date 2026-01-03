# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

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
