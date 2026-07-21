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
    """
    Request payload to create a layout
    """

    accessibility: LayoutAccessibility = pydantic.Field(
        description="Controls layout accessibility between organization-wide or user-only.",
        default=LayoutAccessibility.User,
    )
    folder: Optional[str] = pydantic.Field(
        description="Folder to group this layout under; null leaves it at the root.",
        default=None,
        max_length=120,
    )
    layout_definition: dict[str, Any] = pydantic.Field(description="The layout definition as a JSON object.")
    name: str = pydantic.Field(description="The name of the layout.", max_length=120)
    schema_version: int = pydantic.Field(description="The schema version associated with the layout definition.")
    tags: list[str] = pydantic.Field(description="The tags associated with the layout.", default_factory=list)


class UpdateLayoutRequest(pydantic.BaseModel):
    """
    Request payload to update a layout
    """

    accessibility: Union[LayoutAccessibility, NotSetType] = pydantic.Field(
        description="Controls layout accessibility between organization-wide or user-only.",
        default=NotSet,
    )
    folder: Union[str, None, NotSetType] = pydantic.Field(
        description="Folder to move this layout into; null moves it to the root, omit to leave unchanged.",
        default=NotSet,
        max_length=120,
    )
    layout_definition: Union[dict[str, Any], NotSetType] = pydantic.Field(
        description="The layout definition as a JSON object.", default=NotSet
    )
    name: Union[str, NotSetType] = pydantic.Field(description="The name of the layout.", default=NotSet, max_length=120)
    schema_version: Union[int, NotSetType] = pydantic.Field(
        description="The schema version associated with the layout definition.",
        default=NotSet,
    )

    tags: Union[list[str], NotSetType] = pydantic.Field(
        description="The tags associated with the layout.", default=NotSet
    )

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.model_validator(mode="after")
    def validate_schema_version_with_definition(self) -> "UpdateLayoutRequest":
        if not isinstance(self.layout_definition, NotSetType) and isinstance(self.schema_version, NotSetType):
            raise ValueError("schema_version must be provided when updating layout_definition")
        return self
