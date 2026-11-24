# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections
import collections.abc
import concurrent.futures
import contextlib
import dataclasses
import itertools
import typing
import warnings

from ...compat import import_optional_dependency
from ...domain.topics.record import FieldPath
from ...exceptions import (
    ReadPlanExecutionErrorKind,
    RobotoReadPlanExecutionException,
)
from .batch_transforms import (
    row_number_column_index,
    timestamp_column_index,
    topic_data_schema,
    with_element_names,
)
from .decode.common import (
    FileDecoderOpener,
    ScanTaskGroup,
    SuppliedField,
)
from .read_plan import (
    ReadPlan,
    ReadPlanPartition,
    ReadPlanScanTask,
    UnreadableTopicPartitionsWarning,
)
from .split_partition import SplitPartition

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


SchemaFieldPaths = typing.Callable[[str], collections.abc.Iterable[FieldPath]]
"""Function that looks up a topic schema by its ID, and returns the path of every field the schema declares."""

_MAX_PARTITION_WORKERS = 32
"""Maximum number of partitions decoded at once, which also bounds how many decoded partitions wait in memory.

Decoding a partition waits mostly on the network, for a signed URL and then for ranged GET requests, so the number
does not depend on the CPU count. It is the upper limit of ``concurrent.futures.ThreadPoolExecutor``'s default
thread count, ``min(32, CPU count + 4)``."""

_MAX_FILE_WORKERS = 8
"""Maximum number of a split partition's files opened and decoded at once.

Each split partition read in the partition pool starts its own pool of up to this many threads, so up to
``_MAX_PARTITION_WORKERS`` times this many threads decode files at once; the number is small for that reason."""


_SCAN_TASK_FILE_ATTRIBUTES: tuple[tuple[str, typing.Callable[[ReadPlanScanTask], object]], ...] = (
    ("format", lambda task: task.format),
    ("transformations", lambda task: tuple(task.transformations)),
    ("topic name", lambda task: task.topic_name),
)
"""Attributes the scan tasks on one file must agree on, each with its name in error messages, in the order compared."""


