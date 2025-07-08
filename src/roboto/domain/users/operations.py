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
    """Request payload to create a new user."""

    user_id: str
    """Unique identifier for the user, typically an email address."""

    name: Optional[str] = None
    """Human-readable display name for the user."""

    is_service_user: bool = False
    """Whether this is a service user for automated operations."""

    is_system_user: bool = False
    """Whether this is a system user for internal platform operations."""

    picture_url: Optional[str] = None
    """URL to the user's profile picture."""

    default_notification_channels: Optional[list[NotificationChannel]] = [
        NotificationChannel.Email
    ]
    """Default notification channels to enable for the user."""

    default_notification_types: Optional[list[NotificationType]] = [
        NotificationType.CommentMention
    ]
    """Default notification types to enable for the user."""


class UpdateUserRequest(pydantic.BaseModel):
    """Request payload to update an existing user."""

    name: Optional[str] = None
    """Updated display name for the user."""

    picture_url: Optional[str] = None
    """Updated URL to the user's profile picture."""

    notification_channels_enabled: Optional[dict[NotificationChannel, bool]] = None
    """Updated notification channel preferences."""

    notification_types_enabled: Optional[dict[NotificationType, bool]] = None
    """Updated notification type preferences."""
