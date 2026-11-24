# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Notifications: messages that tell a user about something in an organization that involves them, such as a mention.

:py:class:`~roboto.notifications.NotificationRecord` holds a notification and whether it has been read and delivered by
email and in the Roboto web app, and :py:class:`~roboto.notifications.UpdateNotificationRequest` changes those statuses.
"""

from .http_client import NotificationsClient
from .http_resources import (
    UpdateNotificationRequest,
)
from .record import NotificationRecord
from .validator import (
    EmailLifecycleStatus,
    NotificationChannel,
    NotificationType,
    ReadStatus,
    WebUiLifecycleStatus,
)

__all__ = [
    "NotificationType",
    "NotificationChannel",
    "NotificationsClient",
    "NotificationRecord",
    "ReadStatus",
    "UpdateNotificationRequest",
    "EmailLifecycleStatus",
    "WebUiLifecycleStatus",
]
