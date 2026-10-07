# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Execute a read plan: decode each partition's files and yield the topic's rows as RecordBatches.

:py:func:`execute_read_plan` lists the steps of a read. This module holds the projected paths, the leaf-most paths,
assigning scan tasks and grouping them by file, and reading the partitions in plan order.
Decoding each file lives in :py:mod:`~roboto.experimental.topics.decode`,
combining a split partition in :py:mod:`~roboto.experimental.topics.split_partition`,
and the output schema in that module and :py:mod:`~roboto.experimental.topics.batch_transforms`.
"""

from __future__ import annotations

import collections
import collections.abc
import concurrent.futures
import contextlib
import dataclasses
import itertools
import typing

from ...domain.topics.record import FieldPath
from ...exceptions import (
    ReadPlanExecutionErrorKind,
    RobotoReadPlanExecutionException,
)
from .batch_transforms import topic_data_schema
from .decode.common import (
    FileDecoderOpener,
    ScanTaskGroup,
    SuppliedField,
)
from .read_plan import (
    ReadPlan,
    ReadPlanPartition,
    ReadPlanScanTask,
)
from .split_partition import SplitPartition

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


SchemaFieldPaths = typing.Callable[[str], collections.abc.Iterable[FieldPath]]
"""Returns the path of every field a schema declares, given the schema's id."""

_MAX_PARTITION_WORKERS = 32
"""Most partitions decoded at once, which also caps how many decoded partitions are buffered in memory.

Decoding a partition waits mostly on the network (fetching a signed URL, then ranged GETs), so this is 32 whatever
the CPU count: the cap on ``ThreadPoolExecutor``'s default thread count, ``min(32, CPU count + 4)``."""

_MAX_FILE_WORKERS = 8
"""Most files of one split partition opened and decoded at once.

Kept small because each split partition read in the partition pool starts its own pool of up to this many threads,
so up to :py:data:`_MAX_PARTITION_WORKERS` times this many threads decode files at once."""


_SCAN_TASK_FILE_ATTRIBUTES: tuple[tuple[str, typing.Callable[[ReadPlanScanTask], object]], ...] = (
    ("format", lambda task: task.format),
    ("transformations", lambda task: tuple(task.transformations)),
    ("topic name", lambda task: task.topic_name),
)
"""What the scan tasks on one file must agree on, in the order a disagreement is looked for."""


def projected_paths(plan: ReadPlan, schema_field_paths: SchemaFieldPaths) -> list[FieldPath]:
    """Return the field paths ``plan`` projects.

    A projection that lists its fields gives their paths. A projection of every field (``projection.all``) gives
    every field the plan's schema declares, fetched through ``schema_field_paths``. This is the only case that fetches
    them, and a plan with no scan task in any partition fetches nothing and gives no paths.

    Args:
        plan: The read plan the service resolved.
        schema_field_paths: Returns the path of every field a schema declares, given the schema's id.

    Raises:
        RobotoReadPlanExecutionException: With kind ``plan-without-schema``, when the plan projects every field of its
            schema, a partition has a scan task, and the plan names no schema.
    """
    if not plan.projection.all:
        return [field.path for field in plan.projection.fields or ()]
    if not any(partition.scan_tasks for partition in plan.partitions):
        return []
    if plan.schema_ is None:
        raise RobotoReadPlanExecutionException(
            "The read plan projects every field of its schema and has a partition with a scan task, "
            "but names no schema.",
            kind=ReadPlanExecutionErrorKind.PLAN_WITHOUT_SCHEMA,
        )
    return list(schema_field_paths(plan.schema_.schema_id))


def leaf_most_paths(paths: collections.abc.Iterable[FieldPath]) -> list[FieldPath]:
    """Return the paths among ``paths`` that have no descendant among them.

    A projection lists a struct and its children as separate fields; reading the struct would read every child,
    including one the projection leaves out, so only the leaf-most paths are read. The empty path, which names the
    schema root, and duplicates are dropped. The paths are sorted by their components, each compared by Unicode code
    point.
    """
    ordered = sorted({tuple(path) for path in paths if path})
    return [
        path
        for path, following in zip(ordered, [*ordered[1:], None])
        if following is None or not _is_strict_prefix(path, following)
    ]