def projected_paths(plan: ReadPlan, schema_field_paths: SchemaFieldPaths) -> list[FieldPath]:
    """Return the field paths ``plan`` projects.

    A projection that lists its fields gives their paths. A projection of every field (``projection.all``) gives
    every field the plan's schema declares, looked up through ``schema_field_paths``. Only that case calls
    ``schema_field_paths``, and a plan with no scan task in any partition does not call it and returns no paths.
    Pass the result to ``execute_read_plan`` as ``projected``.

    Raises:
        RobotoReadPlanExecutionException: The plan projects every field of its schema, a partition has a scan task,
            and the plan names no schema. Its ``kind`` is
            :py:attr:`~roboto.exceptions.ReadPlanExecutionErrorKind.PLAN_WITHOUT_SCHEMA`.
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

    A projection lists a struct and each of its projected children as separate fields. Reading the struct would read
    every child, including one the projection leaves out, so the read takes only these paths. The empty path, which
    names the schema root, and duplicates are dropped. The paths are sorted by their components, each compared by
    Unicode code point.
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
    """Return ``partition``'s scan tasks grouped by file, with the fields each file supplies for ``leaf_most``.

    These rules choose the scan task that supplies each field:

    1. A path of ``leaf_most`` comes from the highest-precedence scan task whose subtree contains it. A task with no
       subtree contains every field, and the later task in plan order wins a tie.
    2. A task whose subtree lies strictly inside such a path, and which rule 1 would choose for its own subtree,
       supplies that subtree.
    3. Each supplied field leaves out only the outermost supplied fields strictly inside it.

    All the tasks on one file form one group whatever their precedence, so each file is opened once. Groups are
    ordered by the lowest precedence among their tasks, and groups that tie keep the order in which their files first
    appear among the scan tasks. A group that supplies nothing is dropped, unless every group supplies nothing; then
    only the first group is kept, and its file gives only the row number and timestamp columns.

    Args:
        partition: Partition whose scan tasks to group. It has at least one scan task.
        leaf_most: Projected paths with no other projected path inside them, as ``leaf_most_paths`` returns them.

    Raises:
        RobotoReadPlanExecutionException: Scan tasks on one file disagree on its format, transformations or topic
            name (``kind`` is :py:attr:`~roboto.exceptions.ReadPlanExecutionErrorKind.INCONSISTENT_SCAN_TASKS_ON_FILE`),
            or no scan task contains a path of ``leaf_most`` (``kind`` is ``PROJECTED_FIELD_IN_NO_SCAN_TASK``).
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
    """Decode the files a read plan names and yield the topic's rows as Arrow record batches.

    A read takes these steps:

    1. Take the projected paths, ``projected``, from ``projected_paths``.
    2. Keep the projected paths with no other projected path inside them (``leaf_most_paths``).
    3. Choose the scan task that supplies each of those paths (``assign_scan_tasks``).
    4. Group each partition's scan tasks by file (``assign_scan_tasks``).
    5. Open and decode each file, through the decoders ``open_file_decoder`` opens.
    6. Combine the files of a split partition, one whose scan tasks read more than one file, into the partition's
       rows (``SplitPartition``).
    7. Build the output schema (``topic_data_schema``).
    8. Read the partitions in plan order, checking each one's schema against the first partition's when its files
       open, before any of its rows.
    9. Name the array elements in each batch step 8 yields. Each named array column stores its element names as field
       metadata, under ``ELEMENT_NAMES_FIELD_METADATA_KEY``, narrowed to the elements a projected field selects. A
       narrowed array numbers its elements from 0, in element order.

    Each partition yields only the rows inside its own ``ReadPlanPartition.window``, which can be narrower than the
    plan's: a read scoped to a session that holds a file over part of its time span returns that part of the file and
    nothing else.

    Partitions without scan tasks are skipped, and one ``UnreadableTopicPartitionsWarning`` names them before any
    row. Partitions are yielded in plan order and their rows are never interleaved; within a partition, rows keep
    their stored order. Nothing is sorted by time or deduplicated, so a consumer that needs rows in time order sorts
    them.

    A plan with one partition to read yields its rows as they are decoded. A plan with several decodes up to 32
    partitions at once and holds each partition's rows until it is yielded. A split partition's files are decoded in
    full before their rows are combined.

    Args:
        projected: Field paths the plan projects, as ``projected_paths`` returns them.

    Yields:
        Record batches with the columns of ``topic_data_schema``: the row number, the timestamp in nanoseconds since
        the Unix epoch, then one value column per projected top-level field, sorted by name comparing Unicode code
        points. A batch holds the rows of one partition only; batch sizes and boundaries are otherwise arbitrary. A
        named array keeps its stored type, unless the projection selects some of its elements; it is then a
        fixed-size list of those elements in element order.

    Raises:
        RobotoReadPlanExecutionException: A step refuses the plan. It surfaces during iteration, when the read reaches
            the partition at fault, after the rows of every earlier partition. Its ``kind``, a
            :py:class:`~roboto.exceptions.ReadPlanExecutionErrorKind`, names the reason:

            - ``PROJECTED_FIELD_IN_NO_SCAN_TASK`` or ``INCONSISTENT_SCAN_TASKS_ON_FILE``, from steps 3 and 4.
            - ``UNSUPPORTED_FORMAT``, ``UNSUPPORTED_TIMESTAMP``, ``INVALID_TIMESTAMP``, ``FIELD_NOT_IN_FILE``,
              ``DATA_RANGE_NOT_IN_FILE``, or another kind ``open_file_decoder`` and its decoders raise, from step 5.
            - ``FIELD_SPLIT_INSIDE_NON_STRUCT`` or ``SCAN_TASK_ROW_MISMATCH``, from step 6.
            - ``PARTITION_SCHEMA_MISMATCH``, from step 8, when a partition's files give the read a different schema
              than the first partition's. It is raised before any error in that partition's rows, and even when the
              partition has no rows in the window.
            - ``ELEMENT_COUNT_MISMATCH``, from step 9, when a named array holds a different number of elements than
              it has names. For an array stored as a fixed-size list, it is raised when the partition's files open,
              before any of its rows and even when it has no rows in the window; for a variable-length list, at the
              first such row.
    """
    partitions = [partition for partition in plan.partitions if partition.scan_tasks]
    if len(partitions) < len(plan.partitions):
        warnings.warn(
            UnreadableTopicPartitionsWarning(
                plan.topic_id, tuple(partition for partition in plan.partitions if not partition.scan_tasks)
            ),
            stacklevel=2,
        )
    leaf_most = leaf_most_paths(projected)
    named_arrays = _named_arrays(plan)

    if len(partitions) <= 1:
        for partition in partitions:
            with _open_partition(partition, leaf_most, open_file_decoder) as opened:
                _refuse_fixed_size_named_arrays_of_another_width(opened.value_fields, named_arrays, partition)
                for batch in opened.batches():
                    yield _with_element_names(batch, named_arrays, partition)
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
        _refuse_fixed_size_named_arrays_of_another_width(rows.value_fields, named_arrays, partition)
        if rows.decode_error is not None:
            raise rows.decode_error
        for batch in rows.batches:
            yield _with_element_names(batch, named_arrays, partition)


