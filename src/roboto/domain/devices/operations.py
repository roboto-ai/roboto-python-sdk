# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...updates import MetadataChangeset


class CreateDeviceRequest(pydantic.BaseModel):
    """Request payload to create a new device.

    This request is used to register a new device with the Roboto platform.
    The device will be associated with the specified organization and can
    subsequently be used for authentication and data operations.
    """

    device_id: str
    """A user-provided identifier for a device, which is unique within that device's org."""

    org_id: typing.Optional[str] = None
    """The org to which this device belongs. If None, the device will be registered
    under the caller's organization (if they belong to only one org) or an error
    will be raised if the caller belongs to multiple organizations."""

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this device for discovery and search, e.g. "
        + "`{ 'model': 'mk2', 'serial_number': 'SN001234' }`",
    )
    """Key-value metadata pairs to associate with the device for discovery and search."""

    tags: list[str] = pydantic.Field(
        default_factory=list,
        description="Initial tags to associate with this device for discovery and search, e.g. "
        + "`['production', 'warehouse-a']`",
    )
    """List of tags for device discovery and organization."""


class UpdateDeviceRequest(pydantic.BaseModel):
    """Request payload for updating device properties.

    Used to modify device metadata and tags. Supports granular updates
    through metadata changesets that can add, update, or remove specific
    fields and tags without affecting other properties.
    """

    metadata_changeset: typing.Optional[MetadataChangeset] = None
    """Metadata changes to apply (add, update, or remove fields/tags)."""
