# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic


class DeviceTypeRecord(pydantic.BaseModel):
    """A device type as returned by Roboto."""

    device_type_id: str
    """A Roboto-assigned identifier for this device type (``dt_...``), unique across all orgs and never changed."""

    org_id: str
    """The org to which this device type belongs."""

    name: str
    """A user-provided name for this device type, unique within its org."""

    description: typing.Optional[str] = None
    """Free-text description of this device type."""

    device_count: int
    """Number of devices of this device type, counted when Roboto returned this record."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata pairs associated with this device type."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """List of tags associated with this device type."""

    created: datetime.datetime
    """Date/time when this device type was created."""

    created_by: str
    """The user who created this device type."""

    modified: datetime.datetime
    """Date/time when this device type was last modified."""

    modified_by: str
    """The user who last modified this device type."""
