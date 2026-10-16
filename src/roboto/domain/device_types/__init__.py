# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Device types: named kinds of device within an organization, such as one robot model.

A device has at most one device type, whose ID is in
:py:attr:`~roboto.domain.devices.DeviceRecord.device_type_id`.
"""

from .device_type import DeviceType
from .operations import (
    CreateDeviceTypeRequest,
    UpdateDeviceTypeRequest,
)
from .record import DeviceTypeRecord

__all__ = [
    "CreateDeviceTypeRequest",
    "DeviceType",
    "DeviceTypeRecord",
    "UpdateDeviceTypeRequest",
]
