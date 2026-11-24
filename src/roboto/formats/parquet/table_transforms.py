# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import math
import typing

from ...compat import import_optional_dependency
from ...time import TimeUnit
from ..fields import FieldSelection
from .timestamp import Timestamp

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


def compute_time_filter_mask(
    timestamps: "pyarrow.Array",
    start_time: typing.Optional[int] = None,
    end_time: typing.Optional[int] = None,
) -> typing.Optional["pyarrow.BooleanArray"]:
    """Build a mask that selects the rows whose timestamps fall in a time range.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    Args:
        timestamps: Each row's timestamp, in nanoseconds since the Unix epoch, as ``extract_timestamps`` returns them.
        start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
            unbounded below.
        end_time: Exclusive end of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
            unbounded above.

    Returns:
        One entry per row: true when its timestamp is in the range, and null when its timestamp is null, which
        ``pyarrow.compute.filter`` drops by default. ``None`` when both ``start_time`` and ``end_time`` are ``None``.
    """
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    if start_time is None and end_time is None:
        return None

    masks: list["pyarrow.BooleanArray"] = []
    if start_time is not None:
        masks.append(pc.greater_equal(timestamps, start_time))

    if end_time is not None:
        masks.append(pc.less(timestamps, end_time))

    if len(masks) == 1:
        return masks[0]

    return pc.and_kleene(masks[0], masks[1])


def extract_timestamps(
    table: "pyarrow.Table",
    timestamp: Timestamp,
) -> "pyarrow.Int64Array":
    """Return each row's timestamp from ``table``, converted to nanoseconds since the Unix epoch.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    The field is found by walking ``timestamp.path`` through the table's struct columns, and a row whose enclosing
    struct is null has a null timestamp. Integer, floating-point and decimal values are multiplied by the number of
    nanoseconds in their unit, and floating-point results are truncated toward zero.

    Args:
        table: Table read from the Parquet file, holding the timestamp field's column.
        timestamp: The file's timestamp field, as ``extract_timestamp_field`` returns it.

    Raises:
        TypeError: The timestamp field is not a timestamp, integer, floating-point or decimal field.
        Exception: The timestamp field is an integer, floating-point or decimal field and ``timestamp.unit_hint`` is
            ``None``.
        NotImplementedError: ``timestamp.unit_hint`` names a unit this SDK version does not support.
        pyarrow.ArrowInvalid: A timestamp, converted to nanoseconds, does not fit in a 64-bit integer.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    timestamp_values: "pyarrow.Array" = table.column(timestamp.path[0]).combine_chunks()
    if len(timestamp.path) > 1:
        timestamp_values = pc.struct_field(timestamp_values, list(timestamp.path[1:]))
    data_type = timestamp.field.type

    if pa.types.is_int64(data_type) and timestamp.unit() == TimeUnit.Nanoseconds:
        return typing.cast("pyarrow.Int64Array", timestamp_values)

    timestamps_as_ns: "pyarrow.Int64Array"
    if pa.types.is_timestamp(data_type):
        timestamps_as_ns = pc.cast(timestamp_values, pa.timestamp("ns", "UTC"))
        # Arrow stores a timestamp as a 64-bit count of its unit, so viewing it as int64 reads that count.
        # https://arrow.apache.org/docs/python/timestamps.html#arrow-pandas-timestamps
        timestamps_as_ns = typing.cast("pyarrow.Int64Array", timestamps_as_ns.view(pa.int64()))
    elif pa.types.is_floating(data_type):
        multiplier = pa.scalar(timestamp.unit().nano_multiplier())
        # PyArrow converts the integer multiplier to the values' type, and float32 cannot hold 1_000_000_000
        # exactly, so PyArrow rejects the multiplication unless the values are float64.
        timestamps_as_doubles = pc.cast(timestamp_values, pa.float64())
        scaled = pc.multiply_checked(timestamps_as_doubles, multiplier)
        timestamps_as_ns = pc.trunc(scaled).cast(pa.int64())
    elif pa.types.is_decimal(data_type):
        # A decimal product's precision is the sum of its operands' precisions plus one, and PyArrow rejects a
        # precision above 38. An int64 multiplier would be converted to decimal(19, 0), so give it the fewest
        # digits that hold it.
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


def extract_timestamp_field(
    schema: "pyarrow.Schema",
    timestamp_field: FieldSelection,
    unit_hint: typing.Optional[str],
) -> Timestamp:
    """Find a Parquet file's timestamp field and describe it as a :py:class:`~roboto.formats.parquet.Timestamp`.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    The field is found by walking its path one component at a time, first among the schema's top-level fields and
    then through struct children, so a field nested in a struct and a top-level column whose name contains dots are
    never confused.

    Args:
        schema: The file's ``ParquetFile.schema_arrow``. The timestamp's column index is counted over this schema's
            leaves, which match the file's leaf columns one for one.
        timestamp_field: Path of the timestamp field.
        unit_hint: Unit of the stored values, for a field whose Arrow type carries none; see
            :py:attr:`~roboto.formats.parquet.Timestamp.unit_hint`.

    Raises:
        KeyError: A path component is not in the schema, or names a child of a field that is not a struct.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    path = timestamp_field.path_in_schema
    root_index = schema.get_field_index(path[0])
    if root_index == -1:
        raise KeyError(f"Schema has no field '{path[0]}'")
    arrow_field = schema.field(root_index)
    column_index = sum(_leaf_column_count(schema.field(index).type) for index in range(root_index))

    for component in path[1:]:
        parent_type = arrow_field.type
        if not pa.types.is_struct(parent_type):
            raise KeyError(f"Field '{arrow_field.name}' is not a struct, so it has no child '{component}'")
        struct_type = typing.cast("pyarrow.StructType", parent_type)
        child_index = struct_type.get_field_index(component)
        if child_index == -1:
            raise KeyError(f"Struct field '{arrow_field.name}' has no child '{component}'")
        column_index += sum(_leaf_column_count(struct_type.field(index).type) for index in range(child_index))
        arrow_field = struct_type.field(child_index)

    return Timestamp(field=arrow_field, unit_hint=unit_hint, path=tuple(path), column_index=column_index)


