# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Typed schema tree for schema-driven MCAP decode.

A topic's per-field schema (:py:class:`~roboto.domain.topics.SchemaFieldRecord`)
declares every field's path, canonical type, and native type before any byte is
read. This module wraps those records into a navigable tree whose every column's
Arrow type and per-leaf structural resolution is fixed statically, so the MCAP
decoder never samples a message to discover its shape.

Built once per read from the topic's field declarations and consumed by the MCAP
decode path. (Parquet reads take their Arrow types from the file's own schema and
do not use this tree.)
"""

from __future__ import annotations

import collections.abc
import dataclasses
import re
import typing

from ....compat import import_optional_dependency
from ....domain.topics.record import CanonicalDataType, FieldPath, SchemaFieldRecord
from ....formats.mcap import (
    McapDialect,
    Resolution,
    sequence_resolution,
    simple_resolution,
)
from ....logging import default_logger

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

logger = default_logger()


_OUTERMOST_ARRAY_DIM = re.compile(r"\[\d*\]$")
"""The single trailing dimension of a token -- the ``[3]`` in ``float32[2][3]``, or ``[]`` in ``uint8[]``.

Anchored to the end and unrepeated, so substituting it peels exactly one level of nesting rather than
the whole chain; this is what makes :py:func:`strip_fixed_size` outermost-only.
"""

_ARRAY_DIM = re.compile(r"\[\d*\]")
"""One dimension matched anywhere, unanchored so that :py:meth:`re.Pattern.findall` enumerates them all.

Counting, not stripping: run only against an already-isolated chain to get its length in
:py:func:`array_dimension_count`. The unanchored form would over-match on a raw token, hence the
deliberate pairing with :py:data:`_TRAILING_ARRAY_DIMS` rather than use on its own.
"""

_TRAILING_ARRAY_DIMS = re.compile(r"(?:\[\d*\])+$")
"""The entire trailing run of dimensions -- ``[2][3]`` in ``float32[2][3]``, ``[]`` in ``uint8[]``.

Anchored and repeated, so substituting it bares the scalar base in one pass; this is what makes
:py:func:`strip_array_suffixes` collapse every dimension where :py:data:`_OUTERMOST_ARRAY_DIM` removes one.
"""


def strip_fixed_size(token: str) -> str:
    """Strip one trailing ``[N]``/``[]`` array suffix from a native type token.

    ``float64[36]`` -> ``float64``, ``uint8_t[50]`` -> ``uint8_t``, ``char[9]`` -> ``char``,
    ``uint8[]`` -> ``uint8``. A token with no suffix is returned unchanged. Removes only the
    outermost dimension; use :py:func:`strip_array_suffixes` to collapse a multi-dimensional token.
    """
    return _OUTERMOST_ARRAY_DIM.sub("", token)


def strip_array_suffixes(token: str) -> str:
    """Strip the entire trailing chain of ``[N]``/``[]`` array suffixes from a native type token.

    ``float32[3][3]`` -> ``float32``, ``float32[]`` -> ``float32``, ``float32`` -> ``float32``.
    Unlike :py:func:`strip_fixed_size`, which removes only the outermost dimension, this collapses a
    multi-dimensional token down to its base scalar so the leaf element type can be derived from it.
    """
    return _TRAILING_ARRAY_DIMS.sub("", token)


def array_dimension_count(token: str) -> int:
    """The number of trailing array suffixes a native type token declares -- its list-nesting depth.

    ``float32`` -> 0, ``float32[]`` -> 1, ``float32[3][3]`` -> 2, ``float[2][2][2]`` -> 3. A token that
    declares more than one dimension types as a correspondingly nested Arrow list (``float32[3][3]`` ->
    ``list<list<float32>>``), matching the nested value the decoder yields for such a field.
    """
    match = _TRAILING_ARRAY_DIMS.search(token)
    if match is None:
        return 0
    return len(_ARRAY_DIM.findall(match.group()))


_SCALAR_TOKEN_NAMES: dict[str, str] = {
    "double": "float64",
    "float64": "float64",
    "float": "float32",
    "float32": "float32",
    "int8": "int8",
    "int8_t": "int8",
    "int16": "int16",
    "int16_t": "int16",
    "int32": "int32",
    "int32_t": "int32",
    "integer": "int64",  # unsized/generic token
    "int64": "int64",
    "int64_t": "int64",
    "uint8": "uint8",
    "uint8_t": "uint8",
    "uint16": "uint16",
    "uint16_t": "uint16",
    "uint32": "uint32",
    "uint32_t": "uint32",
    "uint64": "uint64",
    "uint64_t": "uint64",
    "bool": "bool_",
    "large_string": "large_string",
    "string": "string",
}
"""Native scalar type token -> the ``pyarrow`` type factory name it maps to.

