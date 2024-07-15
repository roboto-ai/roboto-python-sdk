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
    notification_id: str
    read_status: Optional[ReadStatus] = None
    lifecycle_status: Optional[dict[NotificationChannel, str]] = None