def _leaf_column_count(arrow_type: "pyarrow.DataType") -> int:
    """Return the number of Parquet leaf columns that store a field of ``arrow_type``."""
    pa = import_optional_dependency("pyarrow", "analytics")

    if pa.types.is_struct(arrow_type):
        struct_type = typing.cast("pyarrow.StructType", arrow_type)
        return sum(_leaf_column_count(struct_type.field(index).type) for index in range(struct_type.num_fields))
    if pa.types.is_map(arrow_type):
        map_type = typing.cast("pyarrow.MapType", arrow_type)
        return _leaf_column_count(map_type.key_type) + _leaf_column_count(map_type.item_type)
    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type) or pa.types.is_fixed_size_list(arrow_type):
        list_type = typing.cast("pyarrow.ListType", arrow_type)
        return _leaf_column_count(list_type.value_type)
    if isinstance(arrow_type, pa.BaseExtensionType):
        # pa is typed as a module, so pa.BaseExtensionType is Any to a type checker and cannot narrow.
        extension_type = typing.cast("pyarrow.BaseExtensionType", arrow_type)
        return _leaf_column_count(extension_type.storage_type)
    return 1


def timestamp_statistics(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: Timestamp,
) -> typing.Optional["pyarrow.parquet.Statistics"]:
    """Return the statistics of the timestamp's column chunk in a row group, or ``None`` when there are none to use.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    The chunk is found by its position, ``timestamp.column_index``, because a field nested in a struct and a
    top-level column whose name contains dots can share a ``path_in_schema``: ``header.stamp`` names both a
    ``header`` struct's ``stamp`` field and a column of that name. The result is ``None`` when:

    - The row group has no chunk at that position.
    - That chunk's ``path_in_schema`` is not the timestamp's path joined with dots, because ``timestamp`` was found
      in another file's schema.
    - The chunk has no statistics.

    Args:
        row_group_metadata: Metadata of the row group, from ``ParquetFile.metadata.row_group``.
        timestamp: The file's timestamp field, as ``extract_timestamp_field`` returns it.
    """
    if timestamp.column_index >= row_group_metadata.num_columns:
        return None

    column_chunk = row_group_metadata.column(timestamp.column_index)
    if column_chunk.path_in_schema != ".".join(timestamp.path):
        return None

    return column_chunk.statistics


