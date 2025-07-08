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
    """A wire-transmissible representation of a user."""

    user_id: str
    """Unique identifier for the user, typically an email address."""

    is_service_user: bool = False
    """Whether this is a service user for automated operations.

    Service users can be used to perform actions on behalf of customers.
    For example, a service user can be associated with a Trigger,
    which will then invoke its corresponding Action as the service user.
    """

    is_system_user: Optional[bool] = False
    """Whether this is a system user for internal platform operations."""

    name: Optional[str] = None
    """Human-readable display name for the user."""

    picture_url: Optional[str] = None
    """URL to the user's profile picture."""

    notification_channels_enabled: dict[NotificationChannel, bool] = pydantic.Field(
        default_factory=dict
    )
    """Mapping of notification channels to their enabled/disabled status."""

    notification_types_enabled: dict[NotificationType, bool] = pydantic.Field(
        default_factory=dict
    )
    """Mapping of notification types to their enabled/disabled status."""

    def is_email_notifications_enabled(self) -> bool:
        return self.notification_channels_enabled.get(NotificationChannel.Email, False)

    def is_comment_mentions_enabled(self) -> bool:
        return self.notification_types_enabled.get(
            NotificationType.CommentMention, False
        )
