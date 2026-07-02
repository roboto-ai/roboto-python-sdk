# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections
import collections.abc
import concurrent.futures
import typing

from ...compat import import_optional_dependency
from ...domain.topics.record import FieldPath
from .batch_transforms import (
    timestamp_column_index,
)
from .decode import (
    ScanTaskDecoder,
    leaf_most,
)
from .overlay import overlay_streams
from .read_plan import (
    ReadPlan,
    ReadPlanPartition,
    ReadPlanScanTask,
    TimeWindow,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


_MAX_PARTITION_WORKERS = 32
"""Most partitions decoded at once, which also caps how many decoded partitions are buffered in memory.

Partition decode waits mostly on the network (fetching a signed URL, then ranged
GETs), so this follows the standard library's I/O-oriented thread-pool default of
32 instead of scaling with CPU count."""

_MAX_SCAN_TASK_WORKERS = 8
"""Most scan tasks decoded at once within a single partition.

Kept small because :py:func:`_resolve_partition` may run inside the partition pool,
so the two pools multiply; this bounds the worst-case thread count."""


def execute_plan(
    plan: ReadPlan,
    projection_paths: collections.abc.Sequence[FieldPath],
    decoder: ScanTaskDecoder,
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Decode the files named by a read plan and yield the topic's rows as RecordBatches.

    A plan splits the data into partitions, and within a partition the same rows may
    be stored across several files (one file may hold some columns, another file
    other columns of the same rows). Per partition, the decoded files are merged back
    into whole rows, the plan's declared precedence deciding which file wins a column
    when two carry it, and the partition's time offset is added to make timestamps
    absolute. Partitions are yielded in plan order, which the plan defines by where
    each file's data begins (a file's segments stay contiguous and in segment order);
    they are decoded concurrently but emitted in that order. Across partitions the rows
    are simply concatenated end to end: no deduplication, and rows from different
    partitions are never interleaved (rows within a partition keep their stored order).
    So the output orders whole partitions, not rows — a consumer needing a strict
    row-level time order (overlapping partitions, or rows not stored in time order)
    must sort.

    Args:
        plan: The read plan resolved by the server.
        projection_paths: The columns to read, as explicit field paths. To read every
            column, the caller expands the request against the plan's schema first.
        decoder: Decodes one scan task, choosing the reader by file format.

    Yields:
        RecordBatches. The timestamp column (marked in the schema metadata) holds
        absolute Unix-epoch nanoseconds. Batch sizes and boundaries are arbitrary.
    """
    partitions = plan.partitions
    if len(partitions) <= 1:
        for partition in partitions:
            yield from _resolve_partition(plan, partition, projection_paths, decoder)
        return

    max_workers = min(_MAX_PARTITION_WORKERS, len(partitions))

    def _buffer_partition(partition: ReadPlanPartition) -> list["pyarrow.RecordBatch"]:
        return list(_resolve_partition(plan, partition, projection_paths, decoder))

    # Yield partitions in plan order while decoding up to max_workers ahead. The
    # deque is a sliding window of in-flight decodes: submit on the right, wait on
    # the oldest on the left, refill its slot, then yield. Waiting in submission
    # order (not as_completed) is what keeps the cross-partition order contract.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        remaining = iter(partitions)
        in_flight: collections.deque[concurrent.futures.Future[list["pyarrow.RecordBatch"]]] = collections.deque()
        for _ in range(max_workers):
            try:
                in_flight.append(executor.submit(_buffer_partition, next(remaining)))
            except StopIteration:
                break
        while in_flight:
            future = in_flight.popleft()
            # Exceptions propagate: a failed partition decode fails the read.
            batches = future.result()
            try:
                in_flight.append(executor.submit(_buffer_partition, next(remaining)))
            except StopIteration:
                pass
            yield from batches


def projection_for_subtree(
    projection_paths: collections.abc.Sequence[FieldPath],
    subtree: typing.Optional[FieldPath],
) -> list[FieldPath]:
    """Restrict the plan's projected paths to what one scan task, covering ``subtree``, can produce.

    The projection is requested against the whole schema, but a scan task holds only
    one branch of it. A field path is a tuple naming a location in the nested schema,
    e.g. ``("pose", "position", "x")``, so each projected path falls into one of three
    cases by how it relates to the subtree root:

    - Inside the subtree (``subtree`` is a prefix of it): kept as-is.
    - An ancestor of the subtree (it is a prefix of ``subtree``): it asks for more
      than this scan task holds, so it clamps to the subtree root; this task
      contributes only its own branch.
    - In a different branch (neither is a prefix of the other): dropped, since another
      scan task produces it.

    For ``subtree = ("pose", "position")`` and projected paths ``("pose", "position",
    "x")``, ``("pose",)``, and ``("twist", "linear")``, the result is ``[("pose",
    "position", "x"), ("pose", "position")]``: kept, clamped, and dropped respectively.

    Args:
        projection_paths: The plan's projected field paths, against the whole schema.
        subtree: The root of the scan task's branch, or ``None`` for a scan task that
            covers the whole schema (no restriction).

    Returns:
        The deduplicated paths this scan task is responsible for producing.
    """
    if subtree is None:
        return list(dict.fromkeys(projection_paths))

    projection: dict[FieldPath, None] = {}
    for path in projection_paths:
        if path[: len(subtree)] == subtree:
            projection[path] = None
        elif subtree[: len(path)] == path:
            projection[subtree] = None
    return list(projection)


def _apply_time_offset(batch: "pyarrow.RecordBatch", offset: int) -> "pyarrow.RecordBatch":
    """Add ``offset`` nanoseconds to the timestamp column, converting stored time to absolute time."""
    # A zero offset means stored time is already absolute; skip the pyarrow work.
    if offset == 0:
        return batch
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")
    ts_index = timestamp_column_index(batch.schema)
    shifted = pc.add(batch.column(ts_index), pa.scalar(offset, type=pa.int64()))
    return batch.set_column(ts_index, batch.schema.field(ts_index), shifted)


def _coalesce_scan_tasks(
    scan_tasks: collections.abc.Sequence[ReadPlanScanTask],
    projection_paths: collections.abc.Sequence[FieldPath],
) -> list[tuple[ReadPlanScanTask, list[FieldPath]]]:
    """Group a partition's scan tasks so each backing file is decoded once per layer, not once per field.

    The plan may split one file into a separate scan task per top-level field (e.g.
    one MCAP file holding ``data``, ``header``, ... as distinct scan tasks). Decoding
    that file once per field re-opens, re-fetches, and re-decodes it for an identical
    result. Within a partition a decode depends only on ``(fs_node_id, format,
    transformations, projection_paths)`` -- the time window and timestamp source are
    partition-wide -- so one decode over the union of a group's projections reproduces
    the per-field decodes leaf-for-leaf and row-for-row.

    Tasks group only when they share ``(fs_node_id, format, transformations,
    precedence)``. Precedence is in the key because a grouped stream takes a single
    slot in the overlay's lowest-precedence-first order: one file can win one column's
    overlap and lose another's, so grouping across precedence would silently change
    which layer wins. The union is carried as explicit projection paths, never the
    whole-schema sentinel (``None``): a group that does not span the schema must not
    claim columns it lacks, or it would shadow a lower-precedence layer that has them.

    The server sets a scan task's precedence to its subtree depth, so a group's
    same-precedence subtrees are same-depth and never nested: the union is disjoint
    same-depth paths, none an ancestor of another, so ``leaf_most`` over it drops
    nothing.

    Returns ``(representative_scan_task, union_projection)`` pairs, lowest-precedence
    first, ties in plan order. The representative's own subtree is irrelevant: a
    decoder reads only its file id and format and takes the projection explicitly.
    """
    groups: dict[tuple[typing.Any, ...], tuple[ReadPlanScanTask, list[FieldPath]]] = {}
    # Stable sort by precedence keeps same-precedence tasks in plan order (the
    # overlay's tiebreak); dict insertion order then carries that into each group.
    for scan_task in sorted(scan_tasks, key=lambda task: task.precedence):
        key = (scan_task.object.fs_node_id, scan_task.format, scan_task.transformations, scan_task.precedence)
        projection = projection_for_subtree(projection_paths, scan_task.subtree.path if scan_task.subtree else None)
        existing = groups.get(key)
        if existing is None:
            groups[key] = (scan_task, list(projection))
            continue
        union = existing[1]
        for path in projection:
            if path not in union:
                union.append(path)
    return list(groups.values())


def _resolve_partition(
    plan: ReadPlan,
    partition: ReadPlanPartition,
    projection_paths: collections.abc.Sequence[FieldPath],
    decoder: ScanTaskDecoder,
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Decode one partition's files, merge them into whole rows, and yield them with absolute timestamps.

    The plan's time window is absolute, so it is shifted by the partition's offset
    to compare against the stored timestamps the decoders see.
    """
    offset = partition.time_offset_ns
    partition_local_window = TimeWindow(start=plan.window.start - offset, end=plan.window.end - offset)

    # Group scan tasks backed by the same file at the same layer so each file is
    # opened, fetched, and decoded once rather than once per field. Groups arrive
    # lowest-precedence first, the order the overlay merge expects.
    grouped = _coalesce_scan_tasks(partition.scan_tasks, projection_paths)

    if len(grouped) <= 1:
        # Common case: a single file holds every column, so there is nothing to
        # merge. Pass the decoder's batches through with only the offset applied. A
        # partition with no readable data has zero groups and yields nothing.
        if not grouped:
            return

        scan_task, projection = grouped[0]
        decoded = decoder(scan_task, partition, partition_local_window, projection)
        for batch in decoded.batches():
            yield _apply_time_offset(batch, offset)
        return

    # Several layers: different files hold different columns of the same rows.
    # Decode every layer and merge each row column-by-column, higher precedence
    # winning. Decode concurrently so the layers' fetch/decode network waits
    # overlap. The merge aligns streams by row position, so each is fully buffered
    # first -- peak memory is the whole partition's decoded size. This pool may nest
    # under execute_plan's partition pool, so _MAX_SCAN_TASK_WORKERS stays small to
    # bound the combined thread count.

    def _scan_task_batches(scan_task: ReadPlanScanTask, projection: list[FieldPath]) -> list["pyarrow.RecordBatch"]:
        # overlay_streams pairs streams by row position, so a decoder must emit rows
        # in stored order. MCAP file order and Parquet row order both satisfy this.
        return list(decoder(scan_task, partition, partition_local_window, projection).batches())

    max_workers = min(_MAX_SCAN_TASK_WORKERS, len(grouped))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_scan_task_batches, scan_task, projection) for scan_task, projection in grouped]
        # Collected in submission (= precedence) order, as the merge requires. A
        # failed layer decode propagates and fails the read.
        buffered_streams = [future.result() for future in futures]

    merged = overlay_streams(
        buffered_streams,
        [leaf_most(projection) for _, projection in grouped],
    )
    if merged is not None:
        yield _apply_time_offset(merged, offset)
