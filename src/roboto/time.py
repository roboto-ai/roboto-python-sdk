# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import decimal
import typing

# 2038-01-19Z
MAX_32BIT_EPOCH_SECONDS = 2_147_483_647
NSEC_PER_SEC = 1_000_000_000


Time: typing.TypeAlias = typing.Union[int, decimal.Decimal, str, datetime.datetime]


def to_epoch_nanoseconds(value: Time):
    """
    Takes a time value in any of the following formats, and converts it to unix epoch nanoseconds:

    * datetime.datetime
    * int: Unix epoch nanoseconds
    * str: ROS formatted timestamp in the form of "<sec>.<nsec>"
    * decimal.Decimal: ROS formatted timestamp in the form of decimal.Decimal("<sec>.<nsec>")
    """
    if isinstance(value, int):
        if value < 0:
            raise ValueError(
                f"Cannot convert a negative number to epoch nanoseconds, got {value}"
            )
        else:
            return value

    elif isinstance(value, decimal.Decimal):
        # Assume value is a ROS formatted timestamp, <sec>.<nsec>
        return int(value * NSEC_PER_SEC)

    elif isinstance(value, str):
        # Assume value is a ROS formatted timestamp, <sec>.<nsec>
        return int(decimal.Decimal(value) * NSEC_PER_SEC)

    elif isinstance(value, datetime.datetime):
        timezone_aware = _ensure_timezone_aware(value)
        return int(timezone_aware.timestamp() * NSEC_PER_SEC)

    else:
        raise TypeError(
            "Input must be either an int (epoch nanoseconds), string (`<sec>.<nsec>`) or a datetime.datetime object"
        )


def utcnow() -> datetime.datetime:
    """Return timezone aware datetime.datetime object, now in UTC."""
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _ensure_timezone_aware(dt: datetime.datetime) -> datetime.datetime:
    """Defaults a non-timezone-aware datetime to UTC"""

    if _is_timezone_aware(dt):
        return dt

    return dt.replace(tzinfo=datetime.timezone.utc)


# https://docs.python.org/3.10/library/datetime.html#determining-if-an-object-is-aware-or-naive
def _is_timezone_aware(dt: datetime.datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None
