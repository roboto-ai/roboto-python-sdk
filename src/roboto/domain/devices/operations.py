# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic


class CreateDeviceRequest(pydantic.BaseModel):
    device_id: str = pydantic.Field(
        description="A user-provided identifier for a device, which is unique within that device's org."
    )
    org_id: typing.Optional[str] = pydantic.Field(
        description="The org to which this device belongs.", default=None
    )
