# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing

from ....compat import import_optional_dependency
from ....domain.topics.record import FieldPath
from ....formats import FieldSelection
from ....formats.parquet import (
    Timestamp as ParquetTimestamp,
)
from ....formats.parquet import (
    compute_time_filter_mask,
    extract_timestamp_field,
    extract_timestamps,
    narrow_list_nested_fields,
    open_parquet_file,
    resolve_columns,
    should_narrow_list_nested_fields,
    should_read_row_group,
)
from ..batch_transforms import timestamp_field
from ..read_plan import (
    ReadPlanScanTask,
    ReadPlanTimestamp,
    TimeWindow,
)
from .common import ScanTaskDecodeParams, disambiguated_timestamp_name, leaf_most

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep

CACHED_PARQUET_NAME_PATTERN = "{fs_node_id}.parquet"
"""Filename template for locally cached Parquet files; keyed on the stable file id."""


def row_group_fully_in_window(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: ParquetTimestamp,
    start: int,
    end: int,
) -> bool:
    """Whether column-chunk statistics prove every row's timestamp is non-null and within the inclusive window.

    Conservative: any absent or incomplete statistic returns ``False``.
    Returns ``True`` only when the timestamp column chunk reports zero nulls and a [min, max] range that sits inside
    ``[start, end]`` — conditions under which the row-level mask would be all-true.
    """
    for col_idx in range(row_group_metadata.num_columns):
        col_chunk_meta = row_group_metadata.column(col_idx)
        if col_chunk_meta.path_in_schema != timestamp.field.name:
            continue

        stats = col_chunk_meta.statistics
        if stats is None or not stats.has_min_max:
            return False

        # pyarrow's type stubs omit Statistics.has_null_count (present at runtime); read it dynamically.
        has_null_count: bool = getattr(stats, "has_null_count")
        if not has_null_count or stats.null_count != 0:
            return False

        min_val = stats.min
        max_val = stats.max
        if min_val is None or max_val is None:
            return False

        return timestamp.to_epoch_nanoseconds(min_val) >= start and timestamp.to_epoch_nanoseconds(max_val) <= end

    return False


