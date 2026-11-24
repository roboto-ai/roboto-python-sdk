# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional, Union

import pydantic

from roboto.domain.layouts.record import (
    LayoutAccessibility,
)
from roboto.sentinels import NotSet, NotSetType


class CreateLayoutRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/layouts/create``, which saves a reusable arrangement of visualizer panels.

    Building the request raises ``pydantic.ValidationError`` for a ``name`` or ``folder`` longer than 120 characters.
    """

    accessibility: LayoutAccessibility = pydantic.Field(
        description="Controls layout accessibility between organization-wide or user-only.",
        default=LayoutAccessibility.User,
    )
    """Who can view the layout. Defaults to :py:attr:`~roboto.domain.layouts.LayoutAccessibility.User`."""

    folder: Optional[str] = pydantic.Field(
        description="Folder to group this layout under; null leaves it at the root.",
        default=None,
        max_length=120,
    )
    """Folder to group the layout under, at most 120 characters. ``None`` leaves it ungrouped, at the root."""

    layout_definition: dict[str, Any] = pydantic.Field(description="The layout definition as a JSON object.")
    """Definition of the layout's panels and their arrangement, as a JSON object."""

    name: str = pydantic.Field(description="The name of the layout.", max_length=120)
    """Human-readable name of the layout, at most 120 characters.

    The name must differ from that of every organization-wide layout in the organization and of the creator's other
    personal layouts.
    """

    schema_version: int = pydantic.Field(description="The schema version associated with the layout definition.")
    """Version of the format ``layout_definition`` follows."""

    tags: list[str] = pydantic.Field(description="The tags associated with the layout.", default_factory=list)
    """Tags to set on the layout."""


class UpdateLayoutRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/layouts/id/{layout_id}``, which updates a layout.

    A field left unset (``NotSet``) is unchanged. Building it raises ``pydantic.ValidationError`` when:

    - ``name`` or ``folder`` is longer than 120 characters.
    - ``base_revision`` is negative.
    - ``layout_definition`` is set without ``schema_version``.
    """

    accessibility: Union[LayoutAccessibility, NotSetType] = pydantic.Field(
        description="Controls layout accessibility between organization-wide or user-only.",
        default=NotSet,
    )
    """Who can view the layout."""

    base_revision: Union[int, NotSetType] = pydantic.Field(default=NotSet, ge=0)
    """Revision of the layout when you loaded it, from :py:attr:`~roboto.domain.layouts.LayoutRecord.revision`.

    When set, Roboto refuses the update with ``RobotoConflictException``, and changes nothing, if the layout's revision
    has changed since: someone else updated it after you loaded it. ``NotSet`` applies the update whatever the
    layout's revision.
    """

    folder: Union[str, None, NotSetType] = pydantic.Field(
        description="Folder to move this layout into; null moves it to the root, omit to leave unchanged.",
        default=NotSet,
        max_length=120,
    )
    """Folder to move the layout into, at most 120 characters. ``None`` moves it out of any folder, to the root."""

    layout_definition: Union[dict[str, Any], NotSetType] = pydantic.Field(
        description="The layout definition as a JSON object.", default=NotSet
    )
    """Definition of the layout's panels and their arrangement, as a JSON object. Requires ``schema_version``."""

    name: Union[str, NotSetType] = pydantic.Field(description="The name of the layout.", default=NotSet, max_length=120)
    """Human-readable name of the layout, at most 120 characters.

    Only the layout's creator can rename it. The name must differ from that of every organization-wide layout in the
    organization and of the creator's other personal layouts.
    """

    schema_version: Union[int, NotSetType] = pydantic.Field(
        description=(
            "The schema version associated with the layout definition. It must equal the layout's: an update cannot "
            "change a layout's schema version."
        ),
        default=NotSet,
    )
    """Version of the format ``layout_definition`` follows.

    It must be the layout's own version, since an update cannot change it; another value raises
    ``RobotoInvalidRequestException``.
    """

    tags: Union[list[str], NotSetType] = pydantic.Field(
        description="The tags associated with the layout.", default=NotSet
    )
    """Tags to set on the layout, replacing its current tags."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.model_validator(mode="after")
    def validate_schema_version_with_definition(self) -> "UpdateLayoutRequest":
        """Reject a request that sets ``layout_definition`` without ``schema_version``."""
        if not isinstance(self.layout_definition, NotSetType) and isinstance(self.schema_version, NotSetType):
            raise ValueError("schema_version must be provided when updating layout_definition")
        return self
