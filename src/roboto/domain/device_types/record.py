# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic


class DeviceTypeRecord(pydantic.BaseModel):
    """Data record of a device type, as the Roboto API returns it.

    A device type is a named kind of device within an organization, such as one robot model.
    ``DeviceType`` wraps this record with methods that act on the device type, and exposes it as ``DeviceType.record``.
    """

    device_type_id: str
    """Unique ID of the device type, beginning with ``dt_``."""

    org_id: str
    """ID of the organization that owns the device type."""

    name: str
    """Human-readable name of the device type, unique within its organization."""

    description: typing.Optional[str] = None
    """Human-readable description of the device type, or ``None`` if it has none."""

    device_count: int
    """Number of devices of this device type, counted when Roboto returned this record."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the device type."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the device type."""

    created: datetime.datetime
    """Time the device type was created."""

    created_by: str
    """Principal that created the device type, as ``<type>:<id>``, such as ``user:<user_id>``."""

    modified: datetime.datetime
    """Time the device type was last modified."""

    modified_by: str
    """Principal that last modified the device type, in the same ``<type>:<id>`` form as ``created_by``."""
