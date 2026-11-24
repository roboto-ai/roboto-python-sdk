# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
import re
from typing import Annotated, Literal, Optional, TypeAlias, Union
import unicodedata
import urllib.parse

import pydantic

from ...compat import StrEnum
from ...warnings import experimental

CUSTOM_FIELD_NAME_PATTERN = r"[a-z][a-z0-9_]{0,62}"
"""Regular expression a custom field's name must match.

A name is at most 63 characters long, starts with a lowercase ASCII letter, and otherwise contains only lowercase
ASCII letters, digits, and underscores. The pattern is unanchored, for embedding in a larger one; to match a whole
name, wrap it as ``^...$``.
"""


class CustomFieldStatus(StrEnum):
    """Lifecycle state of a custom field, which determines what can be done with it.

    After :py:meth:`~roboto.domain.custom_fields.CustomField.create`, Roboto sets the field up and moves it from
    ``Creating`` to ``Ready``. After :py:meth:`~roboto.domain.custom_fields.CustomField.delete`, the field is
    ``Deleting`` until Roboto removes it. Either process can end in ``Failed`` instead.
    """

    Creating = "creating"
    """Roboto is still setting the field up.

    Values cannot yet be set on entities, and search cannot filter or sort by the field.
    """

    Ready = "ready"
    """The field is set up. Values can be set on entities, and search can filter and sort by the field."""

    Deleting = "deleting"
    """Roboto is deleting the field.

    Treat the field as already gone: values can no longer be set on it.
    """

    Failed = "failed"
    """The field's most recent create or delete did not finish.

    The field stays in this state until it is deleted or Roboto intervenes.
    """


