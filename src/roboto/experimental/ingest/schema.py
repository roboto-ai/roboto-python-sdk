# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...domain.topics.record import CanonicalDataType, FixedArrayDataType
from ...time import TimeUnit


class Field(pydantic.BaseModel):
    """One column of a topic's data, identified by name, type, and unit.

    ``path`` lists the names from the schema root down to this field, so a nested field's path extends its
    parent's. ``name`` and ``path`` state one fact twice (the last path element is the field's name), so
    either may be omitted and derives from the other: a top-level field needs only ``name``, and a nested
    field needs only ``path``. A vector column (e.g. a LeRobot ``observation.state`` feature) is one field typed
    :py:attr:`~roboto.domain.topics.record.CanonicalDataType.NumberArray`, whose elements may be named with
    :py:attr:`element_names`.

    This is what a caller declares. :py:class:`~roboto.domain.topics.record.SchemaFieldRecord` is what the
    platform returns for a field it has stored, and carries the identifiers it assigns.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: str = ""
    """Name of the field. Defaults to the last element of ``path`` when only ``path`` is given;
    at least one of ``name`` and ``path`` must be declared."""

    path: list[str] = pydantic.Field(default_factory=list)
    """The names from the schema root down to this field; a nested field's path extends its parent's path.
    Omitted, ``None``, or empty defaults to ``[name]``;
    when given, every element must be non-empty and the last element must equal ``name``."""

    data_type: str = pydantic.Field(min_length=1)
    """Native type of the field as recorded by the source format (e.g. ``"float32"``)."""

    canonical_data_type: CanonicalDataType = CanonicalDataType.Unknown
    """Roboto's normalized type for the field, used for cross-format reads and visualization."""

    unit: typing.Optional[str] = None
    """Unit of the field's values (e.g. ``"rad"``). A field typed
    :py:attr:`~roboto.domain.topics.record.CanonicalDataType.Timestamp` must carry a
    :py:class:`~roboto.time.TimeUnit` value (one of ``"s"``, ``"ms"``, ``"us"``, ``"ns"``)."""

    element_names: typing.Optional[list[str]] = None
    """Name of each element of a fixed-width numeric array, in element order (e.g. ``["shoulder", "elbow"]`` for a
    ``float32[2]`` joint vector). Only a top-level field typed
    :py:attr:`~roboto.domain.topics.record.CanonicalDataType.NumberArray` whose ``data_type`` ends in a single
    ``[N]`` may carry names, and only when its elements are not one byte wide (``uint8``, ``int8``, ``uint8_t``,
    ``int8_t``, ``byte``, ``char`` or ``octet``, in any letter case). It takes exactly N names, each non-empty and
    unique within the array, and the field must have no child fields. Names are part of schema identity: the same
    array with and without names is two schemas."""

    @pydantic.model_validator(mode="before")
    @classmethod
    def _derive_name_and_path_from_each_other(cls, data: typing.Any) -> typing.Any:
        if not isinstance(data, dict):
            return data

        name = data.get("name")
        path = data.get("path")
        if not path and isinstance(name, str) and name:
            return {**data, "path": [name]}
        if name is None and isinstance(path, list) and path and isinstance(path[-1], str) and path[-1]:
            return {**data, "name": path[-1]}
        return data

    @pydantic.model_validator(mode="after")
    def _validate_path_names_this_field(self) -> "Field":
        if not self.name and not self.path:
            raise ValueError("a field must declare a name, a path, or both")
        if any(not element for element in self.path):
            raise ValueError(f"field {self.name!r} has an empty element in path {self.path!r}")
        if not self.path or self.path[-1] != self.name:
            raise ValueError(
                f"the last element of a field's path must equal its name; "
                f"got name {self.name!r} with path {self.path!r}"
            )
        return self

    @pydantic.model_validator(mode="after")
    def _validate_element_names(self) -> "Field":
        if self.element_names is None:
            return self

        if len(self.path) != 1:
            raise ValueError(f"only a top-level field may declare element_names; field {self.path!r} is nested")
        if self.canonical_data_type is not CanonicalDataType.NumberArray:
            raise ValueError(
                f"field {self.name!r} declares element_names, so its canonical_data_type must be "
                f"{CanonicalDataType.NumberArray.value!r}, not {self.canonical_data_type.value!r}"
            )
        fixed_array = FixedArrayDataType.parse(self.data_type)
        if fixed_array is None:
            raise ValueError(
                f"field {self.name!r} declares element_names, so its data_type must be a flat fixed-width array "
                f"ending in one [N], such as 'float32[6]'; got {self.data_type!r}"
            )
        if fixed_array.has_byte_width_elements:
            raise ValueError(
                f"field {self.name!r} holds byte-width elements ({fixed_array.element_type!r}), which may not be named"
            )
        if len(self.element_names) != fixed_array.length:
            raise ValueError(
                f"field {self.name!r} is {fixed_array.length} elements wide "
                f"but declares {len(self.element_names)} element_names"
            )
        if any(not name for name in self.element_names):
            raise ValueError(f"field {self.name!r} has an empty name in element_names {self.element_names!r}")
        if len(set(self.element_names)) != len(self.element_names):
            raise ValueError(f"field {self.name!r} repeats a name in element_names {self.element_names!r}")
        return self

    @pydantic.model_validator(mode="after")
    def _require_time_unit_on_timestamp_fields(self) -> "Field":
        if self.canonical_data_type is not CanonicalDataType.Timestamp:
            return self

        accepted = ", ".join(repr(member.value) for member in TimeUnit)
        if self.unit is None:
            raise ValueError(f"a Timestamp-typed field must declare a unit: one of {accepted}")
        try:
            TimeUnit(self.unit)
        except ValueError:
            raise ValueError(
                f"unit {self.unit!r} is not a recognized TimeUnit for a Timestamp-typed field; "
                f"expected one of {accepted}"
            ) from None
        return self


