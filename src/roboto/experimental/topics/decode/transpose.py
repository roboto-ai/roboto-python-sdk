# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reshape decoded message rows into typed Arrow columns.

One :py:class:`ColumnTransposer` per output column buffers that column's value
from each decoded message and, at batch boundaries, builds an Arrow array whose
type comes from the topic's schema inferred during ingestion.
"""

from __future__ import annotations

import array
import sys
import typing

from ....compat import import_optional_dependency
from ....formats.mcap import McapDialect
from ..batch_transforms import timestamp_field
from .schema_tree import SchemaNode, array_dimension_count, dialect_time_name

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


_INT32_OFFSET_LIMIT = 0x7FFFFFFF  # 2**31 - 1
"""Largest element count addressable by an int32 list offset; past it, the fast path falls back."""


_ROS_TIME_ALIASES: dict[str, tuple[str, ...]] = {
    "sec": ("secs",),
    "nsec": ("nsecs", "nanosec"),
}
"""Canonical ROS time-field name -> the runtime names a decoded message may carry instead.

A schema declares ``sec``/``nsec``, but a ROS1 message exposes ``secs``/``nsecs`` and a
ROS2 message ``nanosec``. :py:func:`_normalize_struct` falls back to these aliases when a
decoded message omits the canonical name, so the value is found either way.
"""


def _subtree_has_ros_time(node: SchemaNode) -> bool:
    """Whether ``node``'s subtree contains a canonical ROS time field (``sec``/``nsec``).

    Gates per-row key normalization to only the columns that could need it; every
    other column appends its value untouched.
    """
    if node.name in _ROS_TIME_ALIASES:
        return True
    return any(_subtree_has_ros_time(child) for child in node.children)


def _normalize_struct(
    children: tuple[SchemaNode, ...], value: typing.Any, dialect: McapDialect
) -> typing.Optional[dict[str, typing.Any]]:
    """Rebuild ``value`` keyed by each child's dialect name, reading ROS time aliases when present.

    A ROS time subfield is read from whichever alias the decoded message carries and written
    under the child's dialect name (:py:func:`dialect_time_name`), so the rebuilt dict's keys
    match the struct fields :py:meth:`SchemaNode.arrow_type` declares for the same dialect.
    Returns ``None`` for a non-mapping value so a struct that decoded to the wrong shape
    becomes a typed null rather than reaching ``pa.array`` as drift.
    """
    if not isinstance(value, dict):
        return None
    normalized: dict[str, typing.Any] = {}
    for child in children:
        child_value = value.get(child.name)
        if child_value is None:
            for alias in _ROS_TIME_ALIASES.get(child.name, ()):
                if alias in value:
                    child_value = value[alias]
                    break
        normalized[dialect_time_name(child.name, dialect)] = _normalize_value(child, child_value, dialect)
    return normalized


def _normalize_value(node: SchemaNode, value: typing.Any, dialect: McapDialect) -> typing.Any:
    """Rewrite ROS runtime time-field keys in ``value`` to the dialect's names.

    A schema-driven walk: structs and array-of-struct elements are rebuilt with the
    dialect's time-field names; scalars and scalar lists pass through unchanged.
    """
    if value is None:
        return None
    if node.is_struct:
        return _normalize_struct(node.children, value, dialect)
    if node.is_array:
        if not isinstance(value, list):
            return None
        if node.children:
            return [_normalize_struct(node.children, element, dialect) for element in value]
        return value
    return value


def _is_native_byte_order(fmt: str) -> bool:
    """Whether a PEP 3118 buffer-format string is native byte order (no opposite-endian marker)."""
    marker = fmt[:1]
    if marker not in ("<", ">", "!"):
        return True  # no marker, '@', '=', or a bare type char -> native
    return marker == ("<" if sys.byteorder == "little" else ">")


def _native_element_buffer(value: typing.Any, width: int) -> typing.Optional[typing.Any]:
    """One row's elements as a contiguous, native-byte-order byte buffer, or ``None`` to fall back.

    ``bytes``/``bytearray`` are accepted only for 1-byte elements: raw bytes carry no element
    size or byte order, so wider widths are ambiguous. Any other value is accepted only if it
    exposes the buffer protocol (``array.array``, ``numpy.ndarray``, ``memoryview``) as a 1-D,
    C-contiguous buffer whose item size is ``width`` in native byte order. A Python ``list`` or
    ``tuple``, or any rank/size/order mismatch, returns ``None``.
    """
    if isinstance(value, (bytes, bytearray)):
        return value if width == 1 else None
    try:
        view = memoryview(value)
    except TypeError:
        return None
    if view.ndim != 1 or not view.c_contiguous or view.itemsize != width:
        return None
    if width > 1 and not _is_native_byte_order(view.format):
        return None
    return view.cast("B")


class ColumnBuildError(Exception):
    """A topic field's data could not be read against the type recorded for it at ingestion.

    Customer-facing: the message names the specific field, describes the data's shape in plain
    language, and reports the field's recorded type -- enough for a user to know which field is
    affected and for Roboto to diagnose the schema/data mismatch (e.g. a multi-dimensional array
    flattened to a single dimension in the stored type). The underlying ``pyarrow`` error is kept
    as the exception's ``__cause__`` for internal logs, not surfaced in the message.
    """


def _value_depth(value: typing.Any) -> int:
    """List-nesting depth of a decoded value; an ``array.array`` of scalars counts as depth 1."""
    if isinstance(value, array.array):
        return 1
    if isinstance(value, (list, tuple)):
        return 1 + (_value_depth(value[0]) if value else 0)
    return 0


def _describe_value(value: typing.Any) -> str:
    """A short, plain-language description of a decoded value's structure (not its contents)."""
    if value is None:
        return "no value"
    if isinstance(value, bool):
        return "a true/false value"
    if isinstance(value, (int, float)):
        return "a single number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, (bytes, bytearray)):
        return "binary data"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, array.array):
        return "a list of numbers"
    if isinstance(value, (list, tuple)):
        if not value:
            return "an empty list"
        return "a list of " + _element_phrase(value[0])
    return "an unexpected value"


