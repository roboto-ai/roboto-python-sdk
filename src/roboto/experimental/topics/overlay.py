# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Overlay a partition's scan-task streams into one nested RecordBatch.

A partition resolves to one or more scan tasks, each a representation layer
decoded into the public nested shape: a RecordBatch with a metadata-marked
``_index`` timestamp column. A row's leaf fields can be shredded across these
layers (record-shredding style), each layer owning a subtree; this module
reassembles each row by gathering every leaf from its owning layer and merging
the layers into one batch.

The model is a per-leaf positional join:

* Streams are aligned by row position, not by index value. Every representation
  of a partition is persisted in the same row order, so row ``i`` is the same
  logical message in every stream; no sort is needed and none is applied — each
  decoder emits its native (persisted) order and the merge pairs rows
  positionally. This is what lets duplicate ``_index`` timestamps overlay
  correctly: equal-timestamp rows keep their shared persisted order instead of
  being reshuffled by a per-stream sort. Every stream must carry the same rows —
  identical length and, by position, element-wise identical ``_index`` values,
  which the merge verifies as a corruption guard. A stream that is shorter,
  longer, or whose ``_index`` values diverge by position is a misalignment and
  raises; there is no fallback.
* The output leaf set and nesting come from the plan's projection. The server
  resolves the projection against the topic schema, so ``leaf_paths_per_stream``
  already enumerates the fine leaves each stream owns by subtree; the merge never
  infers a shape out of decoded batches.
* Each leaf is taken whole from its highest-precedence owning stream. Streams
  are ordered lowest-precedence first, so a narrower-subtree override wins its leaf
  while the base keeps the siblings. Struct sub-property override falls out of
  per-leaf selection; there is no per-struct merge and no cross-stream type
  unification (a higher-precedence string simply wins over a base int).
* ``null`` is a real value. A higher-precedence stream that carries a leaf as
  null wins with that null, exactly as it would with any other value.
"""

from __future__ import annotations

import collections.abc
import typing

from ...compat import import_optional_dependency
from ...domain.topics.record import FieldPath
from ...exceptions import RobotoInternalException
from .batch_transforms import (
    TIMESTAMP_FIELD_NAME,
    timestamp_column_index,
    timestamp_field,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


def _descend_to_leaf(column: "pyarrow.Array", path: FieldPath) -> typing.Any:
    """The Arrow array at ``path`` inside its root ``column``; ``None`` when the type tree lacks the path.

    ``pyarrow.compute.struct_field`` unions parent validity into the child, so a
    cell of the result is null whenever any ancestor cell is.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    array = column
    for component in path[1:]:
        if not pa.types.is_struct(array.type):
            return None
        child_index = array.type.get_field_index(component)
        if child_index < 0:
            return None
        array = pc.struct_field(array, [child_index])
    return array


