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
    """Request body for ``DeviceType.create``."""

    name: str
    """Human-readable name of the device type, unique within its organization.

    A name already taken raises ``RobotoConflictException``.
    """

    description: typing.Optional[str] = None
    """Human-readable description of the device type."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the device type. Defaults to none."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the device type. Defaults to none."""


class UpdateDeviceTypeRequest(pydantic.BaseModel):
    """Request body for ``DeviceType.update``.

    A field left at its default (``NotSet`` or ``None``) is unchanged.
    """

    name: typing.Union[str, NotSetType] = NotSet
    """Human-readable name of the device type, unique within its organization. It cannot be cleared.

    A name already taken raises ``RobotoConflictException``.
    """

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """Human-readable description of the device type. ``None`` clears it."""

    metadata_changeset: typing.Optional[MetadataChangeset] = None
    """Changes to the device type's tags and metadata."""

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