def assign_scan_tasks(
    partition: ReadPlanPartition,
    leaf_most: collections.abc.Sequence[FieldPath],
) -> list[ScanTaskGroup]:
    """Return the groups of ``partition``'s scan tasks that supply the leaf-most paths ``leaf_most``.

    A path's supplier is the highest-precedence scan task whose subtree contains it; a task without a subtree
    contains every field. Ties go to the later task in plan order. A task whose subtree lies strictly inside a path,
    and which is the supplier of its own subtree, supplies that subtree. Each supplied field excludes only the
    outermost supplied fields strictly inside it.

    The tasks on one file form one group whatever their precedence, so each file is opened once. Groups come in order
    of their lowest precedence, ties in the order each file first appears among the scan tasks. A group that supplies
    nothing is dropped, unless every group supplies nothing; then the first group is kept, and its file gives only the
    row number and timestamp columns.

    Raises:
        RobotoReadPlanExecutionException: With kind ``inconsistent-scan-tasks-on-file``, when scan tasks on one file
            disagree on its format, transformations or topic name; with kind ``projected-field-in-no-scan-task``, when
            no scan task contains a path of ``leaf_most``.
    """
    tasks = partition.scan_tasks
    subtrees = [task.subtree.path if task.subtree is not None else () for task in tasks]

    def supplier_of(path: FieldPath) -> typing.Optional[int]:
        supplier: typing.Optional[int] = None
        for index, (task, subtree) in enumerate(zip(tasks, subtrees)):
            if _is_prefix_or_equal(subtree, path) and (
                supplier is None or task.precedence >= tasks[supplier].precedence
            ):
                supplier = index
        return supplier

    tasks_on_file: dict[str, list[ReadPlanScanTask]] = {}
    for task in tasks:
        tasks_on_file.setdefault(task.object.fs_node_id, []).append(task)
    for file_tasks in tasks_on_file.values():
        _check_consistent(partition, file_tasks)

    supplies: dict[str, list[SuppliedField]] = {fs_node_id: [] for fs_node_id in tasks_on_file}
    for path in leaf_most:
        supplier = supplier_of(path)
        if supplier is None:
            raise RobotoReadPlanExecutionException(
                f"No scan task of topic partition {partition.topic_part_id} reads the whole schema or a subtree "
                f'containing the projected field "{".".join(path)}".',
                kind=ReadPlanExecutionErrorKind.PROJECTED_FIELD_IN_NO_SCAN_TASK,
            )
        # The path itself is a supplied field of its supplier, and so is each subtree strictly inside it whose own task
        # is that subtree's supplier.
        supplied = [(path, supplier)] + [
            (subtree, index)
            for index, subtree in enumerate(subtrees)
            if _is_strict_prefix(path, subtree) and supplier_of(subtree) == index
        ]
        for supplied_path, supplied_by in supplied:
            inside = [other for other, _ in supplied if _is_strict_prefix(supplied_path, other)]
            outermost = tuple(other for other in inside if not any(_is_strict_prefix(outer, other) for outer in inside))
            supplies[tasks[supplied_by].object.fs_node_id].append(SuppliedField(path=supplied_path, excluded=outermost))

    # sorted is stable, so files of equal lowest precedence keep the order in which they first appear.
    by_lowest_precedence = sorted(
        tasks_on_file.items(), key=lambda file_and_tasks: min(task.precedence for task in file_and_tasks[1])
    )
    groups = [
        ScanTaskGroup(
            object=first.object,
            format=first.format,
            topic_name=first.topic_name,
            supplies=tuple(supplies[fs_node_id]),
        )
        for fs_node_id, [first, *_] in by_lowest_precedence
    ]
    supplying = [group for group in groups if group.supplies]
    return supplying or groups[:1]


