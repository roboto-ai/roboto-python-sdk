# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic


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