def should_read_row_group(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: Timestamp,
    start_time: typing.Optional[int] = None,
    end_time: typing.Optional[int] = None,
) -> bool:
    """Return whether a Parquet row group may hold rows in a time range, so a reader can skip one that cannot.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    It returns ``False`` only when the statistics of the row group's timestamp column show that every row is before
    ``start_time`` or after ``end_time``. Without statistics it returns ``True``, and a row group it returns ``True``
    for may still hold no rows in the range.

    Args:
        row_group_metadata: Metadata of the row group, from ``ParquetFile.metadata.row_group``.
        timestamp: The file's timestamp field, as ``extract_timestamp_field`` returns it.
        start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
            unbounded below.
        end_time: Exclusive end of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
            unbounded above.

    Raises:
        Exception: The row group has timestamp statistics, the timestamp field's Arrow type is not a timestamp type,
            and ``timestamp.unit_hint`` is ``None``.
        NotImplementedError: The timestamp field's Arrow type is not a timestamp type and ``timestamp.unit_hint``
            names a unit this SDK version does not support.
    """
    stats = timestamp_statistics(row_group_metadata, timestamp)
    if stats is None:
        return True

    pa = import_optional_dependency("pyarrow", "analytics")
    min_ns: typing.Optional[int]
    max_ns: typing.Optional[int]
    if pa.types.is_timestamp(timestamp.field.type):
        # A TIMESTAMP statistic is read as the stored integer, in the field's unit. With pandas installed, PyArrow
        # returns stats.min and stats.max as pandas.Timestamp values, which to_epoch_nanoseconds floors to the
        # microsecond; without pandas, PyArrow raises ValueError for a value that is not a whole microsecond.
        multiplier = timestamp.unit().nano_multiplier()
        min_ns = stats.min_raw * multiplier if stats.min_raw is not None else None
        max_ns = stats.max_raw * multiplier if stats.max_raw is not None else None
    else:
        min_ns = timestamp.to_epoch_nanoseconds(stats.min) if stats.min is not None else None
        max_ns = timestamp.to_epoch_nanoseconds(stats.max) if stats.max is not None else None

    if start_time is not None and max_ns is not None and start_time > max_ns:
        return False

    if end_time is not None and min_ns is not None and end_time < min_ns:
        return False

    return True


