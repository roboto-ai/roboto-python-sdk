# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import pydantic

from ..compat import StrEnum
from ..exceptions import RobotoConditionException


class NotificationType(StrEnum):
    """Kind of event a notification reports."""

    CommentMention = "comment_mention"
    """A comment mentions the user."""


class NotificationChannel(StrEnum):
    """Channel Roboto sends a notification through."""

    Email = "email"
    """Email to the user's email address."""

    WebUi = "web_ui"
    """Notifications menu in the Roboto web app."""


class ReadStatus(StrEnum):
    """Read status of a notification: whether its user has read it."""

    Unread = "unread"
    Read = "read"


class EmailLifecycleStatus(StrEnum):
    """Delivery status of a notification's email: the latest event Roboto has recorded for the email."""

    Initiated = "Initiated"
    """Roboto created the notification and has recorded no event for its email yet."""

    Send = "Send"
    """The email was accepted for sending."""

    Failed = "Failed"
    """Roboto could not send the email."""

    Reject = "Reject"
    """The email was accepted for sending but not delivered, because it contained a virus."""

    Bounce = "Bounce"
    """The recipient's mail server rejected the email."""

    Complaint = "Complaint"
    """The email was delivered, and the recipient marked it as spam."""

    Delivery = "Delivery"
    """The recipient's mail server accepted the email."""

    Open = "Open"
    """The recipient opened the email."""

    Click = "Click"
    """The recipient clicked a link in the email."""

    RenderingFailure = "RenderingFailure"
    """The email was not sent because its template could not be rendered."""

    DeliveryDelay = "DeliveryDelay"
    """A temporary problem delayed delivery of the email."""

    Subscription = "Subscription"
    """The email was delivered, and the recipient changed their subscription preferences from it."""


class WebUiLifecycleStatus(StrEnum):
    """Status of a notification in the Roboto web app."""

    Acknowledged = "Acknowledged"
    """The user opened the notifications menu while the notification was in it.

    An acknowledged notification no longer counts toward the number on the notifications icon.
    """


class LifecycleStatusValidator:
    """Mixin for a pydantic model with a ``lifecycle_status`` field, which checks each status against its channel.

    :py:class:`~roboto.notifications.NotificationRecord` and
    :py:class:`~roboto.notifications.UpdateNotificationRequest` use it. Building such a model raises
    ``RobotoConditionException`` when an email status is not an ``EmailLifecycleStatus`` value, or a status in the
    Roboto web app is not a ``WebUiLifecycleStatus`` value.
    """

    @pydantic.field_validator("lifecycle_status", mode="before")
    @classmethod
    def check_lifecycle_status(cls, value):
        """Reject a ``lifecycle_status`` that holds a status not valid for its channel."""
        for channel, status in value.items():
            if channel == NotificationChannel.Email:
                try:
                    EmailLifecycleStatus(status)
                except ValueError:
                    raise RobotoConditionException(
                        f"Invalid status: {status}. Must be one of {EmailLifecycleStatus.__members__.keys()}"
                    )
            elif channel == NotificationChannel.WebUi:
                try:
                    WebUiLifecycleStatus(status)
                except ValueError:
                    raise RobotoConditionException(
                        f"Invalid status: {status}. Must be one of {WebUiLifecycleStatus.__members__.keys()}"
                    )

        return value
