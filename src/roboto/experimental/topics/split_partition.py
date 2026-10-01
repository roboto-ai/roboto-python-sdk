# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Combine the files of a split partition into the partition's rows.

Each combined row holds every projected top-level field, and each file gives the fields it supplies.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import functools
import typing

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
)
from .decode.common import FileDecoder

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


class SplitPartition:
    """A split partition, read through one file decoder per scan task group.

    A split partition's scan tasks, grouped by file, form more than one scan task group, so its rows are read from more
    than one file. Several scan tasks on one file are one group, read as one file. The groups, and so the file
    decoders, are ordered by the lowest precedence among their scan tasks.

    Each top-level field is made from the files' decoded columns by these rules:

    * A field one file decoded is taken whole from it.
    * A field several files decoded must be a struct in each of them, and is a struct combined from theirs. Its fields
      are the names :py:meth:`~roboto.experimental.topics.decode.FileDecoder.struct_field_names` gives for the struct
      in those files, in the order the first of them stores them, then any name that file lacks, in the next such
      file's order. A name none of those files decoded is dropped, and each other field is made by these same rules
      from the files that decoded it. The combined struct is valid in a row where any of those files has it valid.
    * A top-level name no file decoded is an empty struct, null in every row.
    """

    def __init__(
        self,
        topic_part_id: str,
        file_decoders: collections.abc.Sequence[FileDecoder],
        top_level_names: collections.abc.Sequence[str],
    ) -> None:
        """Describe how to combine ``file_decoders``, one per scan task group, in the groups' order.

        Args:
            topic_part_id: The partition's id, for error messages.
            file_decoders: One opened decoder per scan task group's file, in the groups' order.
            top_level_names: The value columns to give the read, in order: the first component of each leaf-most path.

        Raises:
            RobotoReadPlanExecutionException: With kind ``field-split-inside-non-struct``, when a field is in several
                files' decoded columns and one of them stores it as other than a struct.
        """
        self.__topic_part_id = topic_part_id
        self.__file_schemas = [topic_data_schema(decoder.value_fields) for decoder in file_decoders]
        self.__sources = [
            _field_source(
                topic_part_id,
                file_decoders,
                (name,),
                {
                    file: (position, field)
                    for file, decoder in enumerate(file_decoders)
                    for position, field in enumerate(decoder.value_fields)
                    if field.name == name
                },
            )
            for name in top_level_names
        ]

    @property
    def value_fields(self) -> list["pyarrow.Field"]:
        """The combined partition's value columns, one per top-level name, in the order given."""
        return [source.field for source in self.__sources]

    def combine(
        self, file_batches: collections.abc.Sequence[collections.abc.Sequence["pyarrow.RecordBatch"]]
    ) -> collections.abc.Iterator["pyarrow.RecordBatch"]:
        """Combine each file decoder's rows, paired in stored order, into the partition's rows.

        Row numbers and timestamps come from the file of the first scan task group. The combined batches have the
        columns of :py:func:`~roboto.experimental.topics.batch_transforms.topic_data_schema` over
        :py:attr:`value_fields`.

        Args:
            file_batches: Each file decoder's batches, in the order of the file decoders.

        Raises:
            RobotoReadPlanExecutionException: With kind ``scan-task-row-mismatch``, when the files do not hold the same
                rows: the same row numbers and timestamps in the same order. The message names the first row that
                differs, including when one file runs out of rows before another.
        """
        pa = import_optional_dependency("pyarrow", "analytics")

        tables = [
            pa.Table.from_batches(batches, schema=schema) for batches, schema in zip(file_batches, self.__file_schemas)
        ]
        row_numbers = [table.column(row_number_column_index(table.schema)).combine_chunks() for table in tables]
        timestamps = [table.column(timestamp_column_index(table.schema)).combine_chunks() for table in tables]
        for other in range(1, len(tables)):
            self.__check_same_rows(row_numbers[0], timestamps[0], row_numbers[other], timestamps[other])

        length = tables[0].num_rows
        if length == 0:
            return

        value_columns = [_value_columns(table) for table in tables]
        values = [
            _combined(source, lambda file, position: value_columns[file][position], length) for source in self.__sources
        ]
        yield pa.RecordBatch.from_arrays(
            [row_numbers[0], timestamps[0], *values], schema=topic_data_schema(self.value_fields)
        )

    def __check_same_rows(
        self,
        row_numbers: "pyarrow.Array",
        timestamps: "pyarrow.Array",
        other_row_numbers: "pyarrow.Array",
        other_timestamps: "pyarrow.Array",
    ) -> None:
        """Raise ``scan-task-row-mismatch`` unless two files hold the same rows, naming the first that differs."""
        pc = import_optional_dependency("pyarrow.compute", "analytics")

        length = min(len(row_numbers), len(other_row_numbers))
        differs = pc.or_(
            pc.not_equal(row_numbers[:length], other_row_numbers[:length]),
            pc.not_equal(timestamps[:length], other_timestamps[:length]),
        )
        first_difference = pc.index(pc.fill_null(differs, True), True).as_py()
        if first_difference < 0:
            if len(row_numbers) == len(other_row_numbers):
                return
            first_difference = length

        def row_at(file_row_numbers: "pyarrow.Array", file_timestamps: "pyarrow.Array") -> str:
            if first_difference >= len(file_row_numbers):
                return "no further row"
            return f"row {file_row_numbers[first_difference].as_py()} at {file_timestamps[first_difference].as_py()} ns"

        raise RobotoReadPlanExecutionException(
            f"The scan tasks of topic partition {self.__topic_part_id} hold different rows in the window: "
            f"{row_at(row_numbers, timestamps)} in one file where another has "
            f"{row_at(other_row_numbers, other_timestamps)}.",
            kind=ReadPlanExecutionErrorKind.SCAN_TASK_ROW_MISMATCH,
        )


