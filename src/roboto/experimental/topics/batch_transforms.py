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

Inside the read path, a decoded batch also leads with a row number column (:py:func:`topic_data_schema`): each
row's ``uint64`` position among its file's rows of the topic, marked by :py:data:`ROW_NUMBER_FIELD_METADATA_KEY`.
When a partition's fields are stored across several files, merging those files compares this column to confirm
every file holds the same rows. Batches returned to a caller leave it out (:py:func:`drop_row_number_column`).

:py:func:`flatten_table` expands a table's struct columns into dot-delimited leaf columns, which
``Topic.get_data_as_df(flatten=True)`` returns as the value columns of its DataFrame.

It also exposes the helpers that construct and locate the timestamp and row number columns
(:py:func:`topic_data_schema`, :py:func:`timestamp_field`, :py:func:`timestamp_column_index`,
:py:func:`row_number_column_index`), which the read path uses to mark and find those columns by metadata rather than
name.
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

MARKER_FIELD_METADATA_VALUE = b"true"
"""Value of the metadata key on the column it marks, for both :py:data:`TIMESTAMP_FIELD_METADATA_KEY` and
:py:data:`ROW_NUMBER_FIELD_METADATA_KEY`."""

TIMESTAMP_FIELD_METADATA_KEY = b"roboto.topic_data.timestamp"
"""Arrow field-metadata key marking the per-row timestamp column of a topic-data batch.

The timestamp column holds this key with the value ``b"true"`` (:py:data:`MARKER_FIELD_METADATA_VALUE`); a column
holding the key with any other value is a value column."""

TIMESTAMP_FIELD_NAME = "_index"
"""Name of the emitted per-row timestamp column.

Source-neutral by design: the column always carries the resolved timeline's absolute Unix-epoch nanoseconds,
whatever that source is (message log time, publish time, or a schema field), so the name asserts no particular
origin. It matches the ``_index`` index that :py:meth:`Topic.get_data_as_df` labels its rows with. The column's
real identity is its metadata marker (:py:data:`TIMESTAMP_FIELD_METADATA_KEY`), never this name, which is
uniquified by suffixing when a projected field already claims it."""


ROW_NUMBER_FIELD_METADATA_KEY = b"roboto.topic_data.row_number"
"""Arrow field-metadata key marking the row number column of a decoded topic-data batch.

The row number column holds this key with the value ``b"true"`` (:py:data:`MARKER_FIELD_METADATA_VALUE`); a
column holding the key with any other value is a value column."""

ROW_NUMBER_FIELD_NAME = "_row"
"""Requested name of the row number column; ``_`` is appended while another column of the batch has it.

The column's identity is its metadata marker (:py:data:`ROW_NUMBER_FIELD_METADATA_KEY`), never this name."""


def row_number_column_index(schema: "pyarrow.Schema") -> int:
    """Locate the row number column: the field whose :py:data:`ROW_NUMBER_FIELD_METADATA_KEY` metadata is ``b"true"``.

    Raises:
        RobotoInternalException: The schema does not contain exactly one
            marked column.
    """
    return _marked_column_index(schema, ROW_NUMBER_FIELD_METADATA_KEY, "row number")


def drop_row_number_column(batch: "pyarrow.RecordBatch") -> "pyarrow.RecordBatch":
    """Return ``batch`` without its row number column, found by its metadata marker.

    Raises:
        RobotoInternalException: The batch does not contain exactly one
            marked row number column.
    """
    return batch.remove_column(row_number_column_index(batch.schema))


def topic_data_schema(value_fields: collections.abc.Sequence["pyarrow.Field"]) -> "pyarrow.Schema":
    """The schema of a decoded batch whose value columns are ``value_fields``: row number, timestamp, then values.

    The row number column is non-null ``uint64``. ``_`` is appended to the timestamp column's name until no value
    column has it, then to the row number column's name until neither a value column nor the timestamp column has it.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    value_names = {field.name for field in value_fields}
    timestamp_name = TIMESTAMP_FIELD_NAME
    while timestamp_name in value_names:
        timestamp_name += "_"
    row_number_name = ROW_NUMBER_FIELD_NAME
    while row_number_name == timestamp_name or row_number_name in value_names:
        row_number_name += "_"
    row_number_field = pa.field(
        row_number_name,
        pa.uint64(),
        nullable=False,
        metadata={ROW_NUMBER_FIELD_METADATA_KEY: MARKER_FIELD_METADATA_VALUE},
    )
    return pa.schema([row_number_field, timestamp_field(timestamp_name), *value_fields])


def timestamp_field(name: str = TIMESTAMP_FIELD_NAME) -> "pyarrow.Field":
    """The timestamp column's Arrow field: int64 epoch nanoseconds, metadata-marked."""
    pa = import_optional_dependency("pyarrow", "analytics")
    return pa.field(name, pa.int64(), metadata={TIMESTAMP_FIELD_METADATA_KEY: MARKER_FIELD_METADATA_VALUE})


def timestamp_column_index(schema: "pyarrow.Schema") -> int:
    """Locate the timestamp column: the field whose :py:data:`TIMESTAMP_FIELD_METADATA_KEY` metadata is ``b"true"``.

    The column is identified by metadata, never by name: a projected root
    field can legitimately carry any name, including the timestamp column's
    conventional one.

    Raises:
        RobotoInternalException: The schema does not contain exactly one
            marked column.
    """
    return _marked_column_index(schema, TIMESTAMP_FIELD_METADATA_KEY, "timestamp")


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


def _marked_column_index(schema: "pyarrow.Schema", key: bytes, column: str) -> int:
    marked = [
        index for index, field in enumerate(schema) if (field.metadata or {}).get(key) == MARKER_FIELD_METADATA_VALUE
    ]
    if len(marked) != 1:
        raise RobotoInternalException(
            f"Topic-data batch schema must contain exactly one {column}-marked column, found {len(marked)}."
        )
    return marked[0]
