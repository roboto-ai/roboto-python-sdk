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
    Extract timestamps in nanoseconds since Unix epoch from the table's timestamp field.

    The field is found by walking ``timestamp.path`` through the table's struct columns.
    A row whose enclosing struct is null has a null timestamp.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    timestamp_values: "pyarrow.Array" = table.column(timestamp.path[0]).combine_chunks()
    if len(timestamp.path) > 1:
        timestamp_values = pc.struct_field(timestamp_values, list(timestamp.path[1:]))
    data_type = timestamp.field.type

    # Short-circuit if the timestamp field column is already in target format/unit
    if pa.types.is_int64(data_type) and timestamp.unit() == TimeUnit.Nanoseconds:
        return typing.cast("pyarrow.Int64Array", timestamp_values)

    # Derive nanoseconds since unix epoch as int64 from the timestamp field column
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


def extract_timestamp_field(
    schema: "pyarrow.Schema",
    timestamp_field: FieldSelection,
    unit_hint: typing.Optional[str],
) -> Timestamp:
    """Find a Parquet file's timestamp field and describe it as a :py:class:`Timestamp`.

    The field is found by walking ``timestamp_field.path_in_schema`` one component at a time,
    first among the schema's top-level fields and then through struct children,
    so a nested field and a top-level column whose name contains dots are never confused.
    ``schema`` must be the file's ``ParquetFile.schema_arrow``:
    the timestamp's column index is counted over the schema's leaves, which match the file's leaf columns one for one.

    ``unit_hint`` is the unit of the stored values, used when the field's Arrow type does not carry one
    (an integer, floating-point or decimal field). Callers take it from the ``Unit`` metadata
    of the timestamp's :py:class:`~roboto.domain.topics.MessagePathRecord`,
    or from :py:attr:`~roboto.experimental.topics.ReadPlanTimestamp.unit`.

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
    """The number of Parquet leaf columns that store a field of ``arrow_type``."""
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
        # ``pa`` is typed as a module, so ``pa.BaseExtensionType`` is ``Any`` to a type checker and cannot narrow.
        extension_type = typing.cast("pyarrow.BaseExtensionType", arrow_type)
        return _leaf_column_count(extension_type.storage_type)
    return 1


def timestamp_statistics(
    row_group_metadata: "pyarrow.parquet.RowGroupMetaData",
    timestamp: Timestamp,
) -> typing.Optional["pyarrow.parquet.Statistics"]:
    """The statistics of the timestamp's column chunk in a row group, or ``None`` when there are none to use.

    A nested field and a top-level column whose name contains dots can share a column chunk's ``path_in_schema``
    (``header.stamp`` names both a ``header`` struct's ``stamp`` field and a column of that name),
    so the chunk is found by its position, ``timestamp.column_index``.
    Returns ``None`` when the row group has no chunk at that index,
    when that chunk's ``path_in_schema`` is not the timestamp's path joined with dots
    (``timestamp`` was found in a schema other than this file's), or when the chunk has no statistics.
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
    """
    Determine whether a Parquet row group contains data within the requested time range.
    Used to short-circuit requesting column chunks from the given row group if not relevant.
    """
    stats = timestamp_statistics(row_group_metadata, timestamp)
    if stats is None:
        # The row group has no column chunk at the timestamp's index and path, or that chunk has no statistics,
        # so only reading the row group can tell whether it holds rows in the window.
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


def _list_ancestor_column(
    schema: "pyarrow.Schema",
    path_in_schema: collections.abc.Sequence[str],
) -> typing.Optional[str]:
    """Return the column path of the nearest list ancestor, or ``None``.

    Walks *path_in_schema* through the Arrow *schema*, checking each intermediate
    field.  If any intermediate field is a list (or large or fixed-size list) type, returns the
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
    """Build a deduplicated list of column names safe for ``read_row_group(columns=...)``.

    Children of list-type columns are replaced by their list ancestor's column name
    because PyArrow's prefix-based nested column selection does not work through list
    wrapper nodes in the physical Parquet schema.  Selecting the parent list column
    already returns its full nested structure.

    This is important because the projected fields contain only *leaf* paths.  For a
    column like ``points: list<struct<x, y>>``, only ``points.x`` and ``points.y`` are
    selected — the parent ``points`` field is absent.  This function derives the correct
    parent column name from the child's ``path_in_schema``.

    Children of struct-type columns are preserved because PyArrow can resolve them via
    dot-separated prefix matching (e.g. ``"position.x"`` selects the ``x`` child of
    the ``position`` struct).

    Each name joins path components with dots, the form in which ``read_row_group`` takes columns.
    Two fields whose paths join to the same name are both selected by it:
    ``"header.stamp"`` selects both a ``stamp`` field nested in a ``header`` struct and a top-level column of that name.
    :py:func:`select_fields` removes the fields that were not projected.
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
    """Merge root-relative component sequences into a nested ``dict`` trie.

    Each path's components become a chain of ``dict`` keys; a path that ends at a
    node leaves it ``{}``, marking "keep this whole subtree", unless another path
    continues past that node; see :py:func:`narrow_list_nested_fields`.
    """
    trie: dict = {}
    for path in paths:
        node = trie
        for component in path:
            node = node.setdefault(component, {})
    return trie


def _narrow_array(array: "pyarrow.Array", node: dict) -> "pyarrow.Array":
    """Recursively narrow one Arrow array against a subtree trie *node*.

    An empty *node* keeps the whole subtree (returns the array untouched).
    For a struct, the array is rebuilt keeping only the children named in *node*, in the order the struct holds them
    (reapplying the struct null mask); a name absent from the struct type is skipped.
    A path has no component for a list level:
    ``("points", "x")`` names the ``x`` field of every item in a ``points`` list.
    So a list is narrowed by recursing into ``array.values`` with the same *node*,
    then rebuilt with the original offsets (or, for a fixed-size list, its list size) and the list null mask.
    Any other type is returned as-is.

    Callers MUST pass freshly-read, non-sliced arrays whose list offsets start at
    zero, so ``ListArray.values`` aligns with ``ListArray.offsets``.
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
    """Return whether :py:func:`narrow_list_nested_fields` would change the table.

    True iff at least one projected field addresses a leaf *inside* a list (its
    path has a list ancestor). When False, every projected field resolves through
    structs and scalars alone, so PyArrow's column selection already returns the
    narrowed shape and the post-read prune is a no-op — callers can skip it.

    Cheap enough to evaluate once per file and hoist the per-row-group narrowing
    decision out of the decode loop.
    """
    return any(_list_ancestor_column(schema, field.path_in_schema) is not None for field in fields)


def narrow_list_nested_fields(
    table: "pyarrow.Table",
    schema: "pyarrow.Schema",
    fields: collections.abc.Iterable[FieldSelection],
) -> "pyarrow.Table":
    """Prune list-of-struct columns to the projected leaves inside each element.

    PyArrow's prefix-based nested column selection cannot reach through list
    wrapper nodes, so :py:func:`resolve_columns` reads a list-nested leaf's whole
    list ancestor column — every element keeps all of its struct fields. This
    Arrow-native post-read pass narrows each such element down to the requested
    leaves, leaving every other read path byte-identical.

    A top-level root is narrowed iff at least one of its projected paths has a
    list ancestor; otherwise the table is returned unchanged (pure struct, scalar,
    and scalar-list reads never enter the rebuild). Per root, a trie is built from
    its paths with the root component stripped so non-list-nested siblings the
    projection also keeps are preserved. Every struct keeps its fields in the
    order the file stores them.

    No field of ``fields`` may lie inside another: the outer one would be
    narrowed to the inner one rather than kept whole.
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
"""Field paths merged by shared prefix: each key is a path component,
and its value is ``None`` when a path ends there (the whole field is kept) or the tree of the paths below it."""


def _field_tree(paths: collections.abc.Iterable[collections.abc.Sequence[str]]) -> _FieldTree:
    """Merge field paths into a :py:data:`_FieldTree`. A path that ends at a field keeps it whole,
    so a longer path through that field adds nothing."""
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
    """The struct type holding only the children that ``children`` names, or ``None`` when it names none of them.

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

    Reading columns by their dot-joined names (:py:func:`resolve_columns`) can bring in more than was projected,
    such as a top-level column named ``header.stamp`` read along with a ``header`` struct's ``stamp`` field,
    or a timestamp field read only to filter rows. This removes them:

    - A top-level column that no field's path starts with is dropped.
    - A field that names a column or struct keeps it whole, even when other fields name some of its children.
    - Otherwise a struct keeps only the children that some field's path runs through, with its own null rows.
    - Lists and maps, and everything below them, are kept as read
      (:py:func:`narrow_list_nested_fields` narrows the structs inside a list).
    - A field whose path the table lacks is skipped.

    A column from which nothing is removed is returned as read.
    With no fields at all, the result has no columns and keeps the table's row count.
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
