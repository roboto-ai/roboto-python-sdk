# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import statistics
import typing

from ....compat import import_optional_dependency
from ....exceptions import (
    IngestionException,
    TimestampFieldNotFoundException,
)
from ....logging import default_logger
from ....time import TimeUnit
from .timestamp import (
    TimestampInfo,
    is_timestamp_like,
    is_timezone_aware,
    time_unit_from_timestamp_type,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


logger = default_logger()


class ParquetParser:
    __file: "pyarrow.parquet.ParquetFile"
    __min_required_row_group_size: int
    __schema: "pyarrow.Schema"
    __small_row_group_count_threshold: int

    @staticmethod
    def is_parquet_file(path: pathlib.Path) -> bool:
        try:
            with path.open("rb") as f:
                magic_bytes = f.read(4)
                return magic_bytes == b"PAR1"
        except (FileNotFoundError, IOError, OSError):
            # If we can't read the file, fall back to extension-based detection
            return path.suffix.lower() == ".parquet"

    def __init__(
        self,
        source: pathlib.Path,
        min_required_row_group_size: int = 100_000,
        small_row_group_count_threshold: int = 32,
    ):
        pq = import_optional_dependency("pyarrow.parquet", "ingestion")

        self.__file = pq.ParquetFile(source)
        self.__min_required_row_group_size = min_required_row_group_size
        self.__schema = self.__file.schema_arrow
        self.__small_row_group_count_threshold = small_row_group_count_threshold

    @property
    def column_count(self) -> int:
        return self.__file.metadata.num_columns

    @property
    def fields(self) -> typing.Generator["pyarrow.Field", None, None]:
        yield from self.__schema

    @property
    def row_count(self) -> int:
        return self.__file.metadata.num_rows

    @property
    def row_group_count(self) -> int:
        return self.__file.metadata.num_row_groups

    @property
    def row_group_size(self) -> int:
        if self.__file.metadata.num_row_groups == 0:
            return 0

        if self.__file.metadata.num_row_groups == 1:
            return self.__file.metadata.row_group(0).num_rows

        # avg row group sizes, omitting the final row group from the avg (not expected to be full)
        row_group_counts = [
            self.__file.metadata.row_group(i).num_rows for i in range(self.__file.metadata.num_row_groups - 1)
        ]
        return round(statistics.mean(row_group_counts))

    def find_timestamp_field_by_type(self) -> "pyarrow.Field":
        pa = import_optional_dependency("pyarrow", "ingestion")

        for field in self.__schema:
            if pa.types.is_timestamp(field.type):
                if is_timezone_aware(field.type):
                    return field
                logger.warning(
                    "'%s' is timestamp-like but is not timezone aware "
                    "and therefore cannot be treated as a timestamp by Roboto",
                    field.name,
                )

        raise TimestampFieldNotFoundException(
            "Unable to determine column that should be treated as the timestamp. "
            "Try providing the timestamp column explicitly, ensuring that column exists in the data, "
            "and is timezone-aware if timestamp-like (e.g., a datetime instance)."
        )

    def extract_timestamp_info(
        self,
        timestamp_column_name: typing.Optional[str] = None,
        timestamp_unit: typing.Optional[typing.Union[str, TimeUnit]] = None,
    ) -> TimestampInfo:
        pa = import_optional_dependency("pyarrow", "ingestion")
        pc = import_optional_dependency("pyarrow.compute", "ingestion")

        field = (
            self.get_timestamp_field_by_name(timestamp_column_name)
            if timestamp_column_name is not None
            else self.find_timestamp_field_by_type()
        )

        unit = None
        if timestamp_unit is not None:
            unit = TimeUnit(timestamp_unit)

        inferred_unit = time_unit_from_timestamp_type(field.type) if pa.types.is_timestamp(field.type) else None

        if unit is None:
            unit = inferred_unit

        if unit is not None and inferred_unit is not None and unit != inferred_unit:
            logger.warning(
                "Timestamp unit provided explicitly but data type suggests '%s'. "
                "Using the explicitly provided unit '%s' instead.",
                inferred_unit.value,
                unit.value,
            )

        if unit is None:
            raise IngestionException(
                f"The timestamp unit cannot be determined for field '{field.name}.' "
                "Explicitly set the timestamp unit or ensure the field is datetime-like."
            )

        table = self.get_data_for_column(field.name)
        data = table.column(0)
        min_max = pc.min_max(data)
        # If the value is in nanoseconds, we'll get an error like
        #
        # ValueError: Nanosecond resolution temporal type 999 is not safely convertible to microseconds to convert
        # to datetime.datetime. Install pandas to return as Timestamp with nanosecond support or
        # access the .value attribute.
        #
        # ...which we can handle by just grabbing the int value as "value". We'll normalize it later anyway.
        try:
            start_time = min_max["min"].as_py()
            end_time = min_max["max"].as_py()
        except ValueError:
            start_time = min_max["min"].value  # type: ignore
            end_time = min_max["max"].value  # type: ignore

        return TimestampInfo(
            field=field,
            unit=unit,
            start_time=start_time,
            end_time=end_time,
        )

    def get_data_for_column(self, column_name: str) -> "pyarrow.Table":
        return self.__file.read(columns=[column_name])

    def get_timestamp_field_by_name(self, column_name: str) -> "pyarrow.Field":
        pa = import_optional_dependency("pyarrow", "ingestion")

        try:
            field = self.__schema.field(column_name)
        except KeyError:
            raise TimestampFieldNotFoundException(
                f"'{column_name}' provided as timestamp, but that field is not present in the provided data.",
            ) from None

        # Does it look like a timestamp?
        if not is_timestamp_like(field.type):
            raise IngestionException(
                f"'{column_name}' provided as timestamp, "
                f"but it is of type '{field.type}'. Expected a datetime-like or numeric field.",
            )

        if pa.types.is_timestamp(field.type) and not is_timezone_aware(field.type):
            raise IngestionException(
                f"'{column_name}' provided as timestamp and is of the proper type, "
                "but is not timezone aware and therefore cannot be treated as a timestamp by Roboto."
            )

        return field

    def requires_rewrite(self, timestamp: TimestampInfo) -> bool:
        if self.row_count == 0:
            # Edge case: the file has no data, no need to rewrite
            return False

        # Parquet files with many small row groups will perform poorly in Roboto.
        many_row_groups = self.row_group_count > self.__small_row_group_count_threshold
        row_groups_are_small = self.row_group_size < self.__min_required_row_group_size
        many_small_row_groups = many_row_groups and row_groups_are_small
        if many_small_row_groups:
            logger.warning(
                "This file must be rewritten because it has many small row groups, "
                "which will cause it to integrate poorly with the Roboto Platform."
            )
            return True

        # Selecting slices of files depends on row group filtering based on timestamp statistics.
        # Rewrite the file if the timestamp column is missing statistics.
        missing_row_group_stats = self.__is_timestamp_column_missing_stats(timestamp.field)
        if missing_row_group_stats:
            logger.warning(
                "This file must be rewritten because it has missing row group statistics for the timestamp column, "
                "which will cause it to integrate poorly with the Roboto Platform."
            )
            return True

        return False

    def rewrite(
        self,
        outfile: pathlib.Path,
        timestamp: TimestampInfo,
        # The bigger the better, but there is a direct correlation between this and system memory utilization
        # This can (and maybe should) be dialed up to 500MB or 1GB, but that would require a beefier VM.
        target_row_group_size_bytes: int = 100 * 1000 * 1000,  # 100MB
    ) -> None:
        pq = import_optional_dependency("pyarrow.parquet", "ingestion")

        metadata = self.__file.metadata

        # determine optimal row group size to use while reading the source file to:
        #   1. make sure this action doesn't run out of memory
        #   2. ensure read efficiency of the target file
        #       (as currently implemented, batch size at read time is the row group size at write time)
        max_bytes_per_row = (
            max(
                (metadata.row_group(i).total_byte_size / metadata.row_group(i).num_rows)
                for i in range(metadata.num_row_groups)
                if metadata.row_group(i).num_rows > 0
            )
            if metadata.num_row_groups > 0
            else 1000
        )

        row_group_size = max(int(target_row_group_size_bytes / max_bytes_per_row), 100_000)

        logger.info(
            "Using row group size of %d rows based on an estimated %d bytes per row",
            row_group_size,
            max_bytes_per_row,
        )
        with pq.ParquetWriter(
            where=outfile,
            schema=self.__schema,
            # https://github.com/apache/parquet-format/blob/eb4b31c1d64a01088d02a2f9aefc6c17c54cc6fc/src/main/thrift/parquet.thrift#L619
            # vs
            # https://github.com/apache/parquet-format/blob/eb4b31c1d64a01088d02a2f9aefc6c17c54cc6fc/src/main/thrift/parquet.thrift#L577
            # Supported by our in-browser reader:
            # https://github.com/hyparam/hyparquet/blob/master/src/datapage.js
            data_page_version="2.0",
            # Statistics are used for row group filtering
            write_statistics=[timestamp.field.name],
            # https://arrow.apache.org/docs/python/parquet.html#storing-timestamps
            version="2.6",
        ) as writer:
            for batch in self.__file.iter_batches(batch_size=row_group_size):
                writer.write_batch(batch)

    def __is_timestamp_column_missing_stats(self, timestamp_field: "pyarrow.Field") -> bool:
        for row_group_idx in range(self.__file.metadata.num_row_groups):
            row_group = self.__file.metadata.row_group(row_group_idx)
            for col_idx in range(self.__file.metadata.num_columns):
                column = row_group.column(col_idx)
                if column.path_in_schema != timestamp_field.name:
                    continue
                if not column.is_stats_set:
                    return True
        return False
