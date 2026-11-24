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
    """Data record of a notification, as ``GET /v1/notifications`` returns it.

    A notification tells a user about something in an organization that involves them, such as a comment that
    mentions them. ``PUT /v1/notifications/{notification_id}`` and ``PUT /v1/notifications/batch`` also return it.
    Building a record raises ``RobotoConditionException`` when a ``lifecycle_status`` value is not a status of its
    channel.
    """

    notification_id: str
    """Unique ID of the notification, beginning with ``nt_``."""

    org_id: str
    """ID of the organization that owns the notification."""

    user_id: str
    """ID of the user the notification is for, which for a person is their email address."""

    notifier_id: str
    """ID of the resource that caused the notification.

    For :py:attr:`~roboto.notifications.NotificationType.CommentMention`, the ID of the comment that mentions the user.
    """

    notification_type: NotificationType
    """Kind of event the notification reports."""

    channels: list[NotificationChannel] = pydantic.Field(default_factory=list)
    """Channels Roboto sends the notification through.

    Empty when the user has turned off email notifications or comment-mention notifications.
    """

    lifecycle_status: dict[NotificationChannel, str] = pydantic.Field(default_factory=dict)
    """Delivery status of the notification on each channel, keyed by channel.

    An email's status is an :py:class:`~roboto.notifications.EmailLifecycleStatus` value, and a status in the Roboto
    web app is a :py:class:`~roboto.notifications.WebUiLifecycleStatus` value.
    """

    read_status: ReadStatus = ReadStatus.Unread
    """Whether the user has read the notification. Starts as :py:attr:`~roboto.notifications.ReadStatus.Unread`."""

    created: datetime.datetime
    """Time the notification was created."""

    modified: datetime.datetime
    """Time the notification was created. Changing its read or delivery status does not update it."""
