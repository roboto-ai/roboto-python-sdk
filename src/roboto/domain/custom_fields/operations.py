# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import Annotated, Optional, TypeAlias, Union

import pydantic

from ...sentinels import NotSet, NotSetType
from ...warnings import experimental
from .record import (
    CUSTOM_FIELD_NAME_PATTERN,
    CustomFieldOptions,
    CustomFieldStatus,
    CustomFieldType,
    TargetEntityType,
)

FieldDescription: TypeAlias = Annotated[str, pydantic.StringConstraints(max_length=256)]
"""Long-form description of a custom field. Up to 256 characters."""

FieldDisplayName: TypeAlias = Annotated[str, pydantic.StringConstraints(max_length=128)]
"""Human-readable label for a custom field. Up to 128 characters."""


@experimental
class CreateCustomFieldRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/custom-fields``.

    Defines a new custom field for an entity type in the caller's organization.
    Normally constructed by :py:meth:`~roboto.domain.custom_fields.CustomField.create`
    rather than instantiated directly.
    """

    description: Optional[FieldDescription] = None
    """Long-form description of the field's meaning."""

    display_name: Optional[FieldDisplayName] = None
    """Human-readable label shown in the UI."""

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

    Not yet supported; leave as ``None``.
    """

    options: Optional[CustomFieldOptions] = None
    """Type-specific configuration.

    Required for :py:attr:`CustomFieldType.Enum` fields (to declare the allowed
    values).
    """

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

    Leave as :py:obj:`~roboto.sentinels.NotSet` to leave unchanged.
    """

    display_name: Union[Optional[FieldDisplayName], NotSetType] = NotSet
    """New display name for the field, or ``None`` to clear it.

    Leave as :py:obj:`~roboto.sentinels.NotSet` to leave unchanged.
    """

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
