# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import decimal
import math
import typing

from ....compat import import_optional_dependency
from ....domain.topics.record import FieldPath
from ....exceptions import (
    ReadPlanExecutionErrorKind,
    RobotoReadPlanExecutionException,
)
from ....formats import FieldSelection
from ....formats.parquet import (
    Timestamp as ParquetTimestamp,
)
from ....formats.parquet import (
    extract_timestamp_field,
    narrow_list_nested_fields,
    open_parquet_file,
    resolve_columns,
    select_fields,
    should_narrow_list_nested_fields,
    timestamp_statistics,
)
from ....time import TimeUnit
from ..batch_transforms import topic_data_schema
from ..read_plan import ReadPlanPartition, TimeWindow
from .common import (
    FileDecodeParams,
    FileDecoder,
    ScanTaskGroup,
    SuppliedField,
)
from .timestamp_unit import plan_timestamp_unit

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep

CACHED_PARQUET_NAME_PATTERN = "{fs_node_id}.parquet"
"""Filename template for locally cached Parquet files; keyed on the stable file id."""

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_DECIMAL_DIGITS = 100
"""Significant digits for exact arithmetic on a stored DECIMAL timestamp: more than the 85 a 76-digit DECIMAL holds once
scaled by 10^9."""

_PathTree = dict[str, "_PathTree"]
"""Field paths merged by shared prefix: each key is a path component, mapped to the tree of the components after it.
A path that ends at a component maps it to an empty tree."""