Covers the ROS1/ROS2, uORB, and Arrow-native spellings the schema actually carries
(including every uORB ``*_t`` integer). Taking width from the native token narrows an
MCAP-decoded value to the same Arrow type Parquet assigns the same column, so the two
stay concatenable. The deprecated ROS aliases ``byte`` and ``char`` are deliberately
omitted because their signedness is dialect-dependent; numeric uses resolve them through
:py:func:`_resolve_byte_char`, while a uORB textual ``char`` (canonical ``String``) stays
a string via the canonical-type fallback in :py:func:`_scalar_arrow_type`.
"""


_DIALECT_TIME_NAMES: dict[str, dict[McapDialect, str]] = {
    "sec": {McapDialect.ROS1: "secs", McapDialect.ROS2: "sec", McapDialect.OTHER: "sec"},
    "nsec": {McapDialect.ROS1: "nsecs", McapDialect.ROS2: "nanosec", McapDialect.OTHER: "nsec"},
}
"""Canonical ROS time-field name -> the subfield name each dialect's message def carries.

A schema declares a ROS time struct's subfields canonically as ``sec``/``nsec``, but the
emitted column must name them as the message def does: ROS1 ``secs``/``nsecs``, ROS2
``sec``/``nanosec``, and the canonical names unchanged for any non-ROS (``OTHER``) dialect.
This is the single source of truth shared with the transposer's value normalization
(:py:mod:`roboto.experimental.topics.decode.transpose`) so the declared field name and the
normalized dict key cannot drift.
"""


def dialect_time_name(name: str, dialect: McapDialect) -> str:
    """The subfield name ``dialect`` carries for a canonical ROS time field ``name``.

    Non-time names, and every name under the ``OTHER`` dialect, are returned unchanged.
    """
    mapping = _DIALECT_TIME_NAMES.get(name)
    return mapping[dialect] if mapping is not None else name


def _resolve_byte_char(token: str, dialect: McapDialect) -> typing.Optional[str]:
    """The ``pyarrow`` factory name for a deprecated ROS ``byte``/``char`` alias, or ``None``.

    ROS1 ``byte``=int8/``char``=uint8; ROS2 reverses both. A non-ROS (``OTHER``) dialect
    has no signed convention, so both widen to ``int16`` -- the smallest width that
    round-trips any 8-bit value whether the source meant it signed or unsigned.
    """
    if token == "byte":  # noqa: S105 -- a native type token, not a credential
        if dialect == McapDialect.ROS1:
            return "int8"
        return "uint8" if dialect == McapDialect.ROS2 else "int16"
    if token == "char":  # noqa: S105 -- a native type token, not a credential
        if dialect == McapDialect.ROS2:
            return "int8"
        return "uint8" if dialect == McapDialect.ROS1 else "int16"
    return None


def _scalar_arrow_type(
    token: str, canonical: CanonicalDataType, dialect: McapDialect = McapDialect.OTHER
) -> "pyarrow.DataType":
    """The Arrow scalar type for a native ``token``, falling back to ``canonical`` when unknown.

    An unrecognized token never raises: it logs at debug and derives a coarse type from
    the canonical class (number -> float64, boolean -> bool, string/categorical -> string,
    else null), so an unseen native spelling yields a typed column rather than failing the
    read.

    The deprecated ROS aliases ``byte`` and ``char`` carry a dialect-dependent signedness,
    resolved through :py:func:`_resolve_byte_char` for any non-string field. A uORB textual
    ``char`` is canonical ``String``, where that resolution is skipped so the token falls
    through to the string fallback -- the only place ``byte``/``char`` stays non-numeric.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    # A textual `char` (canonical String) must stay a string; every other field -- numeric
    # scalar or integer categorical -- takes the dialect-signed byte/char width.
    if canonical != CanonicalDataType.String:
        byte_char = _resolve_byte_char(token, dialect)
        if byte_char is not None:
            return getattr(pa, byte_char)()

    factory_name = _SCALAR_TOKEN_NAMES.get(token)
    if factory_name is not None:
        return getattr(pa, factory_name)()

    logger.debug("Unrecognized native type token %r (canonical %s); deriving from canonical type", token, canonical)
    if canonical == CanonicalDataType.Number:
        return pa.float64()
    if canonical == CanonicalDataType.Boolean:
        return pa.bool_()
    if canonical in (CanonicalDataType.String, CanonicalDataType.Categorical):
        return pa.string()
    return pa.null()


