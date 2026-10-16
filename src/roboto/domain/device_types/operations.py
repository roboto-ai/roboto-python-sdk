# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...sentinels import NotSet, NotSetType
from ...updates import MetadataChangeset


class CreateDeviceTypeRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/device-types/create``, which creates a device type in the caller's org."""

    name: str
    """Name of the device type, unique within the org."""

    description: typing.Optional[str] = None
    """Free-text description of the device type."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Initial key-value metadata pairs to associate with the device type."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Initial tags to associate with the device type."""


class UpdateDeviceTypeRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/device-types/id/<device_type_id>``.

    Fields left at their defaults change nothing.
    """

    name: typing.Union[str, NotSetType] = NotSet
    """New name for the device type, unique within its org. Cannot be cleared."""

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New description. ``None`` clears it."""

    metadata_changeset: typing.Optional[MetadataChangeset] = None
    """Metadata fields and tags to add, change, or remove."""

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
