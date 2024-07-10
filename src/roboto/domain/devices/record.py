# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime

import pydantic


class DeviceRecord(pydantic.BaseModel):
    created: datetime.datetime = pydantic.Field(
        description="Date/time when this device was registered."
    )
    created_by: str = pydantic.Field(description="The user who registered this device.")
    device_id: str = pydantic.Field(
        description="A user-provided identifier for a device, which is unique within that device's org."
    )
    modified: datetime.datetime = pydantic.Field(
        description="Date/time when this device record was last modified."
    )
    modified_by: str = pydantic.Field(
        description="The user who last modified this device record."
    )
    org_id: str = pydantic.Field(description="The org to which this device belongs.")