class ParquetFileDecoder(FileDecoder):
    """Decodes one Parquet file of a partition, reading only the columns that hold its supplied fields and timestamp.

    A field the group supplies with fields excluded is expanded into its other fields when it is a struct reached
    through structs only, and so is each struct inside it that holds an excluded field. Any other field that holds an
    excluded field, such as a list or a map, is kept whole, excluded field included. A struct left with no field is
    dropped.

    A TIMESTAMP field counts in its own unit, and any other numeric field in the plan's unit, nanoseconds when the
    plan gives none. Row groups whose timestamp statistics, shifted by the partition's ``time_offset_ns``, rule the
    window out are not read. Every timestamp of a row group that is read must have a signed 64-bit nanosecond value
    once shifted, whether or not the window keeps its row.
    """

    def __init__(
        self,
        group: ScanTaskGroup,
        partition: ReadPlanPartition,
        window: TimeWindow,
        params: FileDecodeParams,
    ) -> None:
        """Open the file and read its schema.

        Args:
            group: The scan tasks that read the file, and the fields they supply.
            partition: The partition the file belongs to.
            window: The plan's absolute window, both ends included.
            params: How to reach the file and whether to cache it.

        Raises:
            RobotoReadPlanExecutionException: With kind ``unsupported-timestamp`` for a timestamp that is not a schema
                field, a timestamp field with no path, a plan unit other than s, ms, us or ns,
                or a timestamp field inside a list or map, holding a date or time of day, or not a number;
                ``field-not-in-file`` for a supplied field or the timestamp field that the file lacks.
        """
        self.__partition = partition
        self.__window = window
        timestamp_path = _timestamp_field_path(partition)
        unit = plan_timestamp_unit(partition) or TimeUnit.Nanoseconds

        fs_node_id = group.object.fs_node_id
        supplied_paths = list(dict.fromkeys(supplied.path for supplied in group.supplies))
        # The read also fetches the timestamp field, which adds a column unless it is one of the supplied paths.
        estimated_column_count = len(supplied_paths) + (0 if timestamp_path in supplied_paths else 1)
        self.__file = open_parquet_file(
            url_provider=lambda: params.signed_url_resolver(fs_node_id),
            cache_outfile=params.cache_dir / CACHED_PARQUET_NAME_PATTERN.format(fs_node_id=fs_node_id),
            policy=params.cache_policy,
            estimated_column_count=estimated_column_count,
            size_bytes=group.object.size_bytes,
        )
        self.__closed = False
        try:
            # schema_arrow is a pyarrow property that rebuilds a wrapper on each access, so it is read once.
            self.__schema = self.__file.schema_arrow
            missing = _first_missing_field(self.__schema, supplied_paths, timestamp_path)
            if missing is not None:
                raise RobotoReadPlanExecutionException(
                    f"The Parquet file of topic partition {partition.topic_part_id} "
                    f'has no field "{".".join(missing)}".',
                    kind=ReadPlanExecutionErrorKind.FIELD_NOT_IN_FILE,
                    field_path=missing,
                )
            self.__timestamp = _timestamp_field(self.__schema, timestamp_path, unit, partition)

            self.__selections = [
                FieldSelection(path_in_schema=path) for path in _included_paths(self.__schema, group.supplies)
            ]
            self.__columns = resolve_columns(
                self.__schema, [*self.__selections, FieldSelection(path_in_schema=timestamp_path)]
            )
            # PyArrow narrows struct and scalar fields as it selects columns; a field inside a list needs a pass
            # after each row group is read.
            self.__narrows_lists = should_narrow_list_nested_fields(self.__schema, self.__selections)
            self.__value_fields = sorted(
                self.__value_table(self.__schema.empty_table()).schema, key=lambda field: field.name
            )
        except BaseException:
            self.close()
            raise

    @property
    def value_fields(self) -> list["pyarrow.Field"]:
        return list(self.__value_fields)

    def batches(self) -> collections.abc.Iterator["pyarrow.RecordBatch"]:
        np = import_optional_dependency("numpy", "analytics")
        pa = import_optional_dependency("pyarrow", "analytics")
        pc = import_optional_dependency("pyarrow.compute", "analytics")

        start = self.__window.start
        end = self.__window.end
        offset = self.__partition.time_offset_ns
        schema = topic_data_schema(self.__value_fields)
        value_names = [field.name for field in self.__value_fields]
        # metadata is a pyarrow property that rebuilds a wrapper on each access, so it is read once.
        file_metadata = self.__file.metadata
        row_group_end = 0
        for row_group_index in range(file_metadata.num_row_groups):
            row_group_metadata = file_metadata.row_group(row_group_index)
            first_row_number = row_group_end
            row_group_end += row_group_metadata.num_rows
            if not _row_group_may_hold_window(row_group_metadata, self.__timestamp, start, end, offset):
                continue

            table = self.__file.read_row_group(row_group_index, columns=self.__columns)
            # Read before the value columns are narrowed, which drops a timestamp nested in a struct when no supplied
            # field holds it.
            timestamps = self.__absolute_timestamps(table, first_row_number)
            row_numbers = pa.array(np.arange(first_row_number, row_group_end, dtype=np.uint64), type=pa.uint64())
            values = self.__value_table(table).select(value_names)

            # When statistics prove every timestamp non-null and in the window, the mask would keep every row.
            if not _row_group_fully_in_window(row_group_metadata, self.__timestamp, start, end, offset):
                # A null timestamp gives a null mask entry, and filtering drops a row whose entry is null.
                mask = pc.and_kleene(pc.greater_equal(timestamps, start), pc.less_equal(timestamps, end))
                values = values.filter(mask)
                timestamps = timestamps.filter(mask)
                row_numbers = row_numbers.filter(mask)
            if values.num_rows == 0:
                continue

            table = pa.Table.from_arrays([row_numbers, timestamps, *values.columns], schema=schema)
            yield from table.combine_chunks().to_batches()

    def close(self) -> None:
        if self.__closed:
            return
        self.__closed = True
        # force=True also closes a source that was already open when the file was given it, such as an HTTP stream.
        self.__file.close(force=True)

    def struct_field_names(self, path: FieldPath) -> typing.Optional[list[str]]:
        struct_type = _struct_at(self.__schema, path)
        return None if struct_type is None else [field.name for field in struct_type]

    def __absolute_timestamp(self, stored: typing.Any, row_number: int) -> int:
        """One stored timestamp in nanoseconds, shifted by the partition's ``time_offset_ns``.

        Computed exactly for an integer or DECIMAL value, and truncated toward zero for a floating-point value.
        """
        unit = self.__timestamp.unit()
        multiplier = unit.nano_multiplier()
        offset = self.__partition.time_offset_ns
        field_name = ".".join(self.__timestamp.path)
        nanoseconds: typing.Optional[int]
        if isinstance(stored, decimal.Decimal):
            with decimal.localcontext() as context:
                context.prec = _DECIMAL_DIGITS
                scaled = stored * multiplier
                if scaled != scaled.to_integral_value():
                    scale = typing.cast("pyarrow.Decimal128Type", self.__timestamp.field.type).scale
                    raise self.__invalid_timestamp(
                        row_number,
                        f'{int(stored.scaleb(scale))} × 10^-{scale} {unit} of "{field_name}" '
                        "is not a whole number of nanoseconds",
                    )
                nanoseconds = int(scaled)
        elif isinstance(stored, int):
            nanoseconds = stored * multiplier
        else:
            # A floating-point value, scaled and truncated as _stored_nanoseconds does it.
            scaled_float = float(stored) * multiplier
            nanoseconds = math.trunc(scaled_float) if math.isfinite(scaled_float) else None

        if nanoseconds is None or not _INT64_MIN <= nanoseconds + offset <= _INT64_MAX:
            raise self.__invalid_timestamp(
                row_number,
                f'{stored} {unit} of "{field_name}", shifted by {offset} ns, is not a signed 64-bit nanosecond value',
            )
        return nanoseconds + offset

    def __absolute_timestamps(self, table: "pyarrow.Table", first_row_number: int) -> "pyarrow.Int64Array":
        """The row group's timestamps in nanoseconds, shifted by the partition's ``time_offset_ns``.

        Raises:
            RobotoReadPlanExecutionException: With kind ``invalid-timestamp`` for the first row whose timestamp is
                NaN or infinite, a DECIMAL holding a fraction of a nanosecond, or outside signed 64 bits once shifted.
        """
        pa = import_optional_dependency("pyarrow", "analytics")
        pc = import_optional_dependency("pyarrow.compute", "analytics")

        path = self.__timestamp.path
        stored = table.column(path[0]).combine_chunks()
        if len(path) > 1:
            stored = pc.struct_field(stored, list(path[1:]))
        try:
            return pc.add_checked(
                _stored_nanoseconds(stored, self.__timestamp),
                pa.scalar(self.__partition.time_offset_ns, pa.int64()),
            )
        except pa.ArrowInvalid:
            # Some row's value has no signed 64-bit nanosecond value before the offset is added or after, or the column
            # is a DECIMAL too wide to scale. Converting each row on its own decides whether its shifted value has one,
            # and which row is the first that does not.
            if pa.types.is_timestamp(stored.type):
                stored = stored.view(pa.int64())
            return pa.array(
                [
                    None if value is None else self.__absolute_timestamp(value, first_row_number + index)
                    for index, value in enumerate(stored.to_pylist())
                ],
                type=pa.int64(),
            )

    def __invalid_timestamp(self, row_number: int, detail: str) -> RobotoReadPlanExecutionException:
        return RobotoReadPlanExecutionException(
            f"The timestamp of row {row_number} of topic partition {self.__partition.topic_part_id} is invalid: "
            f"{detail}",
            kind=ReadPlanExecutionErrorKind.INVALID_TIMESTAMP,
            row_number=row_number,
        )

    def __value_table(self, table: "pyarrow.Table") -> "pyarrow.Table":
        """The table's columns narrowed to the fields the file supplies, in the table's order."""
        if self.__narrows_lists:
            table = narrow_list_nested_fields(table, self.__schema, self.__selections)
        return select_fields(table, self.__selections)