def _char_array_element_type(token: str) -> "pyarrow.DataType":
    """Arrow element type for a ``String`` field stored as a char array (e.g. ``char[9]``).

    A ``char[N]`` field carries canonical ``String`` but is decoded element-wise into a list
    of signed 8-bit code units -- the same ``list<int8>`` Parquet stores for the column
    (code-unit values come back signed, e.g. ``-36``).
    The element is therefore ``int8`` unless the native token names an explicit width the scalar map knows
    (e.g. a raw ``uint8[]``), in which case that width wins so the two stay concatenable.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    factory_name = _SCALAR_TOKEN_NAMES.get(token)
    if factory_name is not None:
        return getattr(pa, factory_name)()
    return pa.int8()


def _arrow_time_unit(unit: typing.Optional[str]) -> str:
    """The ``pyarrow`` timestamp resolution for a schema field unit, defaulting to nanoseconds.

    A schema timestamp field carries its stored values' unit as a
    :py:class:`~roboto.time.TimeUnit` value (``"s"``/``"ms"``/``"us"``/``"ns"``),
    which is exactly ``pyarrow``'s timestamp-unit vocabulary; an absent or
    unrecognized unit falls back to nanoseconds, the platform default.
    """
    if unit in ("s", "ms", "us", "ns"):
        return typing.cast(str, unit)
    return "ns"


@dataclasses.dataclass(frozen=True)
class SchemaNode:
    """One declared schema field, plus its declared child fields.

    Children are held in fields-GET response order, parents before children. The
    node's name is the leaf component of its path — the schema-native attribute
    name the decoder's accumulator is keyed by — which is also its Arrow field name.
    """

    record: SchemaFieldRecord
    children: tuple["SchemaNode", ...]

    @property
    def path(self) -> FieldPath:
        """This field's path components, outermost to leaf."""
        return self.record.path_in_schema

    @property
    def name(self) -> str:
        """The schema-native attribute name: the leaf component of the field's path.

        Doubles as the decode accumulator's key and the Arrow struct/column field name,
        so accumulated values land under the field that declares them by construction.
        """
        return self.record.path_in_schema[-1]

    @property
    def canonical(self) -> CanonicalDataType:
        """The field's normalized, encoding-agnostic data type."""
        return self.record.canonical_data_type

    @property
    def native(self) -> str:
        """The field's native, framework-specific type token (e.g. ``"float32"``, ``"esc_report[8]"``)."""
        return self.record.data_type

    @property
    def is_array(self) -> bool:
        """Whether this node is a sequence (its decoded value is a list)."""
        return self.canonical in (CanonicalDataType.Array, CanonicalDataType.NumberArray)

    @property
    def is_struct(self) -> bool:
        """Whether this node is a struct with declared children (its decoded value is a mapping)."""
        return self.canonical == CanonicalDataType.Object and bool(self.children)

    def arrow_type(self, dialect: McapDialect = McapDialect.OTHER) -> "pyarrow.DataType":
        """The Arrow type for this node's column, derived entirely from the schema.

        Canonical type decides the structure (struct vs. list vs. scalar); the native
        token decides scalar width *and*, for an array, list-nesting depth -- a token
        declaring multiple dimensions (e.g. ``float32[3][3]``) types as a correspondingly
        nested list (``list<list<float32>>``). This is the structural inverse of the Arrow-to-
        canonical mapping in :py:mod:`roboto.formats.parquet.arrow_to_roboto`, so an
        MCAP-decoded column and the Parquet-ingested one for the same field agree.

        A multi-dimensional array whose schema records only a single, flattened suffix (e.g. a
        ``float[3][3]`` persisted as ``float32[9]``) still types as a 1-D list; faithful nesting
        requires the native token to carry the full suffix chain.

        ``dialect`` resolves the two framework-dependent details a canonical type cannot
        carry: the signedness of ``byte``/``char`` scalars and the subfield names of ROS
        time structs. It defaults to ``OTHER``, which keeps the canonical, framework-neutral
        typing and naming for non-ROS data and dialect-agnostic callers.
        """
        pa = import_optional_dependency("pyarrow", "analytics")
        canonical = self.canonical

        if canonical == CanonicalDataType.Object:
            return self._struct_type(dialect)
        if canonical in (CanonicalDataType.Array, CanonicalDataType.NumberArray):
            return pa.list_(self._element_type(dialect))
        if canonical == CanonicalDataType.Number:
            return _scalar_arrow_type(self.native, canonical, dialect)
        if canonical == CanonicalDataType.Boolean:
            return pa.bool_()
        if canonical == CanonicalDataType.String:
            # A char[N] field carries canonical String but is decoded element-wise into a list
            # of code units -- the same list<int8> Parquet stores -- so type it as a list to
            # stay concatenable; a scalar `string`/`large_string` stays a scalar string.
            if _OUTERMOST_ARRAY_DIM.search(self.native):
                return pa.list_(_char_array_element_type(strip_fixed_size(self.native)))
            return _scalar_arrow_type(self.native, canonical, dialect)
        if canonical == CanonicalDataType.Byte:
            return pa.binary()
        if canonical == CanonicalDataType.Timestamp:
            return pa.timestamp(_arrow_time_unit(self.record.unit), tz="UTC")
        if canonical == CanonicalDataType.Categorical:
            # The MCAP wire value is the raw scalar -- an integer severity enum (native
            # `byte`/`char`, dialect-signed) or a string label -- not the dictionary<int,
            # string> Parquet ingestion produces. Type it from the native token: byte/char
            # take a dialect-dependent integer width, a string token stays a string.
            return _scalar_arrow_type(self.native, canonical, dialect)
        if canonical == CanonicalDataType.Image:
            return self._image_type()
        if canonical in (
            CanonicalDataType.LatDegFloat,
            CanonicalDataType.LonDegFloat,
            CanonicalDataType.LatDegInt,
            CanonicalDataType.LonDegInt,
        ):
            return _scalar_arrow_type(self.native, canonical, dialect)
        return pa.null()

    def _struct_type(self, dialect: McapDialect) -> "pyarrow.DataType":
        pa = import_optional_dependency("pyarrow", "analytics")
        if not self.children:
            return pa.null()
        return pa.struct(
            [pa.field(dialect_time_name(child.name, dialect), child.arrow_type(dialect)) for child in self.children]
        )

    def _element_type(self, dialect: McapDialect) -> "pyarrow.DataType":
        """The element type sitting inside the outer ``pa.list_`` :py:meth:`arrow_type` applies.

        The base element is a struct (array-of-struct) or a scalar whose width comes from the native
        token with its whole array-suffix chain stripped. A native token declaring more than one
        dimension contributes one further ``pa.list_`` per *inner* dimension (the outermost is the list
        already applied by the caller), so ``float32[3][3]`` -> ``list<list<float32>>`` while ``float32[]``
        and an array-of-struct stay one level deep.
        """
        pa = import_optional_dependency("pyarrow", "analytics")
        if self.children:
            element = pa.struct(
                [pa.field(dialect_time_name(child.name, dialect), child.arrow_type(dialect)) for child in self.children]
            )
        else:
            element_canonical = (
                CanonicalDataType.Number
                if self.canonical == CanonicalDataType.NumberArray
                else CanonicalDataType.String
            )
            element = _scalar_arrow_type(strip_array_suffixes(self.native), element_canonical, dialect)
        for _ in range(max(0, array_dimension_count(self.native) - 1)):
            element = pa.list_(element)
        return element

    def _image_type(self) -> "pyarrow.DataType":
        """The Arrow type for an image field: a list of its native element's scalar type.

        ``CanonicalDataType.Image`` is assigned only to a message's raw ``data`` byte
        array (``uint8[]``) — for both ``sensor_msgs/Image`` and
        ``sensor_msgs/CompressedImage`` — never to the enclosing message, which is an
        ``Object``. An image field is therefore always an array and decodes to the same
        ``list<uint8>`` (canonical ``NumberArray``) Parquet assigns the same column, so
        the two stay concatenable.
        """
        pa = import_optional_dependency("pyarrow", "analytics")
        return pa.list_(_scalar_arrow_type(strip_fixed_size(self.native), CanonicalDataType.Number))

    def leaves(self) -> list["SchemaNode"]:
        """The scalar / whole-list leaves under this node, for accessor compilation.

        A struct or array-of-struct descends into its children; a scalar or array-of-
        scalar is itself a leaf, whose accessor reads the whole list value at once.
        """
        if self.is_struct or (self.is_array and self.children):
            collected: list[SchemaNode] = []
            for child in self.children:
                collected.extend(child.leaves())
            return collected
        return [self]


