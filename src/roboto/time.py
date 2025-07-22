# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
import decimal
import enum
import typing

from .logging import default_logger

log = default_logger()

# 2038-01-19Z
MAX_32BIT_EPOCH_SECONDS = 2_147_483_647
NSEC_PER_SEC = 1_000_000_000
NSEC_PER_MS = 1_000_000
NSEC_PER_US = 1_000


Time: typing.TypeAlias = typing.Union[
    int, float, decimal.Decimal, str, datetime.datetime
]


class TimeUnit(str, enum.Enum):
    """
    Well-known time units supported for timestamps in recording data.
    """

    Seconds = "s"
    Milliseconds = "ms"
    Microseconds = "us"
    Nanoseconds = "ns"

    def nano_multiplier(self) -> int:
        if self == TimeUnit.Seconds:
            return NSEC_PER_SEC
        if self == TimeUnit.Milliseconds:
            return NSEC_PER_MS
        if self == TimeUnit.Microseconds:
            return NSEC_PER_US
        if self == TimeUnit.Nanoseconds:
            return 1
        raise ValueError(f"Unknown timestamp unit: {self}")


def to_epoch_nanoseconds(value: Time, unit: typing.Optional[TimeUnit] = None):
    """
    Convert a time value to nanoseconds since Unix epoch (1970-01-01 00:00:00 UTC).
    Accepts various input formats (int, float, Decimal, str, datetime) and time units
    (seconds, milliseconds, microseconds, nanoseconds).

    Notes:
        * ``int`` formatted ``value``:
            - If not provided, ``unit`` defaults to :py:attr:`~roboto.time.TimeUnit.Nanoseconds`.
        * ``float`` formatted ``value``:
            - Not recommended due to potential for precision loss.
              If possible, pass ``value`` as ``str`` or ``decimal.Decimal`` instead.
            - If not provided, ``unit`` defaults to :py:attr:`~roboto.time.TimeUnit.Seconds`.
        * ``decimal.Decimal`` formatted ``value``:
            - If not provided, ``unit`` defaults to :py:attr:`~roboto.time.TimeUnit.Seconds`.
            - E.g., a ROS formatted timestamp in the form of decimal.Decimal("<sec>.<nsec>")).
        * ``str`` formatted ``value``:
            - If not provided, ``unit`` defaults to :py:attr:`~roboto.time.TimeUnit.Seconds`.
            - E.g., a ROS formatted timestamp in the form of "<sec>.<nsec>").
        * ``datetime.datetime`` formatted ``value``:
            - ``unit``, if provided, is ignored.
              Datetimes are always converted from seconds to nanoseconds.
    """
    if isinstance(value, int):
        nano_multiplier = (
            unit.nano_multiplier()
            if unit is not None
            else TimeUnit.Nanoseconds.nano_multiplier()
        )
        if value < 0:
            raise ValueError(
                f"Cannot convert a negative number to epoch nanoseconds, got {value}"
            )
        else:
            return value * nano_multiplier

    elif isinstance(value, float):
        log.debug(
            "To avoid floating point precision loss, provide time values as strings or 'decimal.Decimal' instances."
        )
        return to_epoch_nanoseconds(str(value), unit)

    elif isinstance(value, decimal.Decimal):
        # E.g., a ROS formatted timestamp, `<sec>.<nsec>`
        nano_multiplier = (
            unit.nano_multiplier()
            if unit is not None
            else TimeUnit.Seconds.nano_multiplier()
        )
        return int(value * nano_multiplier)

    elif isinstance(value, str):
        # E.g., a ROS formatted timestamp `<sec>.<nsec>`
        nano_multiplier = (
            unit.nano_multiplier()
            if unit is not None
            else TimeUnit.Seconds.nano_multiplier()
        )
        return int(decimal.Decimal(value) * nano_multiplier)

    elif isinstance(value, datetime.datetime):
        timezone_aware = _ensure_timezone_aware(value)
        return int(
            # datetime::timestamp is always seconds
            timezone_aware.timestamp()
            * TimeUnit.Seconds.nano_multiplier()
        )

    else:
        raise TypeError(
            "Input must be either an int, float, Decimal, str (e.g., ``<sec>.<nsec>``), or a datetime instance"
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
