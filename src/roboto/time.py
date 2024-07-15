# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime


def utcnow() -> datetime.datetime:
    """Return timezone aware datetime.datetime object, now in UTC."""
    return datetime.datetime.now(tz=datetime.timezone.utc)
