# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime

import pydantic

from .validator import (
    LifecycleStatusValidator,
    NotificationChannel,
    NotificationType,
    ReadStatus,
)


class NotificationRecord(pydantic.BaseModel, LifecycleStatusValidator):
    notification_id: str
    org_id: str
    user_id: str
    notifier_id: str
    notification_type: NotificationType
    channels: list[NotificationChannel] = pydantic.Field(default_factory=list)
    lifecycle_status: dict[NotificationChannel, str] = pydantic.Field(
        default_factory=dict
    )
    read_status: ReadStatus = ReadStatus.Unread
    created: datetime.datetime
    modified: datetime.datetime