def _element_phrase(value: typing.Any, depth: int = 4) -> str:
    """The plural element description nested inside ``a list of ...`` (e.g. ``lists of numbers``)."""
    if isinstance(value, bool):
        return "true/false values"
    if isinstance(value, (int, float)):
        return "numbers"
    if isinstance(value, str):
        return "text values"
    if isinstance(value, (bytes, bytearray)):
        return "binary values"
    if isinstance(value, dict):
        return "objects"
    if isinstance(value, array.array):
        return "lists of numbers"
    if isinstance(value, (list, tuple)):
        if depth <= 0:
            return "lists"
        if not value:
            return "empty lists"
        return "lists of " + _element_phrase(value[0], depth - 1)
    return "values"


def _locate_mismatch(
    node: SchemaNode, value: typing.Any, dialect: McapDialect
) -> typing.Optional[tuple[typing.Sequence[str], str, typing.Any]]:
    """Pinpoint the leaf field whose decoded value cannot fit its declared type.

    Walks the schema node alongside one representative decoded value and returns the first
    ``(field path, recorded native type, offending value)`` where the structure disagrees --
    typically a field declared as a flat list whose data decoded as a nested list. Returns
    ``None`` when no single leaf can be singled out, so the caller names the whole column.
    """
    if value is None:
        return None

    # Array-of-struct or struct: descend into whichever child carries the offending value.
    if node.children and node.is_array:
        element = next((item for item in value if isinstance(item, dict)), None) if isinstance(value, list) else None
        return _locate_in_children(node.children, element, dialect)
    if node.is_struct:
        return _locate_in_children(node.children, value, dialect)

    # Leaf array: data that nests deeper than the recorded dimensions is the flattened-token case.
    if node.is_array:
        declared_depth = max(1, array_dimension_count(node.native))
        if isinstance(value, (list, tuple, array.array)) and _value_depth(value) > declared_depth:
            return node.path, node.native, value
        return None

    # Scalar leaf that decoded to a list cannot be placed against its scalar type.
    if isinstance(value, (list, tuple, array.array)):
        return node.path, node.native, value
    return None


def _locate_in_children(
    children: tuple[SchemaNode, ...], mapping: typing.Any, dialect: McapDialect
) -> typing.Optional[tuple[typing.Sequence[str], str, typing.Any]]:
    """Recurse into a struct's children, matching each child by its dialect-resolved key."""
    if not isinstance(mapping, dict):
        return None
    for child in children:
        key = dialect_time_name(child.name, dialect)
        if key in mapping:
            found = _locate_mismatch(child, mapping[key], dialect)
            if found is not None:
                return found
    return None


