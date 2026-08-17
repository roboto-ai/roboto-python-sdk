# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...domain.topics.record import CanonicalDataType
from ...time import TimeUnit


class Field(pydantic.BaseModel):
    """One column of a topic's data, identified by name, type, and unit.

    ``path`` lists the names from the schema root down to this field, so a nested field's path extends its
    parent's. ``name`` and ``path`` state one fact twice (the last path element is the field's name), so
    either may be omitted and derives from the other: a top-level field needs only ``name``, and a nested
    field needs only ``path``. A vector column (e.g. a LeRobot ``observation.state`` feature) is expressed as
    a parent field holding the array plus one child field per named element.

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
    every attribute of every field (name, path, source data type, canonical type, and unit), so identical
    declarations collapse to a single stored schema no matter how many times they are repeated, while
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
