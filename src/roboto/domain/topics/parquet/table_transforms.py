# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import functools
import math
import typing

from ....compat import import_optional_dependency
from ....time import TimeUnit
from ..record import MessagePathRecord
from .timestamp import Timestamp

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


def add_column(
    table: "pyarrow.Table", name: str, values: "pyarrow.Array", position: int = 0
) -> "pyarrow.Table":
    pa = import_optional_dependency("pyarrow", "analytics")

    field = pa.field(name, type=values.type)
    return table.add_column(position, field, values)


def enrich_with_logtime_ns(
    table: "pyarrow.Table",
    log_time_column_name: str,
    timestamp: Timestamp,
) -> "pyarrow.Table":
    """
    Add a normalized log_time column in nanoseconds since Unix epoch
    to simplify time-based filtering and to maintain a consistent interface
    with other TopicReaders.
    Derived from the topic's ``CanonicalDataType.Timestamp``-type message path.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    timestamp_values: "pyarrow.Array" = table.column(
        timestamp.field.name
    ).combine_chunks()
    data_type = timestamp.field.type

    # Short-circuit if timestamp message path column is already in target format/unit
    if pa.types.is_int64(data_type) and timestamp.unit() == TimeUnit.Nanoseconds:
        return add_column(table, log_time_column_name, timestamp_values)

    # Derive nanoseconds since unix epoch as int64 from timestamp message path column
    timestamps_as_ns: "pyarrow.Array"
    if pa.types.is_timestamp(data_type):
        timestamps_as_ns = pc.cast(timestamp_values, pa.timestamp("ns", "UTC"))
        # timestamps are internally stored as 64-bit integers
        # https://arrow.apache.org/docs/python/timestamps.html#arrow-pandas-timestamps
        timestamps_as_ns = timestamps_as_ns.view(pa.int64())
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

    return add_column(table, log_time_column_name, timestamps_as_ns)


def drop_column(table: "pyarrow.Table", column_name: str) -> "pyarrow.Table":
    return table.drop_columns(column_name)


def extract_timestamp_field(
    schema: "pyarrow.Schema", timestamp_message_path: MessagePathRecord
) -> Timestamp:
    """Aggregate timestamp info into a helper utility for handling time-based data operations."""
    arrow_field = schema.field(timestamp_message_path.source_path)
    return Timestamp(field=arrow_field, message_path=timestamp_message_path)


def filter_table_by_logtime_ns(
    table: "pyarrow.Table",
    timestamp_column_name: str,
    start_time: typing.Optional[int] = None,
    end_time: typing.Optional[int] = None,
) -> "pyarrow.Table":
    """Filters table rows to include only data within the specified time range."""
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    field: "pyarrow.Field" = pc.field(timestamp_column_name)
    expressions = []
    if start_time is not None:
        # Temporal filtering is inclusive of start time
        expressions.append(pc.greater_equal(field, start_time))

    if end_time is not None:
        # Temporal filtering is exclusive of end time
        expressions.append(pc.less(field, end_time))

    if len(expressions) == 0:
        return table

    combined_expressions = functools.reduce(lambda a, b: a & b, expressions)
    return table.filter(combined_expressions)


def scale_logtime(
    table: "pyarrow.Table", log_time_column_name: str, to_unit: TimeUnit
) -> "pyarrow.Table":
    """
    Scale the log_time column to the given time unit.
    Assumes the log_time values are formatted as nanoseconds since Unix epoch.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    if to_unit == TimeUnit.Nanoseconds:
        # logtime is expected to already be in nanoseconds
        return table

    timestamp_values: "pyarrow.Array" = table.column(
        log_time_column_name
    ).combine_chunks()
    timestamp_field_index = table.schema.get_field_index(log_time_column_name)
    timestamp_field = table.schema.field(timestamp_field_index)

    multiplier = to_unit.nano_multiplier()
    multiplier_scale = int(math.log10(multiplier))
    multiplier_precision = multiplier_scale + 1

    divisor = pa.scalar(multiplier, pa.decimal64(multiplier_precision, 0))

    MAX_64_BIT_INT_PRECISION = 19
    timestamps_scaled: "pyarrow.Array" = pc.divide_checked(
        timestamp_values, divisor
    ).cast(pa.decimal128(MAX_64_BIT_INT_PRECISION, multiplier_scale))

    field = timestamp_field.with_type(timestamps_scaled.type)
    return table.set_column(timestamp_field_index, field, timestamps_scaled)


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
        if (
            start_time is not None
            and max_val is not None
            and start_time > timestamp.to_epoch_nanoseconds(max_val)
        ):
            # Target window of data starts "after" the data contained by this row group
            return False

        min_val = stats.min
        if (
            end_time is not None
            and min_val is not None
            and end_time < timestamp.to_epoch_nanoseconds(min_val)
        ):
            # Target window of data ends "before" the data contained by this row group
            return False

        return True

    # Couldn't figure out the answer by looking at file metadata, so read the row group
    return True