def _row_group_fully_in_window(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: ParquetTimestamp,
    start: int,
    end: int,
    offset: int,
) -> bool:
    """Return whether the timestamp statistics prove every row's timestamp non-null and in the inclusive window.

    Args:
        row_group_metadata: The row group's metadata.
        timestamp: The timestamp field, whose :py:meth:`~roboto.formats.parquet.Timestamp.unit` its values count in.
        start: The window's first nanosecond.
        end: The window's last nanosecond.
        offset: Nanoseconds added to every stored timestamp before it is compared with the window.

    Returns:
        ``False`` when a statistic is absent, or its value shifted by ``offset`` is outside signed 64 bits.
    """
    statistics = timestamp_statistics(row_group_metadata, timestamp)
    if statistics is None:
        return False
    # pyarrow's type stubs omit Statistics.has_null_count (present at runtime); read it dynamically.
    has_null_count: bool = getattr(statistics, "has_null_count")
    if not has_null_count or statistics.null_count != 0:
        return False
    minimum, maximum = _shifted_bounds(statistics, timestamp, offset)
    return minimum is not None and maximum is not None and start <= minimum and maximum <= end


def _row_group_may_hold_window(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: ParquetTimestamp,
    start: int,
    end: int,
    offset: int,
) -> bool:
    """Return whether a row of the row group can have its timestamp in the inclusive window.

    Takes the same arguments as :py:func:`_row_group_fully_in_window`.

    Returns:
        ``False`` only when the timestamp statistics, shifted by ``offset``, lie in signed 64 bits and rule the window
        out.
    """
    statistics = timestamp_statistics(row_group_metadata, timestamp)
    if statistics is None:
        return True
    minimum, maximum = _shifted_bounds(statistics, timestamp, offset)
    if minimum is None or maximum is None:
        return True
    return minimum <= end and start <= maximum


