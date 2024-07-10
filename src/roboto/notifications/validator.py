# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from enum import Enum

import pydantic

from ..exceptions import RobotoConditionException


class NotificationType(str, Enum):
    CommentMention = "comment_mention"
    # CommentOnThread = "comment_on_thread"
    # CommentOnAuthoredAction = "comment_on_authored_action"
    # etc...


class NotificationChannel(str, Enum):
    Email = "email"
    WebUi = "web_ui"
    # Slack = "slack"
    # SMS = "sms"
    # ApplePush = "apple_push"
    # AndroidPush = "android_push"
    # etc...


class ReadStatus(str, Enum):
    Unread = "unread"
    Read = "read"


# https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-examples.html#event-publishing-retrieving-sns-subscription
class EmailLifecycleStatus(str, Enum):
    Initiated = "Initiated"  # for Roboto use only, this is not an SES status
    Send = "Send"
    Failed = "Failed"  # for Roboto use only, this is not an SES status
    Reject = "Reject"
    Bounce = "Bounce"
    Complaint = "Complaint"
    Delivery = "Delivery"
    Open = "Open"
    Click = "Click"
    RenderingFailure = "RenderingFailure"
    DeliveryDelay = "DeliveryDelay"
    Subscription = "Subscription"


class WebUiLifecycleStatus(str, Enum):
    Acknowledged = "Acknowledged"


class LifecycleStatusValidator:
    @pydantic.field_validator("lifecycle_status", mode="before")
    @classmethod
    def check_lifecycle_status(cls, value):
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
