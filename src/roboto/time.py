# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
import decimal
import numbers
import typing

import pydantic

from .compat import StrEnum
from .logging import default_logger

log = default_logger()

MAX_32BIT_EPOCH_SECONDS = 2_147_483_647
"""Largest number of seconds since the Unix epoch a signed 32-bit integer holds: the instant 2038-01-19 03:14:07 UTC.

No SDK method reads it.
"""

NSEC_PER_SEC = 1_000_000_000
"""Number of nanoseconds in a second."""

NSEC_PER_MS = 1_000_000
"""Number of nanoseconds in a millisecond."""

NSEC_PER_US = 1_000
"""Number of nanoseconds in a microsecond."""

_SEC_PER_DAY = 86_400
_UNIX_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


Time: typing.TypeAlias = typing.Union[int, float, decimal.Decimal, str, datetime.datetime]
"""Point in time in any form ``to_epoch_nanoseconds`` accepts."""


class TimeUnit(StrEnum):
    """Unit of a timestamp in recorded data."""

    Seconds = "s"
    Milliseconds = "ms"
    Microseconds = "us"
    Nanoseconds = "ns"

    def __str__(self) -> str:
        return self.value

    def nano_multiplier(self) -> int:
        """Return the number of nanoseconds in one of this unit."""
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
    """Convert a time to nanoseconds since the Unix epoch (1970-01-01 00:00:00 UTC).

    How ``value`` is read depends on its type:

    - ``int``, or any other integer type, such as a ``numpy.int64`` read out of a NumPy or pandas column: a number of
      ``unit``, nanoseconds by default.
    - ``float``: a number of ``unit``, seconds by default. A ``float`` can lose precision, so pass a ``str`` or
      ``decimal.Decimal`` when you can.
    - ``decimal.Decimal`` or numeric ``str``: a number of ``unit``, seconds by default, such as a ROS timestamp in the
      form ``"<sec>.<nsec>"``.
    - Any other ``str``: an ISO 8601 timestamp, such as ``"2024-05-16T10:25:47Z"``, read as the ``datetime.datetime``
      it names.
    - ``datetime.datetime``: that instant. A naive datetime is read as UTC, and a datetime before 1970 converts to a
      negative number of nanoseconds.

    A fraction of a nanosecond is dropped.

    Args:
        value: Time to convert.
        unit: Unit of a numeric ``value``. ``None`` uses the default for the type of ``value``, listed above. Ignored
            for a ``datetime.datetime`` or an ISO 8601 string.

    Raises:
        TypeError: ``value`` is not one of the types above.
        ValueError: ``value`` is a ``bool`` (which Python counts as an ``int``), a negative number, NaN, or a string
            that is neither a number nor an ISO 8601 timestamp.
        OverflowError: ``value`` is infinite, such as ``float("inf")`` or ``"inf"``.

    Examples:
        An ``int`` is nanoseconds and a numeric string is seconds, unless ``unit`` says otherwise:

        >>> from roboto.time import TimeUnit, to_epoch_nanoseconds
        >>> to_epoch_nanoseconds(1_700_000_000_000_000_000)
        1700000000000000000
        >>> to_epoch_nanoseconds("1700000000.5")
        1700000000500000000
        >>> to_epoch_nanoseconds(1_700_000_000, unit=TimeUnit.Seconds)
        1700000000000000000

        An ISO 8601 string is read as the instant it names:

        >>> to_epoch_nanoseconds("2024-05-16T10:25:47Z")
        1715855147000000000
    """
    if isinstance(value, bool):
        raise ValueError(f"Expected a time, not a boolean; got {value}")

    value = _integral_to_python_int(value)

    if isinstance(value, int):
        nano_multiplier = unit.nano_multiplier() if unit is not None else TimeUnit.Nanoseconds.nano_multiplier()
        return _refuse_negative_number(value * nano_multiplier, value)

    elif isinstance(value, float):
        log.debug(
            "To avoid floating point precision loss, provide time values as strings or 'decimal.Decimal' instances."
        )
        return to_epoch_nanoseconds(str(value), unit)

    elif isinstance(value, decimal.Decimal):
        nano_multiplier = unit.nano_multiplier() if unit is not None else TimeUnit.Seconds.nano_multiplier()
        return _refuse_negative_number(int(value * nano_multiplier), value)

    elif isinstance(value, str):
        try:
            nano_multiplier = unit.nano_multiplier() if unit is not None else TimeUnit.Seconds.nano_multiplier()
            nanoseconds = int(decimal.Decimal(value) * nano_multiplier)
        except decimal.InvalidOperation:
            # Not a number, so parse it as an ISO 8601 timestamp, for which unit does not apply.
            return to_epoch_nanoseconds(_parse_iso8601(value))
        return _refuse_negative_number(nanoseconds, value)

    elif isinstance(value, datetime.datetime):
        timezone_aware = _ensure_timezone_aware(value)
        # Integer timedelta arithmetic, not timestamp() * 1e9: the float multiply rounds away the low digits, so a
        # present-day datetime 1 microsecond past a second yields `...001024` nanoseconds instead of `...001000`.
        # A datetime resolves to microseconds, so this is exact for every datetime.
        delta = timezone_aware - _UNIX_EPOCH
        return (delta.days * _SEC_PER_DAY + delta.seconds) * NSEC_PER_SEC + delta.microseconds * NSEC_PER_US

    else:
        raise TypeError(
            "Input must be either an int, float, Decimal, str (e.g., ``<sec>.<nsec>``), or a datetime instance"
        )