def execute_read_plan(
    plan: ReadPlan,
    projected: collections.abc.Sequence[FieldPath],
    open_file_decoder: FileDecoderOpener,
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Decode the files a read plan names and yield the topic's rows as RecordBatches.

    A read takes these steps:

    1. Projected paths: ``projected``, from :py:func:`projected_paths`.
    2. Leaf-most paths (:py:func:`leaf_most_paths`).
    3. Assign scan tasks (:py:func:`assign_scan_tasks`).
    4. Group by file (:py:func:`assign_scan_tasks`).
    5. Decode each file, through the decoders ``open_file_decoder`` opens.
    6. Combine a split partition (:py:class:`~roboto.experimental.topics.split_partition.SplitPartition`).
    7. Output schema (:py:func:`~roboto.experimental.topics.batch_transforms.topic_data_schema`).
    8. Partitions: read in plan order, each one's schema checked against the first partition's when its files open,
       before any of its rows.

    Each partition yields only the rows inside its own :py:attr:`~roboto.experimental.topics.ReadPlanPartition.window`,
    which can be narrower than the plan's: a read scoped to a Session that holds a file over part of its time span
    returns that part of the file and nothing else.

    Partitions without scan tasks are skipped. Partitions are yielded in plan order and their rows are never
    interleaved; within a partition, rows keep their stored order. Nothing is sorted by time or deduplicated, so a
    consumer that needs rows in time order sorts them.

    A plan with one partition to read yields its rows as they are decoded. A plan with several decodes up to 32
    partitions at once and holds each partition's rows until it is yielded. A split partition's files are decoded in
    full before their rows are combined.

    Args:
        plan: The read plan the service resolved.
        projected: The field paths the plan projects, from :py:func:`projected_paths`.
        open_file_decoder: Opens the decoder of one scan task group's file.

    Yields:
        RecordBatches with the columns of :py:func:`~roboto.experimental.topics.batch_transforms.topic_data_schema`:
        the row number, the timestamp in absolute Unix-epoch nanoseconds, then one value column per projected
        top-level field, sorted by name comparing Unicode code points. A batch holds the rows of one partition only;
        batch sizes and boundaries are otherwise arbitrary.

    Raises:
        RobotoReadPlanExecutionException: With the kind of the step that refuses the plan:
            ``projected-field-in-no-scan-task`` or ``inconsistent-scan-tasks-on-file`` (steps 3 and 4);
            ``field-split-inside-non-struct`` or ``scan-task-row-mismatch`` (step 6);
            ``partition-schema-mismatch``, when a partition's files give the read a different schema than the first
            partition's, raised before any error in that partition's rows and even when it has no rows in the window
            (step 8);
            and the kinds ``open_file_decoder`` and its decoders raise, such as ``unsupported-format``,
            ``unsupported-timestamp``, ``invalid-timestamp``, ``field-not-in-file`` and ``data-range-not-in-file``
            (step 5).
    """
    partitions = [partition for partition in plan.partitions if partition.scan_tasks]
    leaf_most = leaf_most_paths(projected)

    if len(partitions) <= 1:
        for partition in partitions:
            with _open_partition(partition, leaf_most, open_file_decoder) as opened:
                yield from opened.batches()
        return

    def read(partition: ReadPlanPartition) -> _PartitionRows:
        return _read_partition(partition, leaf_most, open_file_decoder)

    first_schema: typing.Optional["pyarrow.Schema"] = None
    for partition, rows in zip(partitions, _read_in_plan_order(read, partitions)):
        schema = topic_data_schema(rows.value_fields)
        if first_schema is None:
            first_schema = schema
        elif not schema.equals(first_schema):
            raise RobotoReadPlanExecutionException(
                f"Topic partition {partition.topic_part_id}'s files give the read the schema {schema}, "
                f"where the first partition's gave {first_schema}.",
                kind=ReadPlanExecutionErrorKind.PARTITION_SCHEMA_MISMATCH,
            )
        if rows.decode_error is not None:
            raise rows.decode_error
        yield from rows.batches


@dataclasses.dataclass(frozen=True)
class _OpenedPartition:
    """A partition whose files are open: its value columns, and its rows, which can be decoded once."""

    value_fields: list["pyarrow.Field"]
    batches: typing.Callable[[], collections.abc.Iterator["pyarrow.RecordBatch"]]


@dataclasses.dataclass(frozen=True)
class _PartitionRows:
    """A partition's value columns, known when its files open, and its decoded rows."""

    value_fields: list["pyarrow.Field"]
    batches: list["pyarrow.RecordBatch"]

    decode_error: typing.Optional[Exception] = None
    """The error that stopped decoding the partition's rows, which the read raises only after checking the partition's
    schema; ``batches`` is then empty."""


def _check_consistent(partition: ReadPlanPartition, file_tasks: collections.abc.Sequence[ReadPlanScanTask]) -> None:
    """Raise ``inconsistent-scan-tasks-on-file`` unless the scan tasks on one file agree on how to read it.

    The attributes are compared in the order format, transformations, topic name, and the error names the first
    one on which any task differs from the file's first task.
    """
    first, *others = file_tasks
    disagreement = next(
        (
            name
            for name, value_of in _SCAN_TASK_FILE_ATTRIBUTES
            if any(value_of(task) != value_of(first) for task in others)
        ),
        None,
    )
    if disagreement is None:
        return
    raise RobotoReadPlanExecutionException(
        f"The scan tasks of topic partition {partition.topic_part_id} that read the file {first.object.fs_node_id} "
        f"disagree on its {disagreement}.",
        kind=ReadPlanExecutionErrorKind.INCONSISTENT_SCAN_TASKS_ON_FILE,
    )


def _is_prefix_or_equal(prefix: FieldPath, path: FieldPath) -> bool:
    return path[: len(prefix)] == prefix


def _is_strict_prefix(prefix: FieldPath, path: FieldPath) -> bool:
    return len(prefix) < len(path) and _is_prefix_or_equal(prefix, path)


def _read_in_plan_order(
    read: typing.Callable[[ReadPlanPartition], _PartitionRows],
    partitions: collections.abc.Sequence[ReadPlanPartition],
) -> collections.abc.Iterator[_PartitionRows]:
    """Read ``partitions``, up to :py:data:`_MAX_PARTITION_WORKERS` at once, and yield them in their order."""
    # A sliding window of reads in flight: submit on the right, wait on the oldest on the left, refill its slot, then
    # yield. Waiting in submission order, not as reads complete, keeps the partitions in plan order.
    remaining = iter(partitions)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_PARTITION_WORKERS, len(partitions)))
    try:
        in_flight = collections.deque(
            executor.submit(read, partition) for partition in itertools.islice(remaining, _MAX_PARTITION_WORKERS)
        )
        while in_flight:
            rows = in_flight.popleft().result()
            in_flight.extend(executor.submit(read, partition) for partition in itertools.islice(remaining, 1))
            yield rows
    finally:
        # A read that fails, or a consumer that stops early, leaves no queued read to start.
        executor.shutdown(wait=True, cancel_futures=True)