class Schema(pydantic.BaseModel):
    """The structure of one topic's data: the columns it carries.

    However a schema is produced, whether hand-written field by field or converted from a source format's own
    metadata, the registered result is the same: schemas are content-addressed server-side. Identity covers
    every attribute of every field (name, path, source data type, canonical type, unit, and element names), so
    identical declarations collapse to a single stored schema no matter how many times they are repeated, while
    declarations differing in any field attribute are stored separately.

    A column a timeline source reads is declared by typing it
    :py:attr:`~roboto.domain.topics.record.CanonicalDataType.Timestamp` with a
    :py:class:`~roboto.time.TimeUnit` unit; nothing else marks it. Which of a topic's timeline sources reads
    fall back to is not part of the schema: it is stated on
    :py:attr:`~roboto.experimental.ingest.TopicDeclaration.timeline_sources` and can be changed later, so the
    same columns are one schema no matter which source is preferred.

    This is what a caller declares, so it carries no checksum: the platform computes that from the fields.
    :py:class:`~roboto.domain.topics.record.TopicSchemaRecord` is the stored schema the platform returns,
    carrying that checksum and the identifiers it assigns.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: typing.Optional[str] = None
    """Informational label for the schema (often the topic name). Not part of schema identity."""

    fields: list[Field] = pydantic.Field(min_length=1)
    """Declared columns of the topic's data. At least one is required, and every field's path must be
    unique within the schema."""

    @pydantic.model_validator(mode="after")
    def _reject_duplicate_field_paths(self) -> "Schema":
        seen: set[tuple[str, ...]] = set()
        for field in self.fields:
            path = tuple(field.path)
            if path in seen:
                raise ValueError(f"duplicate field path {list(path)!r}; each field must have a unique path")
            seen.add(path)
        return self

    @pydantic.model_validator(mode="after")
    def _reject_child_fields_under_a_named_array(self) -> "Schema":
        named_arrays = {tuple(field.path) for field in self.fields if field.element_names is not None}
        for field in self.fields:
            if len(field.path) > 1 and (field.path[0],) in named_arrays:
                raise ValueError(
                    f"field {field.path!r} sits under the named array {field.path[0]!r}, "
                    "which must have no child fields"
                )
        return self