def _shifted_bounds(
    statistics: "pyarrow.parquet.Statistics",
    timestamp: ParquetTimestamp,
    offset: int,
) -> tuple[typing.Optional[int], typing.Optional[int]]:
    """The minimum and maximum statistics in nanoseconds, shifted by ``offset``.

    A bound is ``None`` when the statistic is absent or not a number, or when its shifted value is outside signed
    64 bits. A floating-point or DECIMAL bound is truncated toward zero, and the truncated bounds still bound the row
    group's timestamps as read: truncation keeps order, a floating-point timestamp is read truncated toward zero too,
    and a DECIMAL timestamp that is read is a whole number of nanoseconds, which truncation leaves unchanged.
    """
    if not statistics.has_min_max:
        return None, None
    pa = import_optional_dependency("pyarrow", "analytics")

    # A TIMESTAMP statistic is read as the stored integer: pyarrow converts it to a datetime otherwise, which fails
    # for a value outside the range a datetime holds.
    if pa.types.is_timestamp(timestamp.field.type):
        stored_bounds = (statistics.min_raw, statistics.max_raw)
    else:
        stored_bounds = (statistics.min, statistics.max)
    multiplier = timestamp.unit().nano_multiplier()

    def shifted(stored: typing.Any) -> typing.Optional[int]:
        nanoseconds: typing.Optional[int] = None
        if isinstance(stored, int):
            nanoseconds = stored * multiplier
        elif isinstance(stored, float):
            scaled = stored * multiplier
            nanoseconds = math.trunc(scaled) if math.isfinite(scaled) else None
        elif isinstance(stored, decimal.Decimal):
            with decimal.localcontext() as context:
                context.prec = _DECIMAL_DIGITS
                nanoseconds = int(stored * multiplier)
        if nanoseconds is None or not _INT64_MIN <= nanoseconds + offset <= _INT64_MAX:
            return None
        return nanoseconds + offset

    return shifted(stored_bounds[0]), shifted(stored_bounds[1])


