# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Representation conversion for topic-data RecordBatches.

Topic data moves through the read path as Arrow RecordBatches in its public shape:
one column per top-level projected field, with struct/list types mirroring the schema tree,
plus one dedicated timestamp column of absolute Unix-epoch nanoseconds (``int64``) marked by field metadata
(:py:data:`TIMESTAMP_FIELD_METADATA_KEY`).

This module owns the conversions into and out of that shape:

* decoded message rows -> a nested RecordBatch (:py:func:`rows_to_batch`).
* a nested table -> dot-delimited leaf columns
  (:py:func:`flatten_table`), the DataFrame packing shape behind
  ``Topic.get_data_as_df(flatten=True)``. A null at any struct level
  propagates to nulls in every leaf column beneath it.

It also exposes the helpers that locate and construct the timestamp column
(:py:func:`timestamp_column_index`, :py:func:`timestamp_field`), which the
decode path uses to mark and find that column by metadata rather than name.
"""

from __future__ import annotations

import collections.abc
import typing

from ...compat import import_optional_dependency
from ...exceptions import (
    RobotoInternalException,
    RobotoInvalidRequestException,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

TIMESTAMP_FIELD_METADATA_KEY = b"roboto.topic_data.timestamp"
"""Arrow field-metadata key marking the per-row timestamp column of a topic-data batch."""

TIMESTAMP_FIELD_NAME = "_index"
"""Name of the emitted per-row timestamp column.

Source-neutral by design: the column always carries the resolved timeline's absolute Unix-epoch nanoseconds,
whatever that source is (message log time, publish time, or a schema field), so the name asserts no particular
origin. It matches the ``_index`` index that :py:meth:`Topic.get_data_as_df` labels its rows with. The column's
real identity is its metadata marker (:py:data:`TIMESTAMP_FIELD_METADATA_KEY`), never this name, which is
uniquified by suffixing when a projected field already claims it."""


def timestamp_field(name: str = TIMESTAMP_FIELD_NAME) -> "pyarrow.Field":
    """The timestamp column's Arrow field: int64 epoch nanoseconds, metadata-marked."""
    pa = import_optional_dependency("pyarrow", "analytics")
    return pa.field(name, pa.int64(), metadata={TIMESTAMP_FIELD_METADATA_KEY: b"true"})


def timestamp_column_index(schema: "pyarrow.Schema") -> int:
    """Locate the timestamp column by its metadata marker.

    The column is identified by metadata, never by name: a projected root
    field can legitimately carry any name, including the timestamp column's
    conventional one.

    Raises:
        RobotoInternalException: The schema does not contain exactly one
            marked column.
    """
    marked = [
        index for index in range(len(schema)) if TIMESTAMP_FIELD_METADATA_KEY in (schema.field(index).metadata or {})
    ]
    if len(marked) != 1:
        raise RobotoInternalException(
            f"Topic-data batch schema must contain exactly one timestamp-marked column, found {len(marked)}."
        )
    return marked[0]


def rows_to_batch(
    rows: collections.abc.Sequence[tuple[int, dict[str, typing.Any]]],
) -> "pyarrow.RecordBatch":
    """Encode decoded ``(timestamp, row)`` pairs as one nested RecordBatch.

    Column types are inferred from the rows' values. A row that lacks a
    top-level key contributes a null to that column (a whole absent subtree is
    a single struct-level null); a row that carries an empty dict contributes
    a valid struct whose children are all null — a different value, and one
    decoded messages do produce.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    field_names: dict[str, None] = {}
    for _, row in rows:
        for key in row:
            field_names.setdefault(key, None)

    ts_name = TIMESTAMP_FIELD_NAME
    while ts_name in field_names:
        ts_name += "_"

    arrays = [pa.array([ts for ts, _ in rows], type=pa.int64())]
    fields = [timestamp_field(ts_name)]
    for name in field_names:
        column = pa.array([row.get(name) for _, row in rows])
        arrays.append(column)
        fields.append(pa.field(name, column.type))
    return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields))


def flatten_table(table: "pyarrow.Table") -> "pyarrow.Table":
    """Expand struct columns into dot-delimited leaf columns, recursively.

    A null at any struct level propagates to nulls in every leaf column
    beneath it. List-typed columns stay whole. This is the DataFrame packing
    shape: dotted leaf columns over the projected tree.

    Raises:
        RobotoInvalidRequestException: Two columns resolve to the same dotted
            name — e.g. a top-level field literally named ``pose.x`` alongside a
            struct ``pose`` with child ``x``. A plain dict would silently drop
            one (last write wins); the ambiguity is rejected instead. Rename the
            offending field or disable ``flatten=True`` to recover the column.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    while any(pa.types.is_struct(field.type) for field in table.schema):
        columns: dict[str, typing.Any] = {}

        def add_column(name: str, column: typing.Any) -> None:
            if name in columns:
                raise RobotoInvalidRequestException(
                    f"Flattening produced two columns named {name!r}; the dotted packing shape "
                    "cannot represent both. Rename the colliding field or call get_data_as_df "
                    "with flatten=False."
                )
            columns[name] = column

        for field in table.schema:
            column = table[field.name].combine_chunks()
            if pa.types.is_struct(field.type):
                for child_index, child in enumerate(field.type):
                    add_column(f"{field.name}.{child.name}", pc.struct_field(column, [child_index]))
            else:
                add_column(field.name, column)
        table = pa.table(columns)
    return table