@contextlib.contextmanager
def _open_partition(
    partition: ReadPlanPartition,
    leaf_most: collections.abc.Sequence[FieldPath],
    open_file_decoder: FileDecoderOpener,
) -> collections.abc.Iterator[_OpenedPartition]:
    """Open the files of a partition with a scan task, and close them when the context exits, however it exits.

    Opening raises the errors found before any row is decoded, such as ``projected-field-in-no-scan-task``,
    ``field-not-in-file`` or ``field-split-inside-non-struct``; an error in the partition's rows is raised while
    decoding them.
    """
    groups = assign_scan_tasks(partition, leaf_most)
    if len(groups) == 1:
        with open_file_decoder(groups[0], partition, partition.window) as decoder:
            yield _OpenedPartition(value_fields=decoder.value_fields, batches=decoder.batches)
        return

    # A split partition: its scan tasks form more than one group, so its rows are read from more than one file.
    # Its files are opened, and later decoded, concurrently so their network waits overlap, and every decoder that
    # opened is closed however the read ends, including when another file fails to open.
    with (
        contextlib.ExitStack() as decoders_to_close,
        concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_FILE_WORKERS, len(groups))) as executor,
    ):
        opening = [executor.submit(open_file_decoder, group, partition, partition.window) for group in groups]
        concurrent.futures.wait(opening)
        for future in opening:
            if future.exception() is None:
                decoders_to_close.push(future.result())
        decoders = [future.result() for future in opening]
        split = SplitPartition(
            topic_part_id=partition.topic_part_id,
            file_decoders=decoders,
            top_level_names=list(dict.fromkeys(path[0] for path in leaf_most)),
        )

        def batches() -> collections.abc.Iterator["pyarrow.RecordBatch"]:
            file_batches = list(executor.map(lambda decoder: list(decoder.batches()), decoders))
            return split.combine(file_batches)

        yield _OpenedPartition(value_fields=split.value_fields, batches=batches)


def _read_partition(
    partition: ReadPlanPartition,
    leaf_most: collections.abc.Sequence[FieldPath],
    open_file_decoder: FileDecoderOpener,
) -> _PartitionRows:
    """Open the files of a partition with a scan task, and decode all its rows.

    An error opening the files propagates. An error decoding the rows is kept in the result, with the value columns
    known at open, so the read checks the partition's schema before it raises the error.
    """
    with _open_partition(partition, leaf_most, open_file_decoder) as opened:
        try:
            batches = list(opened.batches())
        except Exception as error:
            return _PartitionRows(value_fields=opened.value_fields, batches=[], decode_error=error)
        return _PartitionRows(value_fields=opened.value_fields, batches=batches)