@dataclasses.dataclass(frozen=True)
class _NamedArrayColumn:
    """Element names of one top-level named array column, and the elements the projection selects."""

    element_names: tuple[str, ...]
    """Name of every element, in element order."""

    selected: typing.Optional[tuple[str, ...]]
    """Names of the elements the projection selects, or ``None`` for every element."""


def _named_arrays(plan: ReadPlan) -> dict[str, _NamedArrayColumn]:
    """Return the top-level named arrays of the plan's schema, keyed by column name.

    A named array nested inside a struct is left out, so its column carries no element names.
    """
    if plan.schema_ is None:
        return {}
    selected = {tuple(field.path): field.elements for field in plan.projection.fields or ()}
    return {
        array.path[0]: _NamedArrayColumn(element_names=array.element_names, selected=selected.get(tuple(array.path)))
        for array in plan.schema_.named_arrays
        if len(array.path) == 1
    }


def _refuse_fixed_size_named_arrays_of_another_width(
    value_fields: collections.abc.Sequence["pyarrow.Field"],
    named_arrays: collections.abc.Mapping[str, _NamedArrayColumn],
    partition: ReadPlanPartition,
) -> None:
    """Reject a named array that a partition stores as a fixed-size list with a width other than its number of names.

    A fixed-size list's width is part of its type, so the mismatch is found when the partition's files open, before
    any row is decoded. It raises ``RobotoReadPlanExecutionException`` with kind ``ELEMENT_COUNT_MISMATCH``.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    for field in value_fields:
        named = named_arrays.get(field.name)
        if named is None or not pa.types.is_fixed_size_list(field.type):
            continue
        if field.type.list_size != len(named.element_names):
            raise RobotoReadPlanExecutionException(
                f'Topic partition {partition.topic_part_id} stores the named array "{field.name}" with '
                f"{field.type.list_size} elements in every row, but it names {len(named.element_names)}.",
                kind=ReadPlanExecutionErrorKind.ELEMENT_COUNT_MISMATCH,
                field_path=(field.name,),
            )


def _with_element_names(
    batch: "pyarrow.RecordBatch",
    named_arrays: collections.abc.Mapping[str, _NamedArrayColumn],
    partition: ReadPlanPartition,
) -> "pyarrow.RecordBatch":
    """Return ``batch`` with each named array column narrowed to its selected elements and carrying their names.

    It raises ``RobotoReadPlanExecutionException`` with kind ``ELEMENT_COUNT_MISMATCH`` when a row of a named array
    stored as a variable-length list holds a different number of elements than the array has names.
    """
    if not any(name in named_arrays for name in batch.schema.names):
        return batch
    pa = import_optional_dependency("pyarrow", "analytics")

    # The timestamp and row number columns take names no projected field has, but one of them can still have the name
    # of a named array the read leaves out, so they are skipped by position.
    marked = {timestamp_column_index(batch.schema), row_number_column_index(batch.schema)}
    fields = list(batch.schema)
    columns = list(batch.columns)
    for index, field in enumerate(fields):
        named = named_arrays.get(field.name)
        if named is None or index in marked:
            continue
        column = columns[index]
        if not pa.types.is_fixed_size_list(column.type):
            _refuse_rows_of_another_width(batch, column, field, len(named.element_names), partition)

        names = named.element_names
        if named.selected is not None:
            positions = sorted(names.index(name) for name in named.selected)
            names = tuple(names[position] for position in positions)
            column = _list_elements(column, positions)
        columns[index] = column
        fields[index] = with_element_names(field.with_type(column.type), names)
    return pa.RecordBatch.from_arrays(columns, schema=pa.schema(fields, metadata=batch.schema.metadata))


def _refuse_rows_of_another_width(
    batch: "pyarrow.RecordBatch",
    column: "pyarrow.Array",
    field: "pyarrow.Field",
    width: int,
    partition: ReadPlanPartition,
) -> None:
    """Reject the first row of the list ``column`` that holds other than ``width`` elements.

    A null row is not checked. It raises ``RobotoReadPlanExecutionException`` with kind ``ELEMENT_COUNT_MISMATCH``,
    naming the row number of that row.
    """
    pc = import_optional_dependency("pyarrow.compute", "analytics")
    lengths = pc.list_value_length(column)
    first_mismatch = pc.index(pc.not_equal(lengths, width), True).as_py()
    if first_mismatch < 0:
        return
    row_number = batch.column(row_number_column_index(batch.schema))[first_mismatch].as_py()
    raise RobotoReadPlanExecutionException(
        f"Row {row_number} of topic partition {partition.topic_part_id} holds "
        f'{lengths[first_mismatch].as_py()} elements in the named array "{field.name}", '
        f"which names {width}.",
        kind=ReadPlanExecutionErrorKind.ELEMENT_COUNT_MISMATCH,
        field_path=(field.name,),
        row_number=row_number,
    )


def _list_elements(column: "pyarrow.Array", positions: collections.abc.Sequence[int]) -> "pyarrow.Array":
    """Build a fixed-size list array of the elements at ``positions`` in each list of ``column``.

    A row is null where ``column`` is null.
    """
    np = import_optional_dependency("numpy", "analytics")
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    elements = [pc.list_element(column, position) for position in positions]
    # Interleave the per-position arrays, so the values of row r are elements[0][r], elements[1][r], ...
    interleaved = pa.concat_arrays(elements).take(
        np.arange(len(column) * len(positions)).reshape(len(positions), len(column)).T.ravel()
    )
    return pa.FixedSizeListArray.from_arrays(
        interleaved,
        type=pa.list_(column.type.value_field, len(positions)),
        mask=column.is_null() if column.null_count else None,
    )


@dataclasses.dataclass(frozen=True)
class _OpenedPartition:
    """Partition whose files are open: the fields of its value columns, and a function that decodes its rows once."""

    value_fields: list["pyarrow.Field"]
    batches: typing.Callable[[], collections.abc.Iterator["pyarrow.RecordBatch"]]


@dataclasses.dataclass(frozen=True)
class _PartitionRows:
    """Fields of a partition's value columns, known when its files open, and its decoded rows."""

    value_fields: list["pyarrow.Field"]
    batches: list["pyarrow.RecordBatch"]

    decode_error: typing.Optional[Exception] = None
    """Error that stopped decoding the partition's rows, or ``None`` when decoding finished.

    ``batches`` is empty when it is set. ``execute_read_plan`` raises it only after it checks the partition's schema."""


