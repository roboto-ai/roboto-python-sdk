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
    """Return whether ``arrow_type`` can hold a timestamp: a timestamp, integer, decimal or floating-point type.

    Args:
        arrow_type: Arrow type to check.
    """
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
    """Return whether ``arrow_type`` is an Arrow timestamp type with a time zone.

    Args:
        arrow_type: Arrow type to check.
    """
    pa = import_optional_dependency("pyarrow", "ingestion")

    return pa.types.is_timestamp(arrow_type) and typing.cast("pyarrow.TimestampType", arrow_type).tz is not None


def time_unit_from_timestamp_type(timestamp_type: "pyarrow.TimestampType") -> TimeUnit:
    """Return the unit an Arrow timestamp type records its values in.

    Args:
        timestamp_type: Arrow timestamp type to read the unit of.
    """
    return TimeUnit(timestamp_type.unit)


@dataclasses.dataclass
class Timestamp:
    """Timestamp field of a Parquet file: the field that holds each row's timestamp, and the unit of its values.

    The SDK's own code uses it; to read a topic's data, use :py:meth:`~roboto.domain.topics.Topic.get_data` instead.
    :py:func:`~roboto.formats.parquet.extract_timestamp_field` builds it,
    :py:func:`~roboto.formats.parquet.should_read_row_group` takes it to skip row groups outside a time range, and
    :py:func:`~roboto.formats.parquet.extract_timestamps` takes it to convert the field's values to nanoseconds since
    the Unix epoch.
    """

    field: "pyarrow.Field"
    """Arrow field that holds the timestamp, found at ``path`` in the file's schema."""

    unit_hint: typing.Optional[str]
    """Unit of the stored values, or ``None`` if it is unknown.

    A :py:class:`~roboto.time.TimeUnit` value, such as ``"ms"``. ``unit`` reads it when the field's Arrow type
    carries no unit, as with an integer, decimal or floating-point field. Callers take it from the timestamp message
    path's :py:attr:`~roboto.domain.topics.MessagePathMetadataWellKnown.Unit` metadata, or from
    ``roboto.experimental.topics.ReadPlanTimestamp.unit``.
    """

    path: tuple[str, ...]
    """Names of the fields that lead from the schema's root to the timestamp field, through structs only."""

    column_index: int
    """Index of the timestamp's column chunk in every row group: its position among the file's leaf columns."""

    def to_epoch_nanoseconds(self, timestamp: Time) -> int:
        """Convert a value of the timestamp field to nanoseconds since the Unix epoch.

        A numeric ``timestamp`` is read as a number of ``unit_hint``, even when the field's Arrow type carries its own
        unit. :py:func:`~roboto.time.to_epoch_nanoseconds` does the conversion, and its failures also apply.

        Args:
            timestamp: Value of the timestamp field, such as the minimum or maximum in a row group's statistics.

        Raises:
            Exception: ``unit_hint`` is ``None``.
            NotImplementedError: ``unit_hint`` is not a :py:class:`~roboto.time.TimeUnit` value.
        """
        unit = self.__unit_from_hint()
        return to_epoch_nanoseconds(timestamp, unit)

    def unit(self) -> TimeUnit:
        """Return the unit of the timestamp's values.

        The unit comes from the field's Arrow type when it is a timestamp type, and from ``unit_hint`` otherwise.

        Raises:
            Exception: The field's Arrow type is not a timestamp type and ``unit_hint`` is ``None``.
            NotImplementedError: The unit is read from ``unit_hint``, which is not a :py:class:`~roboto.time.TimeUnit`
                value.
        """
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
    """Timestamp column of a Parquet file being stored as a topic, with its unit and the range of its values.

    :py:meth:`~roboto.formats.parquet.ParquetParser.extract_timestamp_info` returns it, and
    :py:func:`~roboto.formats.parquet.generate_message_path_requests` takes it.
    :py:meth:`~roboto.domain.topics.Topic.create_from_df` uses both to set a new topic's message paths and time range.
    Import it from ``roboto.formats.parquet.timestamp``.
    """

    field: "pyarrow.Field"
    """Arrow field of the timestamp column."""

    unit: TimeUnit
    """Unit of the column's values."""

    start_time: typing.Optional[typing.Union[int, float, datetime.datetime]]
    """Earliest value in the column, or ``None`` if the column holds no values.

    A ``datetime.datetime`` or a number of ``unit``.
    """

    end_time: typing.Optional[typing.Union[int, float, datetime.datetime]]
    """Latest value in the column, in the same form as ``start_time``, or ``None`` if the column holds no values."""

    def start_time_ns(self) -> typing.Optional[int]:
        """Return ``start_time`` in nanoseconds since the Unix epoch, or ``None`` if it is ``None``.

        A ``datetime.datetime`` is converted through a floating-point number of seconds, so the result can be off by a
        few hundred nanoseconds. A fraction of a nanosecond is dropped.
        """
        if self.start_time is None:
            return None

        if isinstance(self.start_time, datetime.datetime):
            return int(self.start_time.timestamp() * 1_000_000_000)

        return int(self.start_time * self.unit.nano_multiplier())

    def end_time_ns(self) -> typing.Optional[int]:
        """Return ``end_time`` in nanoseconds since the Unix epoch, or ``None`` if it is ``None``.

        It is converted the same way as by ``start_time_ns``.
        """
        if self.end_time is None:
            return None

        if isinstance(self.end_time, datetime.datetime):
            return int(self.end_time.timestamp() * 1_000_000_000)

        return int(self.end_time * self.unit.nano_multiplier())
