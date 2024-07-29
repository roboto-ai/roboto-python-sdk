# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

# 2038-01-19Z
MAX_32BIT_EPOCH_SECONDS = 2_147_483_647


def to_epoch_nanoseconds(value: typing.Union[int, datetime.datetime]):
    """
    Takes a time value in any of the following formats, and converts it to unix epoch nanoseconds:

    * Python datetime.datetime
    * Unix epoch seconds
    * Unix epoch milliseconds
    * Unix epoch microseconds
    * Unix epoch nanoseconds
    """
    if isinstance(value, int):
        if value < 0:
            raise ValueError(
                f"Cannot convert a negative number to epoch nanoseconds, got {value}"
            )

        # Assume epoch seconds, convert to nanos
        elif 0 <= value <= MAX_32BIT_EPOCH_SECONDS:
            return value * 1_000_000_000

        # Assume epoch millis, convert to nanos
        elif value < MAX_32BIT_EPOCH_SECONDS * 1_000:
            return value * 1_000_000

        # Assume epoch micros, convert to nanos
        elif value < MAX_32BIT_EPOCH_SECONDS * 1_000_000:
            return value * 1_000

        # Already in epoch nanos
        else:
            return value

    elif isinstance(value, datetime.datetime):
        epoch = datetime.datetime(1970, 1, 1)
        return int((value - epoch).total_seconds() * 1e9)

    else:
        raise TypeError(
            "Input must be either an int (epoch nanoseconds) or a datetime.datetime object"
        )


def utcnow() -> datetime.datetime:
    """Return timezone aware datetime.datetime object, now in UTC."""
    return datetime.datetime.now(tz=datetime.timezone.utc)
