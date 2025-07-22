# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
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
        unit = self.message_path.metadata.get(
            MessagePathMetadataWellKnown.Unit.value, None
        )
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
