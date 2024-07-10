# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from roboto.notifications import (
    NotificationChannel,
    NotificationType,
)


class CreateUserRequest(pydantic.BaseModel):
    user_id: str
    name: Optional[str] = None
    is_service_user: bool = False
    is_system_user: bool = False
    picture_url: Optional[str] = None
    default_notification_channels: Optional[list[NotificationChannel]] = [
        NotificationChannel.Email
    ]
    default_notification_types: Optional[list[NotificationType]] = [
        NotificationType.CommentMention
    ]


class UpdateUserRequest(pydantic.BaseModel):
    name: Optional[str] = None
    picture_url: Optional[str] = None
    notification_channels_enabled: Optional[dict[NotificationChannel, bool]] = None
    notification_types_enabled: Optional[dict[NotificationType, bool]] = None
