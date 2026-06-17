# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
from typing import Annotated, Literal, Optional, TypeAlias, Union
import urllib.parse

import pydantic

from ...compat import StrEnum
from ...warnings import experimental

CUSTOM_FIELD_NAME_PATTERN = r"[a-z][a-z0-9_]{0,62}"
"""Regular expression describing the format of a valid custom-field name.

A custom-field name is at most 63 characters long, starts with a lowercase ASCII
letter, and may otherwise contain lowercase ASCII letters, digits, and underscores.

Unanchored, for embedding in a larger pattern; wrap as ``^{...}$`` to match a
whole field name.
"""


class CustomFieldStatus(StrEnum):
    """Lifecycle state of a :py:class:`~roboto.domain.custom_fields.CustomField`.

    The status tells a caller what they can do with the field right now. See the
    :py:class:`~roboto.domain.custom_fields.CustomField` class docstring for the
    full lifecycle narrative.
    """

    Creating = "creating"
    """The field is being set up.

    Values cannot yet be assigned to entities, and the field cannot be referenced
    in search or sort.
    """

    Ready = "ready"
    """The field is fully available.

    Values can be set on entities and the field can be used in search filters and
    as a sort key.
    """

    Deleting = "deleting"
    """The field is on its way out. Callers should treat it as already gone."""

    Failed = "failed"
    """The most recent create or delete attempt did not succeed.

    The field stays in this state until an operator intervenes. A field that
    failed during creation can normally be deleted, however.
    """


class TargetEntityType(StrEnum):
    """Roboto entity type that a custom field extends.

    Each custom field is scoped to exactly one entity type, and a given
    ``field_name`` is unique within an ``(org_id, entity_type)`` pair.
    """

    Collection = "collection"
    """Field applies to :py:class:`~roboto.domain.collections.Collection` entities."""

    Dataset = "dataset"
    """Field applies to :py:class:`~roboto.domain.datasets.Dataset` entities."""

    Device = "device"
    """Field applies to :py:class:`~roboto.domain.devices.Device` entities."""

    Event = "event"
    """Field applies to :py:class:`~roboto.domain.events.Event` entities."""

    Session = "session"
    """Field applies to :py:class:`~roboto.domain.sessions.Session` entities."""

    @property
    def url_safe_value(self) -> str:
        """URL-encoded form of this entity type's value, suitable for embedding in a path segment."""
        return urllib.parse.quote_plus(self.value)


class CustomFieldType(StrEnum):
    """Value type of a custom field.

    A field's type is fixed at creation time and determines which operators are
    supported in search and sort, as well as which Python types can be assigned
    as values.
    """

    Boolean = "boolean"
    """A boolean value. Supports equality filtering."""

    Enum = "enum"
    """A string value drawn from a fixed set of allowed values.

    The allowed values are declared at creation time via :py:class:`EnumFieldOptions`.
    Supports equality and membership filtering, plus sort.
    """

    Number = "number"
    """A numeric value. Supports equality, range filtering, and sort."""

    String = "string"
    """A free-form string value. Supports equality, substring, and sort."""

    Timestamp = "timestamp"
    """A point in time. Supports equality, range filtering, and sort."""


EnumValue: TypeAlias = Annotated[str, pydantic.StringConstraints(min_length=1, max_length=256)]
"""One allowed value of an :py:attr:`CustomFieldType.Enum` field. Non-empty, up to 256 characters."""


@experimental
class EnumFieldOptions(pydantic.BaseModel):
    """Configuration for an :py:attr:`CustomFieldType.Enum` custom field.

    Declares the set of values an enum field will accept. Required when creating
    an enum field; unused for other field types.
    """

    field_type: Literal[CustomFieldType.Enum] = CustomFieldType.Enum
    """Discriminator that identifies this options payload as belonging to an enum field."""

    enum_values: list[EnumValue] = pydantic.Field(min_length=1)
    """Allowed values for the field. Must contain at least one value."""

    @pydantic.model_validator(mode="after")
    def _force_discriminator_in_set_fields(self) -> EnumFieldOptions:
        # https://github.com/pydantic/pydantic/issues/6465
        self.__pydantic_fields_set__.add("field_type")
        return self


CustomFieldOptions: TypeAlias = Annotated[Union[EnumFieldOptions], pydantic.Field(discriminator="field_type")]
"""Type-specific configuration carried alongside a custom field. Currently only :py:class:`EnumFieldOptions`."""


@experimental
class CustomFieldRecord(pydantic.BaseModel):
    """Wire-transmissible representation of a :py:class:`~roboto.domain.custom_fields.CustomField`.

    Returned by the custom-fields API and wrapped by
    :py:class:`~roboto.domain.custom_fields.CustomField` for ergonomic access.
    Callers normally interact with the wrapping class rather than this record
    directly.
    """

    created: datetime.datetime
    """UTC timestamp when the field was defined."""

    created_by: str
    """User ID that defined the field."""

    description: Optional[str] = None
    """Long-form description of the field's meaning, or ``None`` if unset."""

    display_name: Optional[str] = None
    """Human-readable label for the field, or ``None`` if unset."""

    entity_type: TargetEntityType
    """Roboto entity type the field extends."""

    field_id: str
    """Opaque, globally unique identifier for the field."""

    field_name: str
    """Name of the field. Unique within ``(org_id, entity_type)`` and fixed at creation time."""

    field_type: CustomFieldType
    """Value type of the field. Fixed at creation time."""

    metadata_path: Optional[str] = None
    """Source metadata key the field was promoted from, if any. Reserved for future use."""

    modified: datetime.datetime
    """Timestamp of the field's most recent status or metadata change."""

    modified_by: str
    """User ID of the most recent modifier. May be a system identity for automatic status changes."""

    options: Optional[CustomFieldOptions] = None
    """Type-specific configuration.

    Present for :py:attr:`CustomFieldType.Enum` fields; ``None`` for types that
    take no options.
    """

    org_id: str
    """Organization that owns the field."""

    status: CustomFieldStatus
    """Current lifecycle status. See :py:class:`CustomFieldStatus`."""

    last_error: str | None = None
    """Human-readable summary of the most recent failure, if any.

    Populated when :py:attr:`status` is :py:attr:`CustomFieldStatus.Failed`, and may
    stay set after a retry until the next failure or success.
    """

    attempts: int = 0
    """Number of attempts the platform has made for the field's current lifecycle phase.

    Diagnostic; not actionable for callers.
    """
