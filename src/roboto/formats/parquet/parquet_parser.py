# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import statistics
import typing

from ...compat import import_optional_dependency
from ...exceptions import (
    IngestionException,
    TimestampFieldNotFoundException,
)
from ...logging import default_logger
from ...time import TimeUnit
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
    """Reader of a local Parquet file's schema, row groups and timestamp column.

    :py:meth:`~roboto.domain.topics.Topic.create_from_df` finds a new topic's time range through it, and its message
    paths through :py:func:`~roboto.formats.parquet.generate_message_path_requests`, so most code never calls it. It
    can also tell whether the file's row groups let Roboto read a time range of it efficiently, and write a copy that
    does.

    Args:
        source: Path of the local Parquet file to read.
        min_required_row_group_size: Number of rows below which the file's average row group counts as small, for
            ``requires_rewrite``.
        small_row_group_count_threshold: Number of row groups above which a file of small row groups needs
            rewriting, for ``requires_rewrite``.

    Raises:
        ImportError: The ``roboto[ingestion]`` extra is not installed.
    """

    __file: "pyarrow.parquet.ParquetFile"
    __min_required_row_group_size: int
    __schema: "pyarrow.Schema"
    __small_row_group_count_threshold: int

    @staticmethod
    def is_parquet_file(path: pathlib.Path) -> bool:
        """Return whether the file at ``path`` begins with the Parquet magic bytes ``PAR1``.

        A file that cannot be opened or read, such as one that does not exist, counts as Parquet when its name ends
        in ``.parquet``, in any letter case.

        Args:
            path: Path of the local file to check.
        """
        try:
            with path.open("rb") as f:
                magic_bytes = f.read(4)
                return magic_bytes == b"PAR1"
        except (FileNotFoundError, IOError, OSError):
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
        """Number of leaf columns the file stores, in which each field of a struct counts as its own column."""
        return self.__file.metadata.num_columns

    @property
    def fields(self) -> typing.Generator["pyarrow.Field", None, None]:
        """Top-level fields of the file's schema, in schema order."""
        yield from self.__schema

    @property
    def row_count(self) -> int:
        """Number of rows in the file."""
        return self.__file.metadata.num_rows

    @property
    def row_group_count(self) -> int:
        """Number of row groups in the file."""
        return self.__file.metadata.num_row_groups

    @property
    def row_group_size(self) -> int:
        """Average number of rows per row group, rounded to the nearest whole number.

        The final row group is left out of the average, since it holds whatever rows remain and is usually smaller.
        For a file with one row group, the value is that group's row count; for a file with none, ``0``.
        """
        if self.__file.metadata.num_row_groups == 0:
            return 0

        if self.__file.metadata.num_row_groups == 1:
            return self.__file.metadata.row_group(0).num_rows

        row_group_counts = [
            self.__file.metadata.row_group(i).num_rows for i in range(self.__file.metadata.num_row_groups - 1)
        ]
        return round(statistics.mean(row_group_counts))

    def find_timestamp_field_by_type(self) -> "pyarrow.Field":
        """Return the first top-level field whose type is a timezone-aware timestamp.

        Logs a warning for each timestamp field without a time zone that it passes over, since Roboto cannot use one
        as the timestamp.

        Raises:
            TimestampFieldNotFoundException: No top-level field is a timezone-aware timestamp.
        """
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
        """Read the file's timestamp column, its unit, and the earliest and latest timestamps in it.

        Reads the whole timestamp column to find its minimum and maximum. A timezone-aware timestamp column yields
        ``datetime.datetime`` values; a numeric column yields numbers in ``timestamp_unit``. When pandas is not
        installed and either value has a fraction of a microsecond, both are integers in nanoseconds instead. A file
        with no rows yields ``None`` for both.

        Args:
            timestamp_column_name: Name of the top-level column that holds each row's timestamp. ``None`` uses the
                first column whose type is a timezone-aware timestamp.
            timestamp_unit: Unit of the timestamp values, as a :py:class:`~roboto.time.TimeUnit` or its value, such
                as ``"ms"``. ``None`` takes the unit from the column's timestamp type. A unit given here wins over
                the type's, with a logged warning when the two differ.

        Returns:
            The timestamp column's field, its unit, and the minimum and maximum of its values.

        Raises:
            TimestampFieldNotFoundException: ``timestamp_column_name`` names no top-level column, or it is ``None``
                and no top-level column is a timezone-aware timestamp.
            IngestionException: The named column is neither numeric nor a timestamp, is a timestamp without a time
                zone, or is numeric and no ``timestamp_unit`` was given.
            ValueError: ``timestamp_unit`` is not a :py:class:`~roboto.time.TimeUnit` value.
        """
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
        # Without pandas, as_py raises ValueError for a nanosecond timestamp with a fraction of a microsecond, which
        # datetime.datetime cannot hold. Take the integer nanosecond values instead.
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
        """Read one column of every row group into memory.

        Args:
            column_name: Name of the column to read.

        Returns:
            A table whose only column is the one named.
        """
        return self.__file.read(columns=[column_name])

    def get_timestamp_field_by_name(self, column_name: str) -> "pyarrow.Field":
        """Return the top-level field named ``column_name``, after checking that it can hold timestamps.

        Args:
            column_name: Name of the top-level column that holds each row's timestamp.

        Raises:
            TimestampFieldNotFoundException: No top-level column has this name.
            IngestionException: The column is neither numeric nor a timestamp, or is a timestamp without a time zone.
        """
        pa = import_optional_dependency("pyarrow", "ingestion")

        try:
            field = self.__schema.field(column_name)
        except KeyError:
            raise TimestampFieldNotFoundException(
                f"'{column_name}' provided as timestamp, but that field is not present in the provided data.",
            ) from None

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
        """Return whether the file needs rewriting with ``rewrite`` before Roboto can read time ranges of it quickly.

        Roboto reads a time range of a Parquet file by skipping the row groups whose timestamp statistics fall
        outside it. A file with rows needs rewriting, with a logged warning, when either holds:

        1. It has more row groups than ``small_row_group_count_threshold`` and they average fewer rows than
           ``min_required_row_group_size``, which makes reading it slow.
        2. A row group lacks statistics for the timestamp column, so Roboto cannot skip that row group.

        Args:
            timestamp: The file's timestamp column, from ``extract_timestamp_info``.
        """
        if self.row_count == 0:
            return False

        many_row_groups = self.row_group_count > self.__small_row_group_count_threshold
        row_groups_are_small = self.row_group_size < self.__min_required_row_group_size
        many_small_row_groups = many_row_groups and row_groups_are_small
        if many_small_row_groups:
            logger.warning(
                "This file must be rewritten because it has many small row groups, "
                "which will cause it to integrate poorly with the Roboto Platform."
            )
            return True

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
        target_row_group_size_bytes: int = 100 * 1000 * 1000,
    ) -> None:
        """Write a copy of the file with large row groups and statistics on the timestamp column.

        The copy's row groups are sized to hold as many rows as fit in ``target_row_group_size_bytes``, at the largest
        uncompressed size per row of any row group in this file, and never fewer than 100,000 rows. Only the timestamp
        column gets statistics, which Roboto uses to skip row groups outside a requested time range.

        Args:
            outfile: Path to write the copy to. An existing file there is overwritten.
            timestamp: The file's timestamp column, from ``extract_timestamp_info``.
            target_row_group_size_bytes: Uncompressed size to aim for in each row group, in bytes. Larger row groups
                read faster, but the rewrite holds one row group in memory at a time. Defaults to 100 MB.
        """
        pq = import_optional_dependency("pyarrow.parquet", "ingestion")

        metadata = self.__file.metadata

        # Each batch read below becomes one row group of the copy, unless pyarrow splits a batch longer than its
        # maximum row group length, so this size bounds both the copy's row groups and the rows held in memory at once.
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
            # The Roboto web app reads Parquet files in the browser, and its reader supports version 2 data pages.
            data_page_version="2.0",
            write_statistics=[timestamp.field.name],
            # Format version 2.6 stores nanosecond timestamps as they are; earlier versions coerce them to microseconds.
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
