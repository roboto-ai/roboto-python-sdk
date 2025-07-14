# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Device management for the Roboto platform.

This module provides functionality for managing devices - non-human entities that can
interact with Roboto on behalf of organizations. Devices are typically robots or
other systems that upload data to the platform.

The main components are:
- :py:class:`Device`: Core device entity for registration, token management, and operations
- :py:class:`DeviceRecord`: Wire-transmissible representation of device data
- :py:class:`CreateDeviceRequest`: Request payload for device registration

Devices are identified by unique device IDs within their organization and can be
assigned API tokens for authentication. They serve as the primary mechanism for
automated data ingestion and platform interaction.
"""

from .device import Device
from .operations import CreateDeviceRequest
from .record import DeviceRecord

__all__ = [
    "CreateDeviceRequest",
    "Device",
    "DeviceRecord",
]