class ColumnTransposer:
    """Buffers one output column's per-message values and builds its typed Arrow array.

    The column's Arrow type and name are fixed from the schema node and the partition's
    ``dialect`` at construction; :py:meth:`append_row` takes the column's extracted value
    (or ``None`` when the field is absent for that row) and :py:meth:`column` materializes
    the buffered rows against the fixed type.
    """

    def __init__(self, node: SchemaNode, dialect: McapDialect = McapDialect.OTHER) -> None:
        pa = import_optional_dependency("pyarrow", "analytics")

        self._type = node.arrow_type(dialect)
        self._field = pa.field(node.name, self._type)
        self._node = node
        self._dialect = dialect
        self._needs_normalization = _subtree_has_ros_time(node)
        self._values: list[typing.Any] = []

    def append_row(self, value: typing.Any) -> None:
        """Append this column's value for one row; ``None`` records a typed null."""
        if self._needs_normalization:
            value = _normalize_value(self._node, value, self._dialect)
        self._values.append(value)

    def column(self) -> tuple["pyarrow.Field", "pyarrow.Array"]:
        """The column's ``(field, array)``, built against the schema-declared type."""
        pa = import_optional_dependency("pyarrow", "analytics")

        buffer_backed_array = self.__maybe_build_buffer_backed_array()
        if buffer_backed_array is not None:
            # Fast path applied; skip the per-element generic builder.
            return self._field, buffer_backed_array

        try:
            return self._field, pa.array(self._values, type=self._type)
        except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as err:
            sample = next((v for v in self._values if v is not None), None)
            mismatch = _locate_mismatch(self._node, sample, self._dialect)
            if mismatch is not None:
                path, native, offending = mismatch
                field = ".".join(path)
                detail = (
                    f"The file stores it as {_describe_value(offending)}, which does not match the "
                    f"type recorded for this field when the data was ingested ('{native}')."
                )
            else:
                field = ".".join(self._node.path)
                detail = (
                    f"The data in the file does not match the type recorded for this field when it "
                    f"was ingested ('{self._node.native}')."
                )
            raise ColumnBuildError(
                f"Could not read field '{field}' from this topic. {detail} This field likely needs "
                f"to be re-ingested; if the problem persists, contact Roboto support and share this message."
            ) from err

    def reset(self) -> None:
        """Drop the buffered rows so the transposer can build the next batch."""
        self._values = []

    def __maybe_build_buffer_backed_array(self) -> typing.Optional["pyarrow.Array"]:
        """Build a ``list<int|float>`` column by concatenating each row's element buffer.

        The generic :py:func:`pyarrow.array` converts a fixed-width list element by element, which
        dominates decode time for wide rows such as image ``uint8[]`` or point-cloud ``float32[]``.
        When the column is a list of a fixed-width integer or float AND every row is already a
        contiguous, native-byte-order buffer of the matching element width, this builds the array as
        the rows' bytes concatenated into one value buffer plus int32 offsets, with no per-element
        work.

        Returns ``None`` -- so :py:meth:`column` falls back to the generic builder -- when the
        element type is not a fixed-width int or float, any row is not such a buffer (e.g. a decoder
        yielding ``list[int]``), or the element count exceeds the int32 offset limit.
        """
        pa = import_optional_dependency("pyarrow", "analytics")

        if not pa.types.is_list(self._type):
            return None

        value_type = self._type.value_type
        if not (pa.types.is_integer(value_type) or pa.types.is_floating(value_type)):
            return None

        width = value_type.bit_width // 8

        parts: list[typing.Any] = []
        offsets: list[int] = [0]
        null_mask: list[bool] = []
        has_null = False
        total_elements = 0
        for value in self._values:
            if value is None:
                has_null = True
                null_mask.append(True)
                offsets.append(total_elements)
                continue

            buffer = _native_element_buffer(value, width)
            if buffer is None:
                return None

            null_mask.append(False)
            parts.append(buffer)
            total_elements += len(buffer) // width
            if total_elements > _INT32_OFFSET_LIMIT:  # int32 offsets cannot address this batch
                return None

            offsets.append(total_elements)

        values = pa.Array.from_buffers(value_type, total_elements, [None, pa.py_buffer(b"".join(parts))])
        mask = pa.array(null_mask, type=pa.bool_()) if has_null else None
        return pa.ListArray.from_arrays(pa.array(offsets, type=pa.int32()), values, mask=mask)


def record_batch_from_columns(
    timestamp_name: str,
    timestamps: list[int],
    fields: list["pyarrow.Field"],
    arrays: list["pyarrow.Array"],
) -> "pyarrow.RecordBatch":
    """Frame the timestamp column and the transposed columns into one RecordBatch."""
    pa = import_optional_dependency("pyarrow", "analytics")

    return pa.RecordBatch.from_arrays(
        [pa.array(timestamps, type=pa.int64()), *arrays],
        schema=pa.schema([timestamp_field(timestamp_name), *fields]),
    )