def _leaf_paths_under_type(data_type: "pyarrow.DataType", prefix: FieldPath) -> list[FieldPath]:
    """Every strict-descendant leaf path of ``prefix`` through ``data_type``'s struct tree.

    A non-empty struct contributes its children's leaves recursively; a non-struct
    or empty struct has no descendant leaves and contributes nothing (its own
    presence as a whole/empty node is carried by ``prefix`` itself).
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    if not pa.types.is_struct(data_type) or data_type.num_fields == 0:
        return []
    leaves: list[FieldPath] = []
    for field in typing.cast("pyarrow.StructType", data_type):
        child = prefix + (field.name,)
        if pa.types.is_struct(field.type) and field.type.num_fields > 0:
            leaves.extend(_leaf_paths_under_type(field.type, child))
        else:
            leaves.append(child)
    return leaves


def overlay_streams(
    streams: collections.abc.Sequence[collections.abc.Sequence["pyarrow.RecordBatch"]],
    leaf_paths_per_stream: collections.abc.Sequence[collections.abc.Sequence[FieldPath]],
) -> typing.Optional["pyarrow.RecordBatch"]:
    """Merge position-aligned scan-task streams into one nested RecordBatch, last-writer-wins per leaf.

    Args:
        streams: One sequence of public-shape RecordBatches per scan task,
            ordered lowest-precedence first. Each stream must already be in
            persisted row order (its decoder's native order); the merge pairs
            rows positionally and never sorts.
        leaf_paths_per_stream: Parallel to ``streams``; each entry is the
            leaf-most projection that stream owns by subtree. A stream owns leaf
            ``L`` iff ``L`` appears in its entry, and the highest-precedence owner
            wins ``L``.

    Returns:
        The merged partition as one RecordBatch in the public nested shape with a
        metadata-marked stored-time index column, or ``None`` when every stream is
        empty (the partition emits no rows).

    Raises:
        RobotoInternalException: The streams do not share an index — their row
            counts differ, or their ``_index`` values differ element-wise by
            position.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    # Materialize one table per stream, tolerating per-batch schema drift (an
    # MCAP scan task can infer different struct child sets across flushes):
    # permissive promotion unifies them into a single schema, null-filling gaps.
    tables: list[typing.Optional["pyarrow.Table"]] = []
    lengths: list[int] = []
    for batches in streams:
        batch_list = list(batches)
        if not batch_list:
            tables.append(None)
            lengths.append(0)
            continue
        table = pa.concat_tables(
            [pa.Table.from_batches([batch]) for batch in batch_list],
            promote_options="permissive",
        ).combine_chunks()
        # No sort: every representation of a partition is persisted in the same
        # row order, so each decoder's native order already aligns row-for-row
        # across streams. Pairing positionally rather than by index value is what
        # keeps duplicate-``_index`` rows aligned — a per-stream sort would
        # reshuffle equal-index rows by each format's own tiebreak and misalign
        # them. The element-wise index check below guards a decoder that violates
        # the shared-order contract.
        tables.append(table)
        lengths.append(table.num_rows)

    if all(length == 0 for length in lengths):
        return None
    if len(set(lengths)) != 1:
        raise RobotoInternalException(
            "Overlay streams do not share an index: scan-task row counts differ "
            f"({lengths}). Position-aligned overlay requires every stream to carry the same rows."
        )

    present_tables = [table for table in tables if table is not None]

    length = lengths[0]
    index_columns: list["pyarrow.Array"] = []
    for table in present_tables:
        index_columns.append(table.column(timestamp_column_index(table.schema)).combine_chunks())
    reference_index = index_columns[0]
    for index_column in index_columns[1:]:
        if not pc.all(pc.equal(reference_index, index_column)).as_py():
            raise RobotoInternalException(
                "Overlay streams do not share an index: index (timestamp) values "
                "differ across scan tasks by row position. Position-aligned overlay "
                "requires every stream to carry the same rows."
            )

    # Authoritative fine-leaf set. For each stream and each path it owns by
    # subtree, expand the path into the data leaves it actually covers: a coarsely
    # projected struct expands into its children so a narrower-subtree override
    # patches them per leaf, while a scalar (or an owned path the stream decoded
    # nothing for) stays whole. Union lowest precedence first, then drop any path
    # that is a strict prefix of another (the struct expansion supersedes a bare
    # node a stream that elided the subtree would otherwise contribute).
    all_leaves: dict[FieldPath, None] = {}
    for index, leaf_paths in enumerate(leaf_paths_per_stream):
        table = present_tables[index]
        for owned in leaf_paths:
            root_index = table.schema.get_field_index(owned[0])
            array = _descend_to_leaf(table.column(root_index).combine_chunks(), owned) if root_index >= 0 else None
            descendants = _leaf_paths_under_type(array.type, owned) if array is not None else []
            if descendants:
                for leaf in descendants:
                    all_leaves.setdefault(leaf, None)
            else:
                all_leaves.setdefault(owned, None)
    strict_prefixes = {path[:depth] for path in all_leaves for depth in range(1, len(path))}
    all_leaves = {path: None for path in all_leaves if path not in strict_prefixes}

    out_values: dict[FieldPath, "pyarrow.Array"] = {}
    for path in all_leaves:
        leaf_column: typing.Optional["pyarrow.Array"] = None
        # Highest-precedence owner wins: a stream owns the leaf when one of its
        # subtree-restricted paths is a prefix of it. If that owner decoded nothing
        # there, the leaf is null for every row — a higher-precedence null wins.
        for index in reversed(range(len(present_tables))):
            if not any(path[: len(owned)] == owned for owned in leaf_paths_per_stream[index]):
                continue
            table = present_tables[index]
            root_index = table.schema.get_field_index(path[0])
            if root_index >= 0:
                leaf_column = _descend_to_leaf(table.column(root_index).combine_chunks(), path)
            break
        out_values[path] = leaf_column if leaf_column is not None else pa.nulls(length)

    out_roots = list(dict.fromkeys(path[0] for path in all_leaves))
    ts_name = TIMESTAMP_FIELD_NAME
    while ts_name in out_roots:
        ts_name += "_"

    arrays: list["pyarrow.Array"] = [reference_index]
    fields: list["pyarrow.Field"] = [timestamp_field(ts_name)]

    if all(len(path) == 1 for path in all_leaves):
        # Flat fast path: no struct anywhere, so skip leaf descent and struct
        # rebuild entirely — each owned top-level column is taken whole.
        for root in out_roots:
            root_column = out_values[(root,)]
            arrays.append(root_column)
            fields.append(pa.field(root, root_column.type))
        return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields))

    def build(prefix: FieldPath) -> "pyarrow.Array":
        """Reassemble the column for the subtree at ``prefix`` from its per-leaf overlays (record assembly)."""
        if prefix in out_values:
            return out_values[prefix]
        child_names = list(
            dict.fromkeys(
                path[len(prefix)] for path in all_leaves if len(path) > len(prefix) and path[: len(prefix)] == prefix
            )
        )
        children = [build(prefix + (name,)) for name in child_names]
        child_fields = [pa.field(name, child.type) for name, child in zip(child_names, children)]
        # A struct is null at a row exactly when every child is null there — the
        # rows the per-leaf overlay would emit without that subtree at all.
        mask = pc.is_null(children[0])
        for child in children[1:]:
            mask = pc.and_(mask, pc.is_null(child))
        return pa.StructArray.from_arrays(children, fields=child_fields, mask=mask)

    for root in out_roots:
        root_column = build((root,))
        arrays.append(root_column)
        fields.append(pa.field(root, root_column.type))
    return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields))