@dataclasses.dataclass(frozen=True)
class SchemaTree:
    """A topic's full declared schema, with a projection-restricted column view.

    A topic schema has many top-level fields (e.g. ``header``, ``pose``, ``twist``),
    each the root of its own subtree, so the top level is a *forest* of trees rather
    than a single-rooted tree — hence ``forest``. ``forest`` and ``nodes_by_path``
    hold the whole schema and never change; ``columns`` is the subset a given read
    projects. :py:meth:`restrict` re-derives ``columns`` for a narrower projection
    against the same shared forest.
    """

    columns: tuple[SchemaNode, ...]
    """Top-level output columns, restricted to the current projection, in projection order."""

    forest: tuple[SchemaNode, ...]
    """Every top-level field with its full declared subtree, in fields-GET order."""

    nodes_by_path: dict[FieldPath, SchemaNode]
    """Every node in the full forest, keyed by path, for ancestor lookup."""

    def restrict(self, projection_paths: collections.abc.Sequence[FieldPath]) -> "SchemaTree":
        """A tree whose ``columns`` cover exactly ``projection_paths`` (the full forest is shared)."""
        return SchemaTree(
            columns=_select_columns(self.forest, projection_paths),
            forest=self.forest,
            nodes_by_path=self.nodes_by_path,
        )

    def resolution_for(self, leaf: SchemaNode) -> Resolution:
        """The structural accessor resolution for ``leaf``, derived from the schema.

        Splits the leaf's path at each enclosing list into a per-element sequence
        resolution, terminating in a simple attribute chain. Path components are the
        canonical (schema) field names; the runtime ROS time-field renaming is applied
        separately against a sample by :py:func:`~roboto.formats.mcap.remap_time_fields`.
        """
        return self.resolution_for_path(leaf.path)

    def resolution_for_path(self, path: FieldPath) -> Resolution:
        """The structural accessor resolution for a bare ``path`` (e.g. a timestamp field).

        Like :py:meth:`resolution_for` but keyed by path, for fields read without an
        output column (the designated timestamp).
        """
        return self._resolution(path, 0)

    def _resolution(self, path: FieldPath, start: int) -> Resolution:
        for index in range(start, len(path) - 1):
            node = self.nodes_by_path.get(path[: index + 1])
            if node is not None and node.is_array:
                return sequence_resolution(path[start : index + 1], self._resolution(path, index + 1))
        return simple_resolution(path[start:])


