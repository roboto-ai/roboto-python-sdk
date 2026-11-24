# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Devices: robots, upload stations, or other non-human entities that interact with Roboto on behalf of an organization.

Use :py:class:`~roboto.domain.devices.Device` to register and find devices, create the access tokens they
authenticate with, and record their sessions.
"""

from .device import Device
from .operations import (
    INVALID_DEVICE_ID_MESSAGE,
    CreateDeviceRequest,
    UpdateDeviceRequest,
    validate_device_id,
)
from .record import DeviceRecord

__all__ = [
    "INVALID_DEVICE_ID_MESSAGE",
    "CreateDeviceRequest",
    "Device",
    "DeviceRecord",
    "UpdateDeviceRequest",
    "validate_device_id",
]
