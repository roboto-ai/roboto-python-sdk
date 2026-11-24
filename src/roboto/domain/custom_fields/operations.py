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
"""Human-readable description of a custom field, at most 256 characters."""

FieldDisplayName: TypeAlias = Annotated[str, pydantic.StringConstraints(max_length=128)]
"""Human-readable label for a custom field, at most 128 characters."""


def _text_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    return value.strip() or None


# Maximum number of distinct values an enum custom field may declare, counted after repeats are dropped.
_MAX_ENUM_VALUES = 250

# Maximum length of an enum value as the caller supplied it, not counting surrounding whitespace.
# Normalizing usually leaves a value no longer, but NFC can lengthen it, and that does not count
# against the cap.
_MAX_ENUM_VALUE_LENGTH = 256

# Characters that would break a RoboQL query on an enum value containing them.
_ENUM_VALUE_FORBIDDEN_PUNCTUATION = frozenset('"\\')


def _clean_enum_value(value: str, index: int) -> str:
    # Check for rejected characters before normalizing, so a tab or newline is rejected rather than
    # becoming a space. NFC neither introduces nor removes any of these characters.
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
"""Type-specific configuration of a custom field, as a create or update request carries it.

Building the request normalizes the enum values and rejects any it cannot store, as
``CreateCustomFieldRequest.options`` describes.
"""


def check_options_match_field_type(field_type: CustomFieldType, options: Optional[CustomFieldOptions]) -> None:
    """Reject an enum field type without ``options``, and ``options`` for a different field type.

    :py:meth:`~roboto.domain.custom_fields.CustomField.create` and
    :py:meth:`~roboto.domain.custom_fields.CustomField.update` check a field's options through it, so most code never
    calls it.

    Args:
        field_type: Value type of the custom field.
        options: Type-specific configuration for the field, or ``None`` if it has none.

    Raises:
        ValueError: ``field_type`` is :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Enum` and ``options`` is
            ``None``, or ``options`` are for a different field type.
    """
    if field_type == CustomFieldType.Enum and options is None:
        raise ValueError(f"options are required for field_type '{CustomFieldType.Enum}'")

    if options is not None and options.field_type != field_type:
        raise ValueError(f"field_type is '{field_type}', but field_options are for '{options.field_type}'")


@experimental
class CreateCustomFieldRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.custom_fields.CustomField.create`.

    A reserved ``field_name`` raises ``RobotoInvalidRequestException``. A ``metadata_path`` other than ``None`` raises
    ``RobotoInvalidRequestException``. Building it raises ``pydantic.ValidationError`` when:

    - ``description`` is over 256 characters.
    - ``display_name`` is over 128 characters.
    - ``field_name`` does not match its pattern.
    - ``options`` declares an enum value that ``options`` rejects.
    - ``options`` do not suit ``field_type``.
    """

    description: Optional[FieldDescription] = None
    """Human-readable description of the custom field, at most 256 characters.

    Surrounding whitespace is stripped, and text that is blank once stripped sets no description, as ``None`` does.
    """

    display_name: Optional[FieldDisplayName] = None
    """Human-readable label for the custom field, shown in the Roboto web app, at most 128 characters.

    Surrounding whitespace is stripped, and text that is blank once stripped sets no label, as ``None`` does.
    """

    entity_type: TargetEntityType
    """Entity type the custom field extends."""

    field_name: Annotated[str, pydantic.StringConstraints(pattern=rf"^{CUSTOM_FIELD_NAME_PATTERN}$")]
    """Name of the custom field, unique within its organization and entity type, and fixed once the field is created.

    Must match ``^[a-z][a-z0-9_]{0,62}$``: a lowercase ASCII letter, then up to 62 lowercase ASCII letters, digits,
    or underscores. Roboto reserves a few names that match it.
    """

    field_type: CustomFieldType
    """Value type of the custom field, fixed once the field is created.

    It determines which operators search and sort support on the field.
    """

    metadata_path: Optional[str] = None
    """Reserved for promoting a metadata key to a custom field. Leave it ``None``."""

    options: Optional[ValidatedCustomFieldOptions] = None
    """Type-specific configuration of the custom field. Required for an enum field, to declare its allowed values.

    Each enum value is normalized before it is stored: composed to Unicode NFC, with surrounding whitespace stripped
    and each run of internal whitespace collapsed to a single space. A value that repeats an earlier one once
    normalized is dropped, so the values keep the order in which each first appears. A field may declare at most 250
    distinct values, each at most 256 characters as supplied, not counting surrounding whitespace.

    A value is rejected if it is blank, or if it contains a control character, a double quote, or a backslash, because
    search could not reliably match such a value.
    """

    @pydantic.field_validator("description", "display_name", mode="after")
    @classmethod
    def _blank_text_is_unset(cls, value: Optional[str]) -> Optional[str]:
        return _text_or_none(value)

    @pydantic.model_validator(mode="after")
    def check_options_match_field_type(self) -> CreateCustomFieldRequest:
        """Reject an enum field without ``options``, and ``options`` for a different field type.

        Pydantic calls this while it builds the request.
        """
        check_options_match_field_type(self.field_type, self.options)
        return self


@experimental
class ListCustomFieldsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.custom_fields.CustomField.list`.

    Building the request raises ``pydantic.ValidationError`` when ``statuses`` is empty.
    """

    entity_type: Optional[TargetEntityType] = None
    """Entity type to list custom fields for. ``None`` lists the fields on every entity type."""

    statuses: list[CustomFieldStatus] = pydantic.Field(min_length=1)
    """Statuses of the custom fields to list. Must hold at least one."""

    page_token: Optional[str] = None
    """Token from a previous page's response that resumes the listing after it. ``None`` starts at the first page."""


@experimental
class UpdateCustomFieldRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.custom_fields.CustomField.update`.

    A field left unset (``NotSet``) is unchanged.

    A request for a custom field whose status is not :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`
    raises ``RobotoInvalidRequestException``. ``options`` for a different field type, or without an enum value the
    field already has, raise ``RobotoInvalidRequestException``. Building it raises ``pydantic.ValidationError`` when:

    - ``description`` is over 256 characters.
    - ``display_name`` is over 128 characters.
    - ``options`` declares an enum value that ``options`` rejects.
    """

    description: Union[Optional[FieldDescription], NotSetType] = NotSet
    """Human-readable description of the custom field, at most 256 characters. ``None`` clears it.

    Surrounding whitespace is stripped, and text that is blank once stripped clears it too.
    """

    display_name: Union[Optional[FieldDisplayName], NotSetType] = NotSet
    """Human-readable label for the custom field, shown in the Roboto web app, at most 128 characters.

    ``None`` clears it. Surrounding whitespace is stripped, and text that is blank once stripped clears it too.
    """

    options: Union[ValidatedCustomFieldOptions, NotSetType] = NotSet
    """Type-specific configuration to replace the custom field's own.

    Must be for the field's ``field_type``. For an enum field, ``enum_values`` must include every value the field
    already has: values can be added but not removed.

    Enum values are normalized and capped as ``CreateCustomFieldRequest.options`` describes. A value that repeats an
    earlier one once normalized is dropped rather than rejected, so re-sending a value the field already has changes
    nothing.
    """

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.field_validator("description", "display_name", mode="after")
    @classmethod
    def _blank_text_clears(cls, value: Union[Optional[str], NotSetType]) -> Union[Optional[str], NotSetType]:
        # Blank text becomes None, which clears the value, not NotSet, which would leave it unchanged:
        # a caller who sent whitespace asked for the value to be emptied.
        if not is_set(value):
            return value

        return _text_or_none(value)