def _list_ancestor_column(
    schema: "pyarrow.Schema",
    path_in_schema: collections.abc.Sequence[str],
) -> typing.Optional[str]:
    """Return the dot-joined path of the first list ``path_in_schema`` passes through, or ``None`` when there is none.

    That path is the column name to pass to ``read_row_group(columns=...)`` for a field inside a list. The walk
    starts at the top-level field and follows structs; a list, large list or fixed-size list ends it with that list's
    path, and the leaf or any other field type ends it with ``None``. So a top-level field, or a field that is itself
    a list, returns ``None``. For example, with ``points: list<struct<x, y>>``, ``("points", "x")`` returns
    ``"points"``; with ``outer: struct<inner: list<struct<x>>>``, ``("outer", "inner", "x")`` returns
    ``"outer.inner"``; and with ``position: struct<x, y>``, ``("position", "x")`` returns ``None``.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    if len(path_in_schema) <= 1:
        return None

    current_type = schema.field(path_in_schema[0]).type
    for idx, part in enumerate(path_in_schema[1:], start=1):
        if (
            pa.types.is_list(current_type)
            or pa.types.is_large_list(current_type)
            or pa.types.is_fixed_size_list(current_type)
        ):
            return ".".join(path_in_schema[:idx])
        if pa.types.is_struct(current_type):
            current_type = current_type.field(part).type
        else:
            break
    return None


def resolve_columns(
    schema: "pyarrow.Schema",
    fields: collections.abc.Iterable[FieldSelection],
) -> list[str]:
    """Build the column names to pass to ``ParquetFile.read_row_group`` to read ``fields``, without duplicates.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    Each name is a field's path components joined with dots. PyArrow matches it as a prefix through structs, so
    ``"position.x"`` reads only the ``x`` child of a ``position`` struct. It cannot match through a list, so a field
    inside a list is read by the name of the first list its path passes through, which reads each element whole:
    for ``points: list<struct<x, y>>``, the field ``("points", "x")`` becomes ``"points"``.

    A name can match more than one field: ``"header.stamp"`` reads both a ``stamp`` field nested in a ``header``
    struct and a top-level column named ``header.stamp``. ``select_fields`` removes from the table read the fields
    that were not requested, and ``narrow_list_nested_fields`` narrows each list's elements to the requested fields.

    Args:
        schema: Arrow schema of the Parquet file, ``ParquetFile.schema_arrow``.
        fields: Fields to read.

    Returns:
        Column names, in the order of the first field that needs each.

    Raises:
        KeyError: A field's path has more than one component and names a field ``schema`` lacks, before the path
            reaches a list or a field that is not a struct.
    """
    columns: list[str] = []
    seen: set[str] = set()
    for field in fields:
        ancestor = _list_ancestor_column(schema, field.path_in_schema)
        col = ancestor if ancestor is not None else ".".join(field.path_in_schema)
        if col not in seen:
            columns.append(col)
            seen.add(col)
    return columns


def _build_subtree_trie(
    paths: collections.abc.Iterable[collections.abc.Sequence[str]],
) -> dict:
    """Merge path component sequences into a tree of nested dictionaries keyed by component.

    A node no path continues past is ``{}``, which ``_narrow_array`` reads as "keep the whole field". A path that
    ends where another continues leaves no mark, so the field is narrowed to the longer path's children; this is why
    ``narrow_list_nested_fields`` requires that no requested field lie inside another.
    """
    trie: dict = {}
    for path in paths:
        node = trie
        for component in path:
            node = node.setdefault(component, {})
    return trie


def _narrow_array(array: "pyarrow.Array", node: dict) -> "pyarrow.Array":
    """Narrow ``array`` to the fields ``node`` names, recursively.

    - An empty ``node`` keeps the whole array.
    - A struct keeps only the children ``node`` names, in the order the struct holds them, with its own null rows.
      A struct that has none of them is kept whole.
    - A path has no component for a list level: ``("points", "x")`` names the ``x`` field of every item in a
      ``points`` list. So a list's items are narrowed with the same ``node``, and the list is rebuilt with its
      offsets, or for a fixed-size list its size, and its null rows.
    - Any other type is kept as read.

    A list array must not be sliced, so that its offsets start at zero and match its ``values``.
    """
    if not node:
        return array
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")
    type_ = array.type
    if pa.types.is_struct(type_):
        struct_array = typing.cast("pyarrow.StructArray", array)
        names: list[str] = []
        children: list = []
        for index, field in enumerate(typing.cast("pyarrow.StructType", type_)):
            if field.name not in node:
                continue
            names.append(field.name)
            children.append(_narrow_array(struct_array.field(index), node[field.name]))
        if not names:
            return array
        mask = pc.is_null(array) if array.null_count else None
        return pa.StructArray.from_arrays(children, names=names, mask=mask)
    if pa.types.is_list(type_) or pa.types.is_large_list(type_):
        list_array = typing.cast("pyarrow.ListArray", array)
        narrowed_values = _narrow_array(list_array.values, node)
        from_arrays = pa.LargeListArray.from_arrays if pa.types.is_large_list(type_) else pa.ListArray.from_arrays
        if array.null_count:
            return from_arrays(list_array.offsets, narrowed_values, mask=pc.is_null(array))
        return from_arrays(list_array.offsets, narrowed_values)
    if pa.types.is_fixed_size_list(type_):
        fixed_size_list_array = typing.cast("pyarrow.FixedSizeListArray", array)
        list_size = typing.cast("pyarrow.FixedSizeListType", type_).list_size
        narrowed_values = _narrow_array(fixed_size_list_array.values, node)
        mask = pc.is_null(array) if array.null_count else None
        return pa.FixedSizeListArray.from_arrays(narrowed_values, list_size, mask=mask)
    return array


def should_narrow_list_nested_fields(
    schema: "pyarrow.Schema",
    fields: collections.abc.Iterable[FieldSelection],
) -> bool:
    """Return whether ``narrow_list_nested_fields`` would change a table read for ``fields``.

    Methods such as ``roboto.experimental.topics.Topic.get_data`` read a topic's data from Parquet files through it,
    so most code never calls it.

    It is ``True`` when some field's path passes through a list. Otherwise ``narrow_list_nested_fields`` returns
    the table unchanged, so a reader can skip it. It reads only the schema, so a reader evaluates it once per file
    rather than once per row group.

    Args:
        schema: Arrow schema of the Parquet file, ``ParquetFile.schema_arrow``.
        fields: Fields that were requested.

    Raises:
        KeyError: A field's path has more than one component and names a field ``schema`` lacks, before the path
            reaches a list or a field that is not a struct.
    """
    return any(_list_ancestor_column(schema, field.path_in_schema) is not None for field in fields)


def narrow_list_nested_fields(
    table: "pyarrow.Table",
    schema: "pyarrow.Schema",
    fields: collections.abc.Iterable[FieldSelection],
) -> "pyarrow.Table":
    """Narrow the structs inside list columns to the fields requested within them.

    Methods such as ``roboto.experimental.topics.Topic.get_data`` read a topic's data from Parquet files through it,
    so most code never calls it.

    PyArrow cannot read part of a list's elements, so ``resolve_columns`` reads a field inside a list by the list's
    column, and every element keeps all its struct fields. Each top-level column that some field's path reaches
    through a list is rebuilt without the struct fields, inside the list or not, that no requested path runs
    through; every struct keeps its remaining fields in the order the file stores them. Other columns, and a
    column the table lacks, are left as read.

    Args:
        table: Table read with the columns ``resolve_columns`` returns for ``fields``. It must not be sliced: a
            list is rebuilt from its offsets and its whole child array, which assumes the offsets start at zero.
        schema: Arrow schema of the Parquet file, ``ParquetFile.schema_arrow``.
        fields: Fields that were requested. No field may lie inside another: the outer one would be narrowed to
            the inner one rather than kept whole.

    Returns:
        ``table`` itself when no field's path passes through a list, otherwise a new table with those columns
        narrowed.

    Raises:
        KeyError: A field's path has more than one component and names a field ``schema`` lacks, before the path
            reaches a list or a field that is not a struct.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    paths_by_root: dict[str, list[tuple[str, ...]]] = {}
    roots_needing_narrowing: set[str] = set()
    for field in fields:
        path = field.path_in_schema
        if not path:
            continue
        root = path[0]
        paths_by_root.setdefault(root, []).append(path)
        if _list_ancestor_column(schema, path) is not None:
            roots_needing_narrowing.add(root)

    if not roots_needing_narrowing:
        return table

    result = table
    for root in roots_needing_narrowing:
        if root not in result.column_names:
            continue
        trie = _build_subtree_trie(path[1:] for path in paths_by_root[root])
        column = result.column(root)
        narrowed_chunks = [_narrow_array(chunk, trie) for chunk in column.chunks]
        if not narrowed_chunks:
            continue
        narrowed = pa.chunked_array(narrowed_chunks, type=narrowed_chunks[0].type)
        index = result.schema.get_field_index(root)
        result = result.set_column(index, result.schema.field(index).with_type(narrowed.type), narrowed)
    return result


