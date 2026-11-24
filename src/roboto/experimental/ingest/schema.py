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
    """Field of a topic schema, as a caller declares it: one named value in each of the topic's messages.

    Carried in ``Schema.fields``. :py:class:`~roboto.domain.topics.SchemaFieldRecord` is the field as Roboto stores
    it, with the ID Roboto assigns.

    ``path`` lists the names from the schema root down to this field, so a nested field's path extends its parent's,
    and its last name is ``name``. Either one is derived from the other when omitted: a top-level field needs only
    ``name``, and a nested field needs only ``path``. A vector, such as a LeRobot ``observation.state`` feature, is
    one field typed :py:attr:`~roboto.domain.topics.CanonicalDataType.NumberArray`, whose elements
    ``element_names`` may name.

    Building it raises ``pydantic.ValidationError`` when:

    - ``data_type`` is empty.
    - ``name`` and ``path`` are both omitted or empty, ``path`` has an empty name, or the last name in ``path`` is
      not ``name``.
    - ``element_names`` is set on a field that may not carry names, or does not give each element one non-empty
      name that no other element has.
    - The field is typed :py:attr:`~roboto.domain.topics.CanonicalDataType.Timestamp` and ``unit`` is ``None`` or
      not a :py:class:`~roboto.time.TimeUnit` value.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: str = ""
    """Name of the field: the last name in ``path``. Defaults to that name when only ``path`` is given."""

    path: list[str] = pydantic.Field(default_factory=list)
    """Names from the schema root down to this field, each non-empty, ending with ``name``.

    Omitted, ``None`` or empty defaults to ``[name]``."""

    data_type: str = pydantic.Field(min_length=1)
    """Native data type of the field, as the source data's framework names it, such as ``"float32"``."""

    canonical_data_type: CanonicalDataType = CanonicalDataType.Unknown
    """Framework-independent data type of the field, which Roboto uses to choose how to display its data."""

    unit: typing.Optional[str] = None
    """Unit of the field's values, such as ``"rad"``, or ``None`` if it has none or it is unknown.

    A field typed :py:attr:`~roboto.domain.topics.CanonicalDataType.Timestamp` must give a
    :py:class:`~roboto.time.TimeUnit` value: ``"s"``, ``"ms"``, ``"us"`` or ``"ns"``."""

    element_names: typing.Optional[list[str]] = None
    """Name of each element of a fixed-length numeric array field, in element order, or ``None`` to leave them unnamed.

    For example, ``["shoulder", "elbow"]`` names the elements of a ``float32[2]`` joint vector.

    Only a top-level field typed :py:attr:`~roboto.domain.topics.CanonicalDataType.NumberArray` may carry names,
    and only when its ``data_type`` ends in a single ``[<N>]`` and its elements are not one byte wide (``uint8``,
    ``int8``, ``uint8_t``, ``int8_t``, ``byte``, ``char`` or ``octet``, in any letter case). It takes one name per
    element, each non-empty and unique within the array, and the schema may declare no field under it. Element
    names are part of what identifies a schema, so the same array with and without names makes two schemas."""

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
    """Topic schema, as a caller declares it: the fields that make up a topic's messages.

    Carried in :py:attr:`~roboto.experimental.ingest.TopicDeclaration.topic_schema`. A declared schema carries no
    checksum: Roboto computes one from the fields and stores the schema as a
    :py:class:`~roboto.domain.topics.TopicSchema`, with that checksum and the ID Roboto assigns.

    Within an organization, declarations with identical fields share one stored schema, whether the fields were
    written by hand or converted from a source format, and in whatever order they are listed. Every attribute of
    every field counts: ``name``, ``path``, ``data_type``, ``canonical_data_type``, ``unit`` and ``element_names``.
    Declarations that differ in any of them are stored as separate schemas. The schema's own ``name`` does not count.

    A field a timeline source reads its timestamps from is marked only by its type,
    :py:attr:`~roboto.domain.topics.CanonicalDataType.Timestamp`, and its :py:class:`~roboto.time.TimeUnit` unit.
    Which timeline source reads resolve to when they name none is not part of the schema: ``is_default_for_reads``
    on each entry of :py:attr:`~roboto.experimental.ingest.TopicDeclaration.timeline_sources` states it, and a later
    declaration can change it, so the same fields make one schema whichever source reads resolve to.

    Building it raises ``pydantic.ValidationError`` when ``fields`` is empty, two fields have the same ``path``, a
    field sits under a field that has ``element_names``, or a field breaks a rule ``Field`` states.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    name: typing.Optional[str] = None
    """Informational name of the schema, such as the topic's name; not part of its identity."""

    fields: list[Field] = pydantic.Field(min_length=1)
    """Fields of the topic's messages, each at its own ``path``."""

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