class TargetEntityType(StrEnum):
    """Kind of Roboto entity a custom field applies to.

    Each custom field applies to one entity type, and its name is unique among its organization's fields for that
    type.
    """

    Collection = "collection"
    """Collections (:py:class:`~roboto.domain.collections.Collection`)."""

    Dataset = "dataset"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`)."""

    Device = "device"
    """Devices (:py:class:`~roboto.domain.devices.Device`)."""

    Event = "event"
    """Events (:py:class:`~roboto.domain.events.Event`)."""

    Session = "session"
    """Sessions (:py:class:`~roboto.experimental.sessions.Session`)."""

    @property
    def url_safe_value(self) -> str:
        """Value of the entity type, URL-encoded for use in a request path.

        :py:meth:`~roboto.domain.custom_fields.CustomField.from_name_and_entity_type` builds its request path through
        it, so most code never calls it.
        """
        return urllib.parse.quote_plus(self.value)


class CustomFieldType(StrEnum):
    """Value type of a custom field, which determines the values it accepts and how search can filter by it.

    A field's type is fixed when the field is created. Search can sort by a field of any type, and can check whether
    an entity has a value for it.
    """

    Boolean = "boolean"
    """Boolean value. Search can test it for equality."""

    Enum = "enum"
    """String value from a fixed set of allowed values. Search can test it for equality.

    The allowed values are declared by ``EnumFieldOptions`` when the field is created. Values can be added to the set
    later, with :py:meth:`~roboto.domain.custom_fields.CustomField.add_enum_values`, but not removed from it.
    """

    Number = "number"
    """Numeric value. Search can test it for equality and compare it against a range."""

    String = "string"
    """Free-form string value. Search can test it for equality, a substring, or a wildcard pattern."""

    Timestamp = "timestamp"
    """Point in time. Search can test it for equality and compare it against a range.

    Values may be given as a ``datetime``, an ISO 8601 string, an ``int`` of nanoseconds since the
    Unix epoch, or a ``float``, ``decimal.Decimal`` or numeric string of seconds since it. A string
    is read as seconds whenever it parses as a number, so the all-digit date ``20260101`` names a
    moment in 1970 rather than a day in 2026.

    A value carrying no time zone, whether a naive ``datetime`` or an ISO 8601 string with no
    offset, is read as UTC; a date with no time, such as ``2026-05-14``, resolves to midnight UTC.
    Sub-microsecond precision is not retained.

    Values are returned as ISO 8601 strings, which ``datetime.datetime.fromisoformat`` parses.
    """


# Python does not count U+FEFF as whitespace; including it keeps a pasted byte-order mark from
# surviving into a value that otherwise looks clean.
_ENUM_VALUE_WHITESPACE_RUN = re.compile(r"[\s\uFEFF]+")


def _normalize_enum_value(value: str) -> str:
    """Return the canonical spelling of an enum value.

    Composes to Unicode NFC, collapses runs of whitespace to a single space, and strips
    whitespace from either end. A byte-order mark (U+FEFF) counts as whitespace.

    Applied to a field's allowed values when they are declared, and to a value when it is set on
    an entity or matched in search, so that both spellings of the same value compare equal.
    """
    return _ENUM_VALUE_WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFC", value)).strip()


@experimental
class EnumFieldOptions(pydantic.BaseModel):
    """Configuration of an enum custom field: the values it accepts.

    Required when creating a field of type ``CustomFieldType.Enum``; fields of other types take no options. Building
    the options raises ``pydantic.ValidationError`` when ``enum_values`` is empty or ``field_type`` is not ``Enum``.
    Carried in ``CustomFieldRecord.options``,
    :py:attr:`~roboto.domain.custom_fields.CreateCustomFieldRequest.options` and
    :py:attr:`~roboto.domain.custom_fields.UpdateCustomFieldRequest.options`.
    """

    field_type: Literal[CustomFieldType.Enum] = CustomFieldType.Enum
    """Kind of field these options configure, always ``CustomFieldType.Enum``."""

    enum_values: list[str] = pydantic.Field(min_length=1)
    """Values the field accepts. At least one is required."""

    @pydantic.model_validator(mode="after")
    def _force_discriminator_in_set_fields(self) -> EnumFieldOptions:
        # Mark field_type as set even when it took its default, so a dump with exclude_unset keeps the
        # discriminator that CustomFieldOptions needs to parse the options back.
        self.__pydantic_fields_set__.add("field_type")
        return self


CustomFieldOptions: TypeAlias = Annotated[Union[EnumFieldOptions], pydantic.Field(discriminator="field_type")]
"""Type-specific configuration of any kind: one of ``EnumFieldOptions``.

The options' ``field_type`` selects the kind.
"""


@experimental
class CustomFieldRecord(pydantic.BaseModel):
    """Data record of a custom field, as the Roboto API returns it.

    A custom field is a typed field that an organization defines for one entity type, such as datasets: each entity
    of that type can hold a value for it, and search can filter and sort by it.
    :py:class:`~roboto.domain.custom_fields.CustomField` wraps this record with methods that act on the field.
    """

    created: datetime.datetime
    """Time the custom field was created."""

    created_by: str
    """Principal that created the custom field, as ``<type>:<id>``, such as ``user:<user_id>``."""

    description: Optional[str] = None
    """Human-readable description of the custom field, or ``None`` if it has none."""

    display_name: Optional[str] = None
    """Human-readable label of the custom field, or ``None`` if it has none."""

    entity_type: TargetEntityType
    """Kind of entity the custom field applies to. Fixed when the field is created."""

    field_id: str
    """Unique ID of the custom field, beginning with ``cf_``."""

    field_name: str
    """Name of the custom field, unique among its organization's fields for its entity type.

    Fixed when the field is created.
    """

    field_type: CustomFieldType
    """Value type of the custom field. Fixed when the field is created."""

    metadata_path: Optional[str] = None
    """Unused. Roboto rejects a create request that sets it, so it is always ``None``."""

    modified: datetime.datetime
    """Time the custom field was last modified."""

    modified_by: str
    """Principal that last modified the custom field, in the same ``<type>:<id>`` form as ``created_by``.

    Roboto's own system user when Roboto made the change, such as moving ``status`` to ``CustomFieldStatus.Ready``.
    """

    options: Optional[CustomFieldOptions] = None
    """Type-specific configuration of the custom field.

    Set on fields of type ``CustomFieldType.Enum``; ``None`` on types that take no options.
    """

    org_id: str
    """ID of the organization that owns the custom field."""

    status: CustomFieldStatus
    """Lifecycle state of the custom field, which determines what can be done with it."""

    last_error: str | None = None
    """Human-readable reason the custom field's most recent create or delete failed, or ``None``.

    Set when ``status`` becomes ``CustomFieldStatus.Failed``, and cleared when the field is deleted. Roboto sets it;
    no request does.
    """

    attempts: int = 0
    """Number of times Roboto has tried to finish the custom field's current create or delete, for diagnosis.

    Reset to ``0`` when the field becomes ``CustomFieldStatus.Ready`` and when its deletion begins. Roboto sets it;
    no request does.
    """
