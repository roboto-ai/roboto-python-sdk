# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import Annotated, Optional, TypeAlias, Union
import unicodedata

import pydantic

from ...sentinels import NotSet, NotSetType, is_set
from ...warnings import experimental
from .record import (
    CUSTOM_FIELD_NAME_PATTERN,
    CustomFieldOptions,
    CustomFieldStatus,
    CustomFieldType,
    EnumFieldOptions,
    TargetEntityType,
    _normalize_enum_value,
)

FieldDescription: TypeAlias = Annotated[str, pydantic.StringConstraints(max_length=256)]
"""Long-form description of a custom field. Up to 256 characters."""

FieldDisplayName: TypeAlias = Annotated[str, pydantic.StringConstraints(max_length=128)]
"""Human-readable label for a custom field. Up to 128 characters."""


def _text_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    return value.strip() or None


# Maximum number of options for an enum custom field.
_MAX_ENUM_VALUES = 250

# Maximum character length - after whitespace trimming - of an enum option, as provided by the user.
# Enum options are normalized, and their normalized length will usually, but not always,
# be smaller than what the user provided.
_MAX_ENUM_VALUE_LENGTH = 256

# Characters that would break RoboQL queries if they show up in an enum option.
_ENUM_VALUE_FORBIDDEN_PUNCTUATION = frozenset('"\\')


def _clean_enum_value(value: str, index: int) -> str:
    # Check for rejected characters before normalizing, so that they fail loudly rather than
    # quietly becoming a space or some other benign character. NFC neither introduces nor removes
    # any of these, so it's safe to apply afterwards.
    for position, character in enumerate(value):
        # Reject Unicode control characters, such as NUL, tab, CR, LF, etc.
        if unicodedata.category(character) == "Cc":
            raise ValueError(
                f"enum_values[{index}] contains a control character (U+{ord(character):04X} at position "
                f"{position}); such a value cannot be expressed in a search query"
            )

        if character in _ENUM_VALUE_FORBIDDEN_PUNCTUATION:
            raise ValueError(
                f"enum_values[{index}] contains {character!r} (U+{ord(character):04X} at position {position}); "
                "double quotes and backslashes are not supported in enum values"
            )

    # Length is checked for before normalizing, against what the caller actually sent.
    trimmed = value.strip()
    if len(trimmed) > _MAX_ENUM_VALUE_LENGTH:
        raise ValueError(
            f"enum_values[{index}] is {len(trimmed)} characters; "
            f"an enum value may be at most {_MAX_ENUM_VALUE_LENGTH} characters"
        )

    normalized = _normalize_enum_value(value)
    if not normalized:
        raise ValueError(f"enum_values[{index}] is blank")

    return normalized


def _validate_field_options(options: CustomFieldOptions) -> CustomFieldOptions:
    if isinstance(options, EnumFieldOptions):
        unique_values: list[str] = []
        seen: set[str] = set()

        for index, value in enumerate(options.enum_values):
            cleaned = _clean_enum_value(value, index)
            if cleaned not in seen:
                seen.add(cleaned)
                unique_values.append(cleaned)

        if len(unique_values) > _MAX_ENUM_VALUES:
            raise ValueError(f"a field may declare at most {_MAX_ENUM_VALUES} enum values, got {len(unique_values)}")

        return options.model_copy(update={"enum_values": unique_values})

    return options


ValidatedCustomFieldOptions: TypeAlias = Annotated[CustomFieldOptions, pydantic.AfterValidator(_validate_field_options)]
"""Custom field options as supplied when a field is defined - tidied and checked."""