def _integral_to_python_int(value: typing.Any) -> typing.Any:
    if isinstance(value, numbers.Integral) and not isinstance(value, int):
        return int(value)
    return value


def _refuse_negative_number(nanoseconds: int, value: Time) -> int:
    if nanoseconds < 0:
        raise ValueError(f"Cannot convert a negative number to epoch nanoseconds, got {value}")
    return nanoseconds


def _validate_epoch_nanoseconds(value: typing.Any) -> typing.Any:
    try:
        return to_epoch_nanoseconds(value)
    except (TypeError, ArithmeticError) as exc:
        # Pydantic turns a ValueError raised here into a validation error but lets a TypeError or ArithmeticError
        # escape, so re-raise the TypeError for a non-time value (such as a JSON object) and the OverflowError for an
        # infinite value (such as "inf") as ValueError. A ValueError from to_epoch_nanoseconds passes through.
        raise ValueError(str(exc)) from exc


_EpochNanosecondsFromTime = typing.Annotated[int, pydantic.BeforeValidator(_validate_epoch_nanoseconds)]
"""Integer of nanoseconds since the Unix epoch, typed as ``int``, that a pydantic model fills from any ``Time``.

A value is converted as ``to_epoch_nanoseconds`` converts it, so an ``int`` is nanoseconds, a ``float``,
``decimal.Decimal``, or numeric string is seconds, and a ``datetime.datetime`` or ISO 8601 string is that instant. A
value that ``to_epoch_nanoseconds`` refuses fails validation with ``pydantic.ValidationError``. Negative numbers are
refused but a ``datetime.datetime`` or ISO 8601 string before 1970 is not, so a field declaring this type states any
bounds it needs, such as ``gt=0``.
"""

_NanosecondsFromInteger = typing.Annotated[int, pydantic.BeforeValidator(_integral_to_python_int)]
"""Integer of nanoseconds that takes any integer type without loss, such as a ``numpy.uint64`` from a NumPy column.

Pydantic's ``int`` validation takes a NumPy integer through a 64-bit float, which rounds a present-day time since the
Unix epoch to a multiple of 256 nanoseconds. This type gives pydantic a Python ``int`` instead, and every other value
is validated as for ``int``: unlike ``_EpochNanosecondsFromTime``, it reads no value as seconds and refuses no negative
number.
"""


def utcnow() -> datetime.datetime:
    """Return the current time as a timezone-aware ``datetime.datetime`` in UTC."""
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _ensure_timezone_aware(dt: datetime.datetime) -> datetime.datetime:
    """Return ``dt``, read as UTC if it has no time zone."""

    if _is_timezone_aware(dt):
        return dt

    return dt.replace(tzinfo=datetime.timezone.utc)


def _parse_iso8601(value: str) -> datetime.datetime:
    # The Z -> +00:00 swap is for Python 3.10; 3.11+ accepts Z natively.
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.datetime.fromisoformat(candidate)


# Python's definition of an aware datetime:
# https://docs.python.org/3.10/library/datetime.html#determining-if-an-object-is-aware-or-naive
def _is_timezone_aware(dt: datetime.datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None
