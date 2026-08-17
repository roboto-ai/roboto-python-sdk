# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...query import QueryTarget
from ...sentinels import (
    NotSet,
    NotSetType,
)
from .record import ViewDefinition

MAX_VIEW_NAME_LENGTH: typing.Final[int] = 120
"""Longest permitted View name, matching the limit layouts uses."""


class CreateViewRequest(pydantic.BaseModel):
    """Request payload to create a View."""

    name: str = pydantic.Field(min_length=1, max_length=MAX_VIEW_NAME_LENGTH)
    """Display name. Need not be unique."""

    target: QueryTarget
    """The resource type this View searches. Cannot be changed afterwards."""

    definition: ViewDefinition
    """The query and presentation state to save."""


class UpdateViewRequest(pydantic.BaseModel):
    """Request payload to update a View.

    Omitted fields are left unchanged. ``target`` is absent by design: a View's conditions are
    written against one resource type, so retargeting it would leave them referring to fields
    the new target does not have. Create a new View instead.
    """

    name: typing.Union[str, NotSetType] = pydantic.Field(
        default=NotSet,
        min_length=1,
        max_length=MAX_VIEW_NAME_LENGTH,
    )
    """New display name, or ``NotSet`` to leave it alone."""

    definition: typing.Union[ViewDefinition, NotSetType] = NotSet
    """Replacement query and presentation state, or ``NotSet`` to leave it alone.

    Replaces the definition wholesale rather than merging, so a caller changing one filter must
    send the whole definition back.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)