def parquet_filtered_row_groups(
    scan_task: ReadPlanScanTask,
    timestamp: ReadPlanTimestamp,
    window: TimeWindow,
    projection_paths: collections.abc.Sequence[FieldPath],
    params: ScanTaskDecodeParams,
) -> collections.abc.Generator[tuple["pyarrow.Table", "pyarrow.Int64Array"], None, None]:
    """Yield each surviving row group as ``(projected_table, stored_timestamps)``.

    The table holds the projected columns only (the timestamp column is read
    for filtering and dropped when the projection omits it); rows are filtered
    to ``window`` (inclusive on both ends), and ``stored_timestamps`` is
    the aligned int64 nanosecond column.
    """
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    if timestamp.kind != "schema_field" or timestamp.field is None:
        # Parquet files don't have "message envelopes" like MCAP messages, so this should be an impossible code path.
        raise NotImplementedError(
            "Roboto does not support reading this topic's data. Please reach out to Roboto support."
        )

    start = window.start
    end = window.end
    fs_node_id = scan_task.object.fs_node_id

    decode_paths = leaf_most(projection_paths)
    field_selections = [FieldSelection(path_in_schema=path) for path in decode_paths]
    timestamp_selection = FieldSelection(path_in_schema=timestamp.field.path)

    # The designated timestamp column is materialized even when the projection
    # omits it (it window-filters the rows), so the fetch-mode estimate must
    # count it. When the timestamp is itself projected it is already among the
    # field selections, so it is not added twice.
    timestamp_is_projected = any(
        selection.source_path == timestamp_selection.source_path for selection in field_selections
    )
    estimated_column_count = len(field_selections) + (0 if timestamp_is_projected else 1)

    parquet_file = open_parquet_file(
        url_provider=lambda: params.signed_url_resolver(fs_node_id),
        cache_outfile=params.cache_dir / CACHED_PARQUET_NAME_PATTERN.format(fs_node_id=fs_node_id),
        policy=params.cache_policy,
        estimated_column_count=estimated_column_count,
        size_bytes=scan_task.object.size_bytes,
    )

    # schema_arrow and metadata are pyarrow properties that rebuild a wrapper on each access;
    # deriving each once per file keeps the per-row-group loop off that path.
    arrow_schema = parquet_file.schema_arrow
    columns = resolve_columns(arrow_schema, field_selections)

    # Whether any projected field addresses a leaf inside a list decides if the post-read prune is necssary.
    # PyArrow already narrows pure struct and scalar projections during column selection.
    needs_list_narrowing = should_narrow_list_nested_fields(arrow_schema, field_selections)

    # The timestamp column is read even when the projection omits it, to
    # window-filter rows; it is dropped from the output in that case.
    include_timestamp_column = timestamp_selection.source_path in columns
    if not include_timestamp_column:
        columns.append(timestamp_selection.source_path)

    # An absent unit (None) defaults to nanoseconds — the convention the plan's
    # extents and offsets assume. The guard is `is not None`, not falsy, so a
    # set-but-empty unit is passed through and rejected downstream by TimeUnit
    # rather than silently coerced.
    unit_hint = timestamp.unit if timestamp.unit is not None else "ns"
    timestamp_arrow_field = extract_timestamp_field(arrow_schema, timestamp_selection, unit_hint=unit_hint)

    file_metadata = parquet_file.metadata
    for row_group_index in range(file_metadata.num_row_groups):
        row_group_metadata = file_metadata.row_group(row_group_index)
        if not should_read_row_group(row_group_metadata, timestamp_arrow_field, start, end):
            continue

        row_group_table = parquet_file.read_row_group(row_group_index, columns=columns)
        if needs_list_narrowing:
            row_group_table = narrow_list_nested_fields(row_group_table, arrow_schema, field_selections)

        timestamps = extract_timestamps(row_group_table, timestamp_arrow_field)

        if not include_timestamp_column:
            row_group_table = row_group_table.drop_columns(timestamp_arrow_field.field.name)

        # row_group_fully_in_window lets the whole step be skipped: when column-chunk statistics prove every row's
        # timestamp is non-null and inside the window, the mask would be all-true, so there is nothing to filter out.
        #
        # Otherwise build the mask. The window [start, end] is inclusive on both ends, but compute_time_filter_mask
        # treats its end bound as exclusive, so it is called with end + 1.
        # A row whose stored timestamp is null becomes a null mask entry, and pc.filter drops
        # null-mask rows, so rows without a designated timestamp never surface.
        if not row_group_fully_in_window(row_group_metadata, timestamp_arrow_field, start, end):
            filter_mask = compute_time_filter_mask(timestamps, start, end + 1)
            if filter_mask is not None:
                row_group_table = pc.filter(row_group_table, filter_mask)
                timestamps = pc.filter(timestamps, filter_mask)

        yield row_group_table, timestamps


def decode_parquet_batches(
    scan_task: ReadPlanScanTask,
    timestamp: ReadPlanTimestamp,
    window: TimeWindow,
    projection_paths: collections.abc.Sequence[FieldPath],
    params: ScanTaskDecodeParams,
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Wrap each surviving Parquet row group into a RecordBatch, prefixed with the stored-time column.

    Empty row groups are skipped. The timestamp column name is suffixed until it
    stops colliding with a projected column, the same disambiguation the MCAP path
    applies.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    for row_group_table, timestamps in parquet_filtered_row_groups(
        scan_task, timestamp, window, projection_paths, params
    ):
        if row_group_table.num_rows == 0:
            continue

        timestamp_name = disambiguated_timestamp_name(row_group_table.column_names)
        schema = pa.schema([timestamp_field(timestamp_name), *row_group_table.schema])
        with_timestamp = pa.Table.from_arrays(
            [timestamps, *(row_group_table.column(index) for index in range(row_group_table.num_columns))],
            schema=schema,
        )
        yield from with_timestamp.combine_chunks().to_batches()