@experimental
class CreateCustomFieldRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/custom-fields``.

    Defines a new custom field for an entity type in the caller's organization.
    Normally constructed by :py:meth:`~roboto.domain.custom_fields.CustomField.create`
    rather than instantiated directly.
    """

    description: Optional[FieldDescription] = None
    """Long-form description of the field's meaning.

    Surrounding whitespace is removed. Text that is empty once stripped counts as unset.
    """

    display_name: Optional[FieldDisplayName] = None
    """Human-readable label shown in the UI.

    Surrounding whitespace is removed. Text that is empty once stripped counts as unset.
    """

    entity_type: TargetEntityType
    """Roboto entity type the field extends."""

    field_name: Annotated[str, pydantic.StringConstraints(pattern=rf"^{CUSTOM_FIELD_NAME_PATTERN}$")]
    """Name of the field. Fixed at creation time.

    Must match ``^[a-z][a-z0-9_]{0,62}$`` (lowercase ASCII, max 63 chars) and is
    unique within ``(org_id, entity_type)``.
    """

    field_type: CustomFieldType
    """Value type of the field.

    Determines which operators are supported in search and sort.
    """

    metadata_path: Optional[str] = None
    """Reserved for promoting an existing metadata key into a custom field.

    Not yet supported; leave as ``None``. Supplying a value is rejected.
    """

    options: Optional[ValidatedCustomFieldOptions] = None
    """Type-specific configuration.

    Required for :py:attr:`CustomFieldType.Enum` fields (to declare the allowed values).

    Enum values are tidied before they are stored: each is normalized to Unicode NFC,
    surrounding whitespace is removed, internal runs of whitespace become a single space,
    and values that repeat after that are deduplicated. A field may declare at most 250
    distinct values, each at most 256 characters long as supplied, not counting surrounding whitespace.

    A value is rejected if it is blank, or if it contains a control character, a double
    quote, or a backslash: a value carrying one of those cannot be relied on to work in search.
    """

    @pydantic.field_validator("description", "display_name", mode="after")
    @classmethod
    def _blank_text_is_unset(cls, value: Optional[str]) -> Optional[str]:
        return _text_or_none(value)

    @pydantic.model_validator(mode="after")
    def check_options_match_field_type(self) -> CreateCustomFieldRequest:
        if self.field_type == CustomFieldType.Enum and self.options is None:
            raise ValueError(f"options are required for field_type '{CustomFieldType.Enum}'")

        if self.options is not None and self.options.field_type != self.field_type:
            raise ValueError(
                f"field_type is '{self.field_type}', but field_options are for '{self.options.field_type}'"
            )

        return self


@experimental
class ListCustomFieldsRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/custom-fields/query``.

    Pages through the custom fields visible to the caller, optionally filtered by
    entity type and status. Normally constructed by
    :py:meth:`~roboto.domain.custom_fields.CustomField.list` rather than directly.
    """

    entity_type: Optional[TargetEntityType] = None
    """If provided, restrict results to fields targeting this entity type."""

    statuses: list[CustomFieldStatus] = pydantic.Field(min_length=1)
    """Statuses to include in the results. Must contain at least one status."""

    page_token: Optional[str] = None
    """Opaque token returned by a prior page; omit on the first request."""


@experimental
class UpdateCustomFieldRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/custom-fields/{field_id}``.

    Carries mutable metadata changes for an existing custom field. Each request attribute
    defaults to :py:obj:`~roboto.sentinels.NotSet`, which leaves the
    corresponding attribute unchanged; pass ``None`` explicitly to clear an
    attribute.
    """

    description: Union[Optional[FieldDescription], NotSetType] = NotSet
    """New description for the field, or ``None`` to clear it.

    Leave as :py:obj:`~roboto.sentinels.NotSet` to leave unchanged. Surrounding whitespace is
    removed, and text that is empty once stripped clears the attribute.
    """

    display_name: Union[Optional[FieldDisplayName], NotSetType] = NotSet
    """New display name for the field, or ``None`` to clear it.

    Leave as :py:obj:`~roboto.sentinels.NotSet` to leave unchanged. Surrounding whitespace is
    removed, and text that is empty once stripped clears the attribute.
    """

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.field_validator("description", "display_name", mode="after")
    @classmethod
    def _blank_text_clears(cls, value: Union[Optional[str], NotSetType]) -> Union[Optional[str], NotSetType]:
        # Text that is empty once stripped clears the attribute rather than leaving it alone:
        # a caller who sent whitespace asked for it to be emptied, and NotSet would no-op.
        if not is_set(value):
            return value

        return _text_or_none(value)