def _stored_nanoseconds(stored: "pyarrow.Array", timestamp: ParquetTimestamp) -> "pyarrow.Int64Array":
    """The stored timestamps in nanoseconds, before any offset.

    Raises:
        pyarrow.ArrowInvalid: A value is NaN or infinite, is a DECIMAL holding a fraction of a nanosecond, or is
            outside signed 64 bits once in nanoseconds; or the column is a DECIMAL too wide to scale.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    data_type = stored.type
    multiplier = timestamp.unit().nano_multiplier()
    if pa.types.is_floating(data_type):
        scaled = pc.trunc(pc.multiply(pc.cast(stored, pa.float64()), float(multiplier)))
        # The cast is safe by default, so it refuses NaN, infinities and values outside signed 64 bits.
        return pc.cast(scaled, pa.int64())
    if pa.types.is_decimal(data_type):
        # Arrow gives a product the sum of its factors' precisions plus one, and refuses a product wider than the
        # column's type holds (38 digits for decimal128, 76 for decimal256), so the multiplier gets the narrowest
        # decimal type that holds it. Casting the product to an integer refuses a fraction.
        decimal_multiplier = pa.scalar(multiplier, pa.decimal128(len(str(multiplier)), 0))
        return pc.cast(pc.multiply_checked(stored, decimal_multiplier), pa.int64())
    integers = stored.view(pa.int64()) if pa.types.is_timestamp(data_type) else pc.cast(stored, pa.int64())
    return pc.multiply_checked(integers, multiplier)


def _timestamp_field_path(partition: ReadPlanPartition) -> FieldPath:
    """The path of the partition's timestamp field.

    Raises:
        RobotoReadPlanExecutionException: With kind ``unsupported-timestamp`` for a kind other than a schema field,
            such as a message time, which a Parquet file does not store, or for a field without a path.
    """
    timestamp = partition.timestamp

    def unsupported(reason: str) -> RobotoReadPlanExecutionException:
        return RobotoReadPlanExecutionException(
            f"Topic partition {partition.topic_part_id} is read from Parquet, and its timestamp {reason}.",
            kind=ReadPlanExecutionErrorKind.UNSUPPORTED_TIMESTAMP,
        )

    if timestamp.kind != "schema_field":
        raise unsupported(f'kind "{timestamp.kind}" is not a schema field, the only timestamp a Parquet file stores')
    if timestamp.field is None or not timestamp.field.path:
        raise unsupported("field has no declared path")
    return timestamp.field.path


def _timestamp_field(
    schema: "pyarrow.Schema",
    path: FieldPath,
    unit: TimeUnit,
    partition: ReadPlanPartition,
) -> ParquetTimestamp:
    """The timestamp field at ``path``, which the file has, counting in its own unit when it is a TIMESTAMP and in
    ``unit`` otherwise.

    Raises:
        RobotoReadPlanExecutionException: With kind ``unsupported-timestamp`` for a field inside a list or map,
            one that is not a single value, one holding a date or time of day, or one that is not a number.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    def unsupported(reason: str) -> RobotoReadPlanExecutionException:
        return RobotoReadPlanExecutionException(
            f'The timestamp field "{".".join(path)}" of topic partition {partition.topic_part_id} {reason}.',
            kind=ReadPlanExecutionErrorKind.UNSUPPORTED_TIMESTAMP,
        )

    field = schema.field(schema.get_field_index(path[0]))
    for name in path[1:]:
        if not pa.types.is_struct(field.type):
            raise unsupported("is inside a list or map, so it has no single value per row")
        struct_type = typing.cast("pyarrow.StructType", field.type)
        field = struct_type.field(struct_type.get_field_index(name))

    data_type = field.type
    if pa.types.is_nested(data_type):
        raise unsupported("is not a single number per row")
    if pa.types.is_date(data_type) or pa.types.is_time(data_type):
        raise unsupported("holds a date or a time of day rather than an instant in time")
    if not (
        pa.types.is_integer(data_type)
        or pa.types.is_floating(data_type)
        or pa.types.is_decimal(data_type)
        or pa.types.is_timestamp(data_type)
    ):
        raise unsupported(f"is stored as {data_type}, which is not a number")
    return extract_timestamp_field(schema, FieldSelection(path_in_schema=path), unit_hint=unit.value)


def _included_paths(schema: "pyarrow.Schema", supplies: collections.abc.Sequence[SuppliedField]) -> list[FieldPath]:
    """The paths of the fields the file reads for ``supplies``, none inside another, sorted.

    A supplied field with fields excluded is replaced by its other fields, found through structs only.
    """
    paths = [path for supplied in supplies for path in _supplied_paths(schema, supplied)]
    root_most: list[FieldPath] = []
    # Sorted, the paths inside a path come right after it, so each is compared with the last path kept.
    for path in sorted(set(paths)):
        if root_most and path[: len(root_most[-1])] == root_most[-1]:
            continue
        root_most.append(path)
    return root_most


def _supplied_paths(schema: "pyarrow.Schema", supplied: SuppliedField) -> list[FieldPath]:
    """The paths that together hold the supplied field less its excluded fields."""
    struct_type = _struct_at(schema, supplied.path) if supplied.excluded else None
    if struct_type is None:
        return [supplied.path]
    return _fields_less_excluded(struct_type, supplied.path, supplied.excluded)


