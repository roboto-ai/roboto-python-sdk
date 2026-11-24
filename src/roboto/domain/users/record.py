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
    """Data record of a user, as the Roboto API returns it.

    A user is a person, or a service user that Roboto runs automated work as, who acts in the organizations it
    belongs to. :py:class:`~roboto.domain.users.User` wraps this record with methods that act on the user, and exposes
    it as :py:attr:`~roboto.domain.users.User.record`.
    """

    user_id: str
    """Unique ID of the user, which for a person is their email address in lowercase."""

    is_service_user: bool = False
    """Whether the user is a service user: a non-human user that Roboto runs an organization's automated work as.

    For example, a trigger invokes its action as a service user of the trigger's organization, so the invocation has
    that service user's access.
    """

    is_system_user: Optional[bool] = False
    """Whether the user is Roboto staff, such as a Roboto administrator."""

    name: Optional[str] = None
    """Human-readable display name of the user, or ``None`` if it has none."""

    picture_url: Optional[str] = None
    """URL of the user's profile picture, or ``None`` if it has none."""

    notification_channels_enabled: dict[NotificationChannel, bool] = pydantic.Field(default_factory=dict)
    """Whether each notification channel is enabled for the user, keyed by channel. An absent channel is disabled."""

    notification_types_enabled: dict[NotificationType, bool] = pydantic.Field(default_factory=dict)
    """Whether each notification type is enabled for the user, keyed by type. An absent type is disabled."""

    def is_email_notifications_enabled(self) -> bool:
        """Return whether the user has the email notification channel enabled."""
        return self.notification_channels_enabled.get(NotificationChannel.Email, False)

    def is_comment_mentions_enabled(self) -> bool:
        """Return whether the user has notifications enabled for comments that mention them.

        Roboto emails the user about such a comment only when ``is_email_notifications_enabled`` also returns ``True``.
        """
        return self.notification_types_enabled.get(NotificationType.CommentMention, False)
