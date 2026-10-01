# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import datetime
import typing

from ...compat import import_optional_dependency
from ...time import (
    Time,
    TimeUnit,
    to_epoch_nanoseconds,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


def is_timestamp_like(arrow_type: "pyarrow.DataType") -> bool:
    pa = import_optional_dependency("pyarrow", "ingestion")

    return any(
        [
            pa.types.is_timestamp(arrow_type),
            pa.types.is_integer(arrow_type),
            pa.types.is_decimal(arrow_type),
            pa.types.is_floating(arrow_type),
        ],
    )


def is_timezone_aware(arrow_type: "pyarrow.DataType") -> bool:
    pa = import_optional_dependency("pyarrow", "ingestion")

    return pa.types.is_timestamp(arrow_type) and typing.cast("pyarrow.TimestampType", arrow_type).tz is not None


def time_unit_from_timestamp_type(timestamp_type: "pyarrow.TimestampType") -> TimeUnit:
    return TimeUnit(timestamp_type.unit)


@dataclasses.dataclass
class Timestamp:
    """
    The timestamp field of a Parquet file, the field holding each row's timestamp.
    Serves as both a descriptor of that field and as a utility for projecting its values to other time units.

    Note:
        This is not intended as a public API.
    """

    field: "pyarrow.Field"
    unit_hint: typing.Optional[str]
    """Unit the stored values are recorded in, used when the Arrow type does not carry one.

    Taken from the ``Unit`` metadata of the timestamp's :py:class:`~roboto.domain.topics.MessagePathRecord`,
    or from the read plan's :py:attr:`~roboto.experimental.topics.ReadPlanTimestamp.unit`.
    ``None`` when the unit is unknown.
    """
    path: tuple[str, ...]
    """Path components locating the timestamp field in the file's schema, root to leaf, through structs only."""
    column_index: int
    """The timestamp's position among the file's leaf columns,
    which is the index of its column chunk in every row group."""

    def to_epoch_nanoseconds(self, timestamp: Time) -> int:
        unit = self.__unit_from_hint()
        return to_epoch_nanoseconds(timestamp, unit)

    def unit(self) -> TimeUnit:
        pa = import_optional_dependency("pyarrow", "analytics")
        if pa.types.is_timestamp(self.field.type):
            timestamp_type = typing.cast("pyarrow.TimestampType", self.field.type)
            return TimeUnit(timestamp_type.unit)

        return self.__unit_from_hint()

    def __unit_from_hint(self) -> TimeUnit:
        unit = self.unit_hint
        if unit is None:
            raise Exception(
                f"Unable to determine timestamp unit of data in field '{self.field.name}'. "
                "This is likely an issue with Parquet ingestion, please reach out to Roboto support!"
            )

        try:
            return TimeUnit(unit)
        except ValueError:
            raise NotImplementedError(
                f"Timestamp unit '{unit}' is not supported in this Roboto SDK version. "
                "Make sure you're using the most recent Roboto SDK version. "
                "If problem persists, please reach out to Roboto support!"
            ) from None


@dataclasses.dataclass
class TimestampInfo:
    field: "pyarrow.Field"
    unit: TimeUnit
    start_time: typing.Optional[typing.Union[int, float, datetime.datetime]]
    end_time: typing.Optional[typing.Union[int, float, datetime.datetime]]

    def start_time_ns(self) -> typing.Optional[int]:
        if self.start_time is None:
            return None

        if isinstance(self.start_time, datetime.datetime):
            return int(self.start_time.timestamp() * 1_000_000_000)

        return int(self.start_time * self.unit.nano_multiplier())

    def end_time_ns(self) -> typing.Optional[int]:
        if self.end_time is None:
            return None

        if isinstance(self.end_time, datetime.datetime):
            return int(self.end_time.timestamp() * 1_000_000_000)

        return int(self.end_time * self.unit.nano_multiplier())