_FieldTree = dict[str, typing.Optional["_FieldTree"]]
"""Field paths merged by shared prefix, keyed by path component.

A key's value is ``None`` when a path ends there, which keeps the whole field, and otherwise the tree of the paths
below it.
"""


def _field_tree(paths: collections.abc.Iterable[collections.abc.Sequence[str]]) -> _FieldTree:
    """Merge field paths into a ``_FieldTree``.

    A path that ends at a field keeps it whole, so a longer path through that field adds nothing, whichever comes
    first.
    """
    tree: _FieldTree = {}
    for path in paths:
        if not path:
            continue
        node = tree
        for component in path[:-1]:
            child = node.setdefault(component, {})
            if child is None:
                break
            node = child
        else:
            node[path[-1]] = None
    return tree


def _selected_struct_type(
    struct_type: "pyarrow.StructType",
    children: _FieldTree,
) -> typing.Optional["pyarrow.StructType"]:
    """Return the struct type holding only the children ``children`` keeps, or ``None`` when it keeps none.

    Returns ``struct_type`` itself when every child is kept.
    A child struct that ``children`` descends into is narrowed the same way;
    a child of any other type is kept as read.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    kept: list["pyarrow.Field"] = []
    removed_any = False
    for index in range(struct_type.num_fields):
        child_field = struct_type.field(index)
        if child_field.name not in children:
            removed_any = True
            continue

        grandchildren = children[child_field.name]
        child_type = child_field.type
        if grandchildren is not None and pa.types.is_struct(child_type):
            selected_type = _selected_struct_type(typing.cast("pyarrow.StructType", child_type), grandchildren)
            if selected_type is None:
                removed_any = True
                continue
            if selected_type is not child_type:
                removed_any = True
                child_field = child_field.with_type(selected_type)

        kept.append(child_field)

    if not kept:
        return None
    if not removed_any:
        return struct_type
    return typing.cast("pyarrow.StructType", pa.struct(kept))


def _select_struct_children(array: "pyarrow.StructArray", selected_type: "pyarrow.StructType") -> "pyarrow.Array":
    """Rebuild a struct array with only the children of ``selected_type``, keeping the array's null rows."""
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    if array.type.equals(selected_type):
        return array

    child_fields: list["pyarrow.Field"] = []
    child_arrays: list["pyarrow.Array"] = []
    for index in range(selected_type.num_fields):
        child_field = selected_type.field(index)
        child_array = array.field(array.type.get_field_index(child_field.name))
        if pa.types.is_struct(child_field.type):
            child_array = _select_struct_children(
                typing.cast("pyarrow.StructArray", child_array),
                typing.cast("pyarrow.StructType", child_field.type),
            )
        child_fields.append(child_field)
        child_arrays.append(child_array)

    mask = pc.is_null(array) if array.null_count else None
    return pa.StructArray.from_arrays(child_arrays, fields=child_fields, mask=mask)


