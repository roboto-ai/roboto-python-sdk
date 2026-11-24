# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import json
import typing

from ...compat import import_optional_dependency
from ...exceptions import (
    RobotoInternalException,
    RobotoInvalidRequestException,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

MARKER_FIELD_METADATA_VALUE = b"true"
"""Value that ``TIMESTAMP_FIELD_METADATA_KEY`` or ``ROW_NUMBER_FIELD_METADATA_KEY`` holds on the column it marks."""

TIMESTAMP_FIELD_METADATA_KEY = b"roboto.topic_data.timestamp"
"""Arrow field-metadata key that marks the timestamp column of a topic-data RecordBatch.

A topic-data batch has one value column per top-level projected field, with struct and list types that follow the
topic's schema, and one timestamp column: each row's time as ``int64`` nanoseconds since the Unix epoch. The
timestamp column holds this key with the value ``b"true"`` (``MARKER_FIELD_METADATA_VALUE``); a column holding the
key with any other value is a value column."""

TIMESTAMP_FIELD_NAME = "_index"
"""Name of the timestamp column, unless a value column already has it.

The name says nothing of where the times come from: the column holds absolute Unix-epoch nanoseconds from whichever
timeline source the read uses, whether the message log time, the message publish time, or a schema field. It matches
``_index``, the name of the index of the DataFrame ``Topic.get_data_as_df`` returns. ``topic_data_schema`` appends
``_`` to the name while a value column has it, so find the column by ``TIMESTAMP_FIELD_METADATA_KEY``, never by this
name."""


ELEMENT_NAMES_FIELD_METADATA_KEY = b"roboto.topic_data.element_names"
"""Arrow field-metadata key on a named array column, whose value is the JSON list of its elements' names.

The names are in element order and cover exactly the elements the column holds, so a read that selects some elements
of a named array lists only those. ``with_element_names`` writes it and ``element_names`` reads it."""

ROW_NUMBER_FIELD_METADATA_KEY = b"roboto.topic_data.row_number"
"""Arrow field-metadata key that marks the row number column of a decoded topic-data RecordBatch.

The row number column holds each row's position among the topic's rows in its file, as a non-null ``uint64``. When a
topic partition's fields are stored across several files, combining those files compares this column to confirm that
every file holds the same rows. ``Topic.get_data_as_record_batches`` removes the column before it yields a batch.

The row number column holds this key with the value ``b"true"`` (``MARKER_FIELD_METADATA_VALUE``); a column holding
the key with any other value is a value column."""

ROW_NUMBER_FIELD_NAME = "_row"
"""Name of the row number column, unless another column of the batch already has it.

``topic_data_schema`` appends ``_`` to the name while another column has it, so find the column by
``ROW_NUMBER_FIELD_METADATA_KEY``, never by this name."""


def row_number_column_index(schema: "pyarrow.Schema") -> int:
    """Return the index of the row number column, the field marked by ``ROW_NUMBER_FIELD_METADATA_KEY``.

    Raises:
        RobotoInternalException: The schema does not have exactly one column marked as the row number column.
    """
    return _marked_column_index(schema, ROW_NUMBER_FIELD_METADATA_KEY, "row number")


def drop_row_number_column(batch: "pyarrow.RecordBatch") -> "pyarrow.RecordBatch":
    """Return ``batch`` without its row number column, found by ``ROW_NUMBER_FIELD_METADATA_KEY``.

    Raises:
        RobotoInternalException: The batch does not have exactly one column marked as the row number column.
    """
    return batch.remove_column(row_number_column_index(batch.schema))


def topic_data_schema(value_fields: collections.abc.Sequence["pyarrow.Field"]) -> "pyarrow.Schema":
    """Build the schema of a decoded topic-data batch: the row number column, the timestamp column, then values.

    The timestamp column takes ``TIMESTAMP_FIELD_NAME`` with ``_`` appended until no value column has it. The row
    number column takes ``ROW_NUMBER_FIELD_NAME`` with ``_`` appended until neither a value column nor the timestamp
    column has it.
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
    """Build the timestamp column's Arrow field: ``int64``, marked by ``TIMESTAMP_FIELD_METADATA_KEY``."""
    pa = import_optional_dependency("pyarrow", "analytics")
    return pa.field(name, pa.int64(), metadata={TIMESTAMP_FIELD_METADATA_KEY: MARKER_FIELD_METADATA_VALUE})


def timestamp_column_index(schema: "pyarrow.Schema") -> int:
    """Return the index of the timestamp column, the field marked by ``TIMESTAMP_FIELD_METADATA_KEY``.

    A value column may have any name, including ``TIMESTAMP_FIELD_NAME``, so the column is found by its metadata and
    never by its name.

    Raises:
        RobotoInternalException: The schema does not have exactly one column marked as the timestamp column.
    """
    return _marked_column_index(schema, TIMESTAMP_FIELD_METADATA_KEY, "timestamp")


def with_element_names(field: "pyarrow.Field", names: collections.abc.Sequence[str]) -> "pyarrow.Field":
    """Build a copy of ``field`` that stores ``names`` under ``ELEMENT_NAMES_FIELD_METADATA_KEY``.

    The copy keeps the rest of ``field``'s metadata.

    Args:
        names: Names of the elements the column holds, in element order.
    """
    metadata: dict[typing.Union[bytes, str], typing.Union[bytes, str]] = {
        key: value for key, value in (field.metadata or {}).items()
    }
    metadata[ELEMENT_NAMES_FIELD_METADATA_KEY] = json.dumps(list(names)).encode()
    return field.with_metadata(metadata)


def element_names(field: "pyarrow.Field") -> typing.Optional[list[str]]:
    """Return the element names a named array column stores, or ``None`` for a column that is not a named array."""
    encoded = (field.metadata or {}).get(ELEMENT_NAMES_FIELD_METADATA_KEY)
    return json.loads(encoded) if encoded is not None else None


def flatten_table(table: "pyarrow.Table") -> "pyarrow.Table":
    """Expand struct columns into dot-delimited leaf columns, recursively, and add a column per named array element.

    A null at any struct level becomes a null in every leaf column beneath it. A list column stays whole. A named
    array column (one with ``ELEMENT_NAMES_FIELD_METADATA_KEY`` metadata) stays too, followed by one
    ``<array name>.<element name>`` column per element, null where the array is null.
    ``Topic.get_data_as_df(flatten=True)`` returns these columns as the columns of its DataFrame.

    Raises:
        RobotoInvalidRequestException: Two columns flatten to the same name, such as a top-level field named
            ``pose.x`` and the child ``x`` of a struct ``pose``. Rename one of the fields, or call
            ``Topic.get_data_as_df`` with ``flatten=False``.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    if any(element_names(field) is not None for field in table.schema):
        # Expand named arrays before structs: the struct loop below builds each table from bare arrays, which drops
        # the field metadata that holds the element names.
        fields: dict[str, "pyarrow.Field"] = {}
        arrays: list[typing.Any] = []

        def keep(field: "pyarrow.Field", array: typing.Any) -> None:
            _refuse_collision(fields, field.name)
            fields[field.name] = field
            arrays.append(array)

        for field in table.schema:
            keep(field, table[field.name])
            for index, name in enumerate(element_names(field) or ()):
                element = pc.list_element(table[field.name], index)
                keep(pa.field(f"{field.name}.{name}", element.type), element)
        table = pa.table(arrays, schema=pa.schema(list(fields.values())))

    while any(pa.types.is_struct(field.type) for field in table.schema):
        columns: dict[str, typing.Any] = {}

        def add_column(name: str, column: typing.Any) -> None:
            _refuse_collision(columns, name)
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


def _refuse_collision(names: collections.abc.Container[str], name: str) -> None:
    if name in names:
        raise RobotoInvalidRequestException(
            f"Flattening produced two columns named {name!r}; the dotted packing shape "
            "cannot represent both. Rename the colliding field or call get_data_as_df "
            "with flatten=False."
        )


def _marked_column_index(schema: "pyarrow.Schema", key: bytes, column: str) -> int:
    marked = [
        index for index, field in enumerate(schema) if (field.metadata or {}).get(key) == MARKER_FIELD_METADATA_VALUE
    ]
    if len(marked) != 1:
        raise RobotoInternalException(
            f"Topic-data batch schema must contain exactly one {column}-marked column, found {len(marked)}."
        )
    return marked[0]
