# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from ...notifications import (
    NotificationChannel,
    NotificationType,
)


class UserRecord(pydantic.BaseModel):
    user_id: str
    is_service_user: bool = False
    """
    A service user can be used to perform actions on behalf of customers.
    For example, a service user can be associated with a Trigger,
    which will then invoke its corresponding Action as the service user.
    """

    is_system_user: Optional[bool] = False

    name: Optional[str] = None
    picture_url: Optional[str] = None
    notification_channels_enabled: dict[NotificationChannel, bool] = pydantic.Field(
        default_factory=dict
    )
    notification_types_enabled: dict[NotificationType, bool] = pydantic.Field(
        default_factory=dict
    )

    def is_email_notifications_enabled(self) -> bool:
        return self.notification_channels_enabled.get(NotificationChannel.Email, False)

    def is_comment_mentions_enabled(self) -> bool:
        return self.notification_types_enabled.get(
            NotificationType.CommentMention, False
        )