def select_fields(
    table: "pyarrow.Table",
    fields: collections.abc.Iterable[FieldSelection],
) -> "pyarrow.Table":
    """Keep only the fields ``fields`` names, found by walking their path components, in the table's order.

    Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` read a topic's data from Parquet files through
    it, so most code never calls it.

    Reading columns by their dot-joined names (``resolve_columns``) can bring in more than was requested,
    such as a top-level column named ``header.stamp`` read along with a ``header`` struct's ``stamp`` field,
    or a timestamp field read only to filter rows. This removes them:

    - A top-level column that no field's path starts with is dropped.
    - A field that names a column or struct keeps it whole, even when other fields name some of its children.
    - Otherwise a struct keeps only the children that some field's path runs through, with its own null rows.
    - Lists and maps, and everything below them, are kept as read
      (``narrow_list_nested_fields`` narrows the structs inside a list).
    - A field whose path the table lacks is skipped.

    A column from which nothing is removed is returned as read.
    With no fields at all, the result has no columns and keeps the table's row count.

    Args:
        table: Table read from the Parquet file.
        fields: Fields to keep.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    tree = _field_tree(field.path_in_schema for field in fields)
    selected_fields: list["pyarrow.Field"] = []
    selected_columns: list["pyarrow.ChunkedArray"] = []
    for index, name in enumerate(table.column_names):
        if name not in tree:
            continue

        field = table.schema.field(index)
        column = table.column(index)
        children = tree[name]
        column_type = column.type
        if children is not None and pa.types.is_struct(column_type):
            struct_type = typing.cast("pyarrow.StructType", column_type)
            selected_type = _selected_struct_type(struct_type, children)
            if selected_type is None:
                continue
            if selected_type is not struct_type:
                field = field.with_type(selected_type)
                column = pa.chunked_array(
                    [
                        _select_struct_children(typing.cast("pyarrow.StructArray", chunk), selected_type)
                        for chunk in column.chunks
                    ],
                    type=selected_type,
                )

        selected_fields.append(field)
        selected_columns.append(column)

    if not selected_columns:
        return table.select([])
    return pa.Table.from_arrays(selected_columns, schema=pa.schema(selected_fields, metadata=table.schema.metadata))
