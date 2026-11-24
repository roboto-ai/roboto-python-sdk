# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from .record import (
    NotificationChannel,
    ReadStatus,
)
from .validator import LifecycleStatusValidator


class UpdateNotificationRequest(pydantic.BaseModel, LifecycleStatusValidator):
    """Request body for ``PUT /v1/notifications/{notification_id}``.

    Updates one notification's read or delivery status. It is also an item of ``requests`` in the request body of
    ``PUT /v1/notifications/batch``. A field left ``None`` is unchanged. Building the request raises
    ``RobotoConditionException`` when a ``lifecycle_status`` value is not a status of its channel.
    """

    notification_id: str
    """ID of the notification to update.

    As the body of ``PUT /v1/notifications/{notification_id}``, an ID that differs from the path's raises
    ``RobotoInvalidRequestException``.
    """

    read_status: Optional[ReadStatus] = None
    """Read status to set."""

    lifecycle_status: Optional[dict[NotificationChannel, str]] = None
    """Delivery status to set on each channel, keyed by channel.

    Channels left out keep their status. Each value is a status of its channel, as in
    :py:attr:`~roboto.notifications.NotificationRecord.lifecycle_status`.

    Leaving it at its default of ``None`` leaves every channel unchanged, but building the request with ``None`` passed
    explicitly raises ``AttributeError``. Roboto fails the same way on a ``null`` value in a request body, and
    :py:meth:`~roboto.notifications.NotificationsClient.batch_update_notifications` sends ``null`` for each update that
    leaves it unset.
    """