def _fields_less_excluded(
    struct_type: "pyarrow.StructType",
    path: FieldPath,
    excluded: collections.abc.Sequence[FieldPath],
) -> list[FieldPath]:
    """The paths of the fields of the struct at ``path`` less those at ``excluded``, each strictly inside ``path``.

    A field holding an excluded field is expanded the same way when it is a struct, and kept whole otherwise.
    A struct left with no field contributes no path.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    depth = len(path)
    paths: list[FieldPath] = []
    for field in struct_type:
        field_path = (*path, field.name)
        inside = [other for other in excluded if other[depth] == field.name]
        if any(len(other) == depth + 1 for other in inside):
            continue
        if inside and pa.types.is_struct(field.type):
            paths.extend(_fields_less_excluded(typing.cast("pyarrow.StructType", field.type), field_path, inside))
        else:
            paths.append(field_path)
    return paths


def _struct_at(schema: "pyarrow.Schema", path: FieldPath) -> typing.Optional["pyarrow.StructType"]:
    """The struct type at ``path``, reached through structs from a top-level field; ``None`` when there is none."""
    pa = import_optional_dependency("pyarrow", "analytics")

    fields: typing.Union["pyarrow.Schema", "pyarrow.StructType"] = schema
    struct_type: typing.Optional["pyarrow.StructType"] = None
    for name in path:
        index = fields.get_field_index(name)
        if index < 0:
            return None
        field_type = fields.field(index).type
        if not pa.types.is_struct(field_type):
            return None
        struct_type = typing.cast("pyarrow.StructType", field_type)
        fields = struct_type
    return struct_type


def _first_missing_field(
    schema: "pyarrow.Schema",
    value_paths: collections.abc.Sequence[FieldPath],
    timestamp_path: FieldPath,
) -> typing.Optional[FieldPath]:
    """The first of ``value_paths`` and ``timestamp_path`` that a file with Arrow schema ``schema`` lacks,
    cut after its first component the file lacks. ``None`` when the file holds them all.

    Each path's first component names a top-level field. The fields are checked in this order:

    1. The top-level fields: those of ``value_paths`` in order, then the timestamp's.
    2. The fields below each top-level field of ``value_paths``, in order, as :py:func:`_first_missing_below` orders
       them.
    3. The fields below the timestamp's top-level field.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    top_level = pa.struct(schema)
    for name in dict.fromkeys([*(path[0] for path in value_paths), timestamp_path[0]]):
        if top_level.get_field_index(name) < 0:
            return (name,)

    for paths, crosses_lists in ((value_paths, True), ([timestamp_path], False)):
        for name, below in _path_tree(paths).items():
            missing = _first_missing_below(top_level.field(name).type, below, (name,), crosses_lists=crosses_lists)
            if missing is not None:
                return missing
    return None


def _first_missing_below(
    data_type: "pyarrow.DataType",
    tree: _PathTree,
    path: FieldPath,
    *,
    crosses_lists: bool,
) -> typing.Optional[FieldPath]:
    """The first path of ``tree`` that the field at ``path``, of Arrow type ``data_type``, lacks below it,
    cut after its first missing component. ``None`` when the field holds them all.

    Each component names a field of the struct reached so far. At a struct, every field ``tree`` names is checked
    before anything below them, then the fields below each, in the order the file stores the struct's fields.
    With ``crosses_lists``, a list is crossed to its items without using a component, as a read plan names the fields
    of a list's items. Nothing below a map is checked, since the read keeps a map whole, nor below a list that is not
    crossed. A timestamp path that runs through a list or map therefore passes this check, and is refused as a
    timestamp field inside a list or map.
    Below a field of any other type, the first component ``tree`` names is one the file lacks.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    def is_list(arrow_type: "pyarrow.DataType") -> bool:
        return (
            pa.types.is_list(arrow_type)
            or pa.types.is_large_list(arrow_type)
            or pa.types.is_fixed_size_list(arrow_type)
        )

    while crosses_lists and is_list(data_type):
        data_type = typing.cast("pyarrow.ListType", data_type).value_type
    if not tree or pa.types.is_map(data_type) or is_list(data_type):
        return None
    if not pa.types.is_struct(data_type):
        return (*path, next(iter(tree)))

    struct_type = typing.cast("pyarrow.StructType", data_type)
    for name in tree:
        if struct_type.get_field_index(name) < 0:
            return (*path, name)
    for field in struct_type:
        if field.name not in tree:
            continue
        missing = _first_missing_below(field.type, tree[field.name], (*path, field.name), crosses_lists=crosses_lists)
        if missing is not None:
            return missing
    return None


def _path_tree(paths: collections.abc.Iterable[FieldPath]) -> _PathTree:
    """Merge ``paths`` by shared prefix, keeping each level's names in the order the paths first name them."""
    tree: _PathTree = {}
    for path in paths:
        node = tree
        for name in path:
            node = node.setdefault(name, {})
    return tree