def build_schema_tree(
    fields: collections.abc.Sequence[SchemaFieldRecord],
    projection_paths: collections.abc.Sequence[FieldPath],
) -> SchemaTree:
    """Build a :py:class:`SchemaTree` from the fields-GET records, restricted to ``projection_paths``.

    Each record is placed under its parent (the path with its last component dropped),
    preserving GET order among siblings; ``columns`` is then the projection-restricted
    view. A projected parent pulls in its whole declared subtree. An empty projection
    yields no columns (decode emits timestamp-only batches).
    """
    forest, nodes_by_path = _build_forest(fields)
    return SchemaTree(
        columns=_select_columns(forest, projection_paths),
        forest=forest,
        nodes_by_path=nodes_by_path,
    )


def _build_forest(
    fields: collections.abc.Sequence[SchemaFieldRecord],
) -> tuple[tuple[SchemaNode, ...], dict[FieldPath, SchemaNode]]:
    record_by_path: dict[FieldPath, SchemaFieldRecord] = {}
    for field in fields:
        record_by_path.setdefault(field.path_in_schema, field)

    child_paths: dict[FieldPath, list[FieldPath]] = {path: [] for path in record_by_path}
    top_level_paths: list[FieldPath] = []
    for path in record_by_path:
        if len(path) == 1:
            top_level_paths.append(path)
            continue
        parent = path[:-1]
        # A child whose parent the schema does not declare is an orphan; surface it
        # as a top-level node rather than dropping its data.
        (child_paths[parent] if parent in child_paths else top_level_paths).append(path)

    nodes_by_path: dict[FieldPath, SchemaNode] = {}

    def build(path: FieldPath) -> SchemaNode:
        node = SchemaNode(
            record=record_by_path[path],
            children=tuple(build(child) for child in child_paths[path]),
        )
        nodes_by_path[path] = node
        return node

    forest = tuple(build(path) for path in top_level_paths)
    return forest, nodes_by_path


def _covered_whole(path: FieldPath, projection_paths: collections.abc.Sequence[FieldPath]) -> bool:
    """Whether the projection requests ``path`` or an ancestor of it (its whole subtree is in scope)."""
    return any(path[: len(projected)] == projected for projected in projection_paths)


def _restrict_node(
    node: SchemaNode, projection_paths: collections.abc.Sequence[FieldPath]
) -> typing.Optional[SchemaNode]:
    if _covered_whole(node.path, projection_paths):
        return node
    kept = [
        restricted for child in node.children if (restricted := _restrict_node(child, projection_paths)) is not None
    ]
    if kept:
        return dataclasses.replace(node, children=tuple(kept))
    return None


def _select_columns(
    forest: collections.abc.Sequence[SchemaNode],
    projection_paths: collections.abc.Sequence[FieldPath],
) -> tuple[SchemaNode, ...]:
    node_by_name = {node.name: node for node in forest}
    column_order = list(dict.fromkeys(path[0] for path in projection_paths if path))
    columns: list[SchemaNode] = []
    for name in column_order:
        node = node_by_name.get(name)
        if node is None:
            continue
        restricted = _restrict_node(node, projection_paths)
        if restricted is not None:
            columns.append(restricted)
    return tuple(columns)