def _check_consistent(partition: ReadPlanPartition, file_tasks: collections.abc.Sequence[ReadPlanScanTask]) -> None:
    """Reject scan tasks on one file that disagree on how to read it.

    The error has kind ``INCONSISTENT_SCAN_TASKS_ON_FILE`` and names the first attribute of
    ``_SCAN_TASK_FILE_ATTRIBUTES`` on which any task differs from the file's first task.
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
    """Read ``partitions``, up to ``_MAX_PARTITION_WORKERS`` at once, and yield their rows in the order given."""
    # Keep up to _MAX_PARTITION_WORKERS reads running: wait on the oldest, start the next partition's read in its
    # place, then yield the oldest's rows. Waiting in submission order, not as reads complete, keeps plan order.
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
        # When a read raises or the consumer stops iterating, cancel the reads not yet started and wait for the
        # running ones, so no read outlives the generator. The exception still propagates.
        executor.shutdown(wait=True, cancel_futures=True)


@contextlib.contextmanager
def _open_partition(
    partition: ReadPlanPartition,
    leaf_most: collections.abc.Sequence[FieldPath],
    open_file_decoder: FileDecoderOpener,
) -> collections.abc.Iterator[_OpenedPartition]:
    """Open the files of a partition with a scan task, and close them when the context exits, however it exits.

    Opening raises the errors found before any row is decoded, such as those of kind
    ``PROJECTED_FIELD_IN_NO_SCAN_TASK``, ``FIELD_NOT_IN_FILE`` or ``FIELD_SPLIT_INSIDE_NON_STRUCT``; an error in the
    partition's rows is raised while decoding them.
    """
    groups = assign_scan_tasks(partition, leaf_most)
    if len(groups) == 1:
        with open_file_decoder(groups[0], partition, partition.window) as decoder:
            yield _OpenedPartition(value_fields=decoder.value_fields, batches=decoder.batches)
        return

    # A split partition: its scan tasks form more than one group, so its rows are read from more than one file.
    # Its files are opened, and later decoded, concurrently so their network waits overlap. Every decoder that opened
    # is closed however the read ends, including when another file fails to open and its exception propagates.
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

    An error opening the files propagates. Any ``Exception`` raised while decoding the rows is kept in the result,
    with the value columns known at open, so ``execute_read_plan`` checks the partition's schema before it raises the
    error.
    """
    with _open_partition(partition, leaf_most, open_file_decoder) as opened:
        try:
            batches = list(opened.batches())
        except Exception as error:
            return _PartitionRows(value_fields=opened.value_fields, batches=[], decode_error=error)
        return _PartitionRows(value_fields=opened.value_fields, batches=batches)
