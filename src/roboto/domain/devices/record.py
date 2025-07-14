# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime

import pydantic


class DeviceRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a device.

    This record contains all the essential information about a device that can be
    transmitted over the network. It includes metadata about when the device was
    created and modified, along with its organizational association.
    """

    created: datetime.datetime
    """Date/time when this device was registered."""

    created_by: str
    """The user who registered this device."""

    device_id: str
    """A user-provided identifier for a device, which is unique within that device's org."""

    modified: datetime.datetime
    """Date/time when this device record was last modified."""

    modified_by: str
    """The user who last modified this device record."""

    org_id: str
    """The org to which this device belongs."""