@dataclasses.dataclass(frozen=True)
class _FieldSource:
    """How one output field is made from the file decoders' decoded columns."""

    field: "pyarrow.Field"

    positions: dict[int, int]
    """The field's position in each file whose decoded columns hold it, keyed by the file's index among the decoders:
    among the file's value columns for a top-level field, else among its parent's fields in that file."""

    children: typing.Optional[tuple[_FieldSource, ...]] = None
    """For a struct combined from several files, or from none, how each of its fields is made; ``None`` for a field
    taken whole from its one file."""


def _field_source(
    topic_part_id: str,
    file_decoders: collections.abc.Sequence[FileDecoder],
    path: FieldPath,
    fields: dict[int, tuple[int, "pyarrow.Field"]],
) -> _FieldSource:
    """How the field at ``path`` is made from the files whose decoded columns hold it,
    given its position and field in each.

    ``fields`` is keyed by the file's index among the file decoders, in ascending order.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    positions = {file: position for file, (position, _) in fields.items()}
    if len(fields) == 1:
        [(_, field)] = fields.values()
        return _FieldSource(field=field, positions=positions)

    structs: dict[int, "pyarrow.StructType"] = {}
    for file, (_, field) in fields.items():
        if not pa.types.is_struct(field.type):
            raise RobotoReadPlanExecutionException(
                f"The scan tasks of topic partition {topic_part_id} split the field "
                f'"{".".join(path)}", which one of its files stores as other than a struct.',
                kind=ReadPlanExecutionErrorKind.FIELD_SPLIT_INSIDE_NON_STRUCT,
            )
        structs[file] = typing.cast("pyarrow.StructType", field.type)

    names = dict.fromkeys(name for file in structs for name in file_decoders[file].struct_field_names(path) or ())
    children = []
    for name in names:
        child_fields = {
            file: (index, struct.field(index))
            for file, struct in structs.items()
            if (index := struct.get_field_index(name)) >= 0
        }
        if child_fields:
            children.append(_field_source(topic_part_id, file_decoders, (*path, name), child_fields))
    return _FieldSource(
        field=pa.field(path[-1], pa.struct([child.field for child in children])),
        positions=positions,
        children=tuple(children),
    )


def _combined(
    source: _FieldSource,
    data_at: typing.Callable[[int, int], "pyarrow.Array"],
    length: int,
) -> "pyarrow.Array":
    """The array of ``source``'s field over ``length`` rows, where ``data_at`` gives the array at a position in a file.

    A field taken from a file is null wherever that file has its parent struct null, since
    ``pyarrow.compute.struct_field`` makes a child null wherever its parent is.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    own = {file: data_at(file, position) for file, position in source.positions.items()}
    if source.children is None:
        [array] = own.values()
        return array

    valid = functools.reduce(pc.or_, (pc.is_valid(array) for array in own.values()), pa.repeat(False, length))
    if not source.children:
        # StructArray.from_arrays cannot take the length of a struct without fields from its fields.
        return pa.array([{} if is_valid else None for is_valid in valid.to_pylist()], type=pa.struct([]))

    def child_data_at(file: int, position: int) -> "pyarrow.Array":
        return pc.struct_field(own[file], [position])

    return pa.StructArray.from_arrays(
        [_combined(child, child_data_at, length) for child in source.children],
        fields=list(typing.cast("pyarrow.StructType", source.field.type)),
        mask=pc.invert(valid),
    )


def _value_columns(table: "pyarrow.Table") -> list["pyarrow.Array"]:
    """A decoded table's value columns: every column but the row number and timestamp columns, in order."""
    marked = {row_number_column_index(table.schema), timestamp_column_index(table.schema)}
    return [table.column(index).combine_chunks() for index in range(table.num_columns) if index not in marked]
