# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import datetime
import typing

from ....compat import import_optional_dependency
from ....time import (
    Time,
    TimeUnit,
    to_epoch_nanoseconds,
)
from ..record import (
    MessagePathMetadataWellKnown,
    MessagePathRecord,
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
    Timestamp signal in topic data stored as Parquet.
    Serves as both a descriptor of that signal and as a utility for projecting it to other time units.

    Note:
        This is not intended as a public API.
    """

    field: "pyarrow.Field"
    message_path: MessagePathRecord

    def to_epoch_nanoseconds(self, timestamp: Time) -> int:
        unit = self.__unit_from_message_path_metadata()
        return to_epoch_nanoseconds(timestamp, unit)

    def unit(self) -> TimeUnit:
        pa = import_optional_dependency("pyarrow", "analytics")
        if pa.types.is_timestamp(self.field.type):
            timestamp_type = typing.cast("pyarrow.TimestampType", self.field.type)
            return TimeUnit(timestamp_type.unit)

        return self.__unit_from_message_path_metadata()

    def __unit_from_message_path_metadata(self) -> TimeUnit:
        unit = self.message_path.metadata.get(MessagePathMetadataWellKnown.Unit.value, None)
        if unit is None:
            raise Exception(
                f"Unable to determine timestamp unit of data in field '{self.message_path.source_path}'. "
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
