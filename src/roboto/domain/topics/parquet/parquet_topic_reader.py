# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import pathlib
import typing
import urllib.request

from ....association import AssociationType
from ....compat import import_optional_dependency
from ....http import RobotoClient
from ....logging import default_logger
from ..operations import (
    MessagePathRepresentationMapping,
)
from ..record import (
    CanonicalDataType,
    MessagePathRecord,
    RepresentationRecord,
    RepresentationStorageFormat,
)
from ..topic_reader import Timestamp, TopicReader
from .table_transforms import (
    compute_time_filter_mask,
    extract_timestamp_field,
    extract_timestamps,
    resolve_columns,
    should_read_row_group,
)
from .timestamp import Timestamp as TimestampDescriptor

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


logger = default_logger()

OUTFILE_NAME_PATTERN = "{repr_id}_{file_id}.parquet"
"""Filename template for locally cached Parquet files."""

_COLUMN_COUNT_LOCAL_CACHE_THRESHOLD = 10
"""
When the number of columns to read meets or exceeds this threshold,
the Parquet file is downloaded to a local cache before reading.
Reading many columns over HTTP incurs significant per-column overhead;
a local file avoids repeated network round-trips, but also loads much unnecessary data.
10 was chosen as individual column loading can be very slow for some files and many columns, while local
cache based access is never terribly slow.
"""


class _ReadContext(typing.NamedTuple):
    """Shared state prepared for reading a Parquet-backed topic."""

    parquet_file: pyarrow.parquet.ParquetFile
    timestamp_field: TimestampDescriptor
    columns: list[str]
    include_timestamp_column: bool


class ParquetTopicReader(TopicReader):
    """Private interface for retrieving topic data stored in Parquet files.

    Note:
        This is not intended as a public API.
        To access topic data, prefer the ``get_data`` or ``get_data_as_df`` methods
        on :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`,
        or :py:class:`~roboto.domain.events.Event`.
    """

    __cache_dir: typing.Optional[pathlib.Path]
    __roboto_client: RobotoClient

    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ) -> bool:
        for mapping in message_paths_to_representations:
            if mapping.representation.storage_format != RepresentationStorageFormat.PARQUET:
                return False
        return True

    def __init__(
        self,
        roboto_client: RobotoClient,
        cache_dir: typing.Optional[pathlib.Path] = None,
    ):
        self.__roboto_client = roboto_client
        self.__cache_dir = cache_dir

    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        pc = import_optional_dependency("pyarrow.compute", "analytics")

        if timestamp_message_path_representation_mapping is None:
            raise NotImplementedError(
                "Reading data from a Parquet file requires one column to be marked as a 'CanonicalDataType.Timestamp'. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support."
            )

        ctx = self.__prepare_read(
            message_paths_to_representations,
            timestamp_message_path_representation_mapping,
        )
        if ctx is None:
            return

        for row_group_idx in range(ctx.parquet_file.metadata.num_row_groups):
            row_group_metadata = ctx.parquet_file.metadata.row_group(row_group_idx)
            if not should_read_row_group(
                row_group_metadata,
                ctx.timestamp_field,
                start_time,
                end_time,
            ):
                continue

            row_group_table = ctx.parquet_file.read_row_group(
                row_group_idx,
                columns=ctx.columns,
            )

            timestamps = extract_timestamps(row_group_table, ctx.timestamp_field)

            # Drop the timestamp column if it wasn't originally requested
            if not ctx.include_timestamp_column:
                row_group_table = row_group_table.drop_columns(ctx.timestamp_field.field.name)

            filter_mask = compute_time_filter_mask(timestamps, start_time, end_time)
            if filter_mask is not None:
                row_group_table = pc.filter(row_group_table, filter_mask)
                timestamps = pc.filter(timestamps, filter_mask)

            # Yield tuples of (timestamp, row_dict)
            for idx, row in enumerate(row_group_table.to_pylist()):
                timestamp = timestamps[idx]
                if pc.is_null(timestamp, nan_is_null=True):
                    logger.warning("Skipping row %d, timestamp is null", idx)
                    continue

                yield timestamp.as_py(), row

    def get_data_as_df(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
    ) -> tuple[pandas.Series, pandas.DataFrame]:
        pd = import_optional_dependency("pandas", "analytics")
        pa = import_optional_dependency("pyarrow", "analytics")
        pc = import_optional_dependency("pyarrow.compute", "analytics")

        if timestamp_message_path_representation_mapping is None:
            raise NotImplementedError(
                "Reading data from a Parquet file requires one column to be marked as a 'CanonicalDataType.Timestamp'. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support."
            )

        ctx = self.__prepare_read(
            message_paths_to_representations,
            timestamp_message_path_representation_mapping,
        )
        if ctx is None:
            return pd.Series(), pd.DataFrame()

        timestamps = []
        tables = []

        for row_group_idx in range(ctx.parquet_file.metadata.num_row_groups):
            row_group_metadata = ctx.parquet_file.metadata.row_group(row_group_idx)
            if not should_read_row_group(
                row_group_metadata,
                ctx.timestamp_field,
                start_time,
                end_time,
            ):
                continue

            row_group_table = ctx.parquet_file.read_row_group(
                row_group_idx,
                columns=ctx.columns,
            )

            row_group_timestamps = extract_timestamps(row_group_table, ctx.timestamp_field)

            if not ctx.include_timestamp_column:
                # The timestamp column was not included in the column projection list.
                row_group_table = row_group_table.drop_columns(
                    ctx.timestamp_field.field.name,
                )

            filter_mask = compute_time_filter_mask(row_group_timestamps, start_time, end_time)
            if filter_mask is not None:
                row_group_table = pc.filter(row_group_table, filter_mask)
                row_group_timestamps = pc.filter(row_group_timestamps, filter_mask)

            timestamps.append(row_group_timestamps)
            tables.append(row_group_table)

        if not tables:
            return pd.Series(), pd.DataFrame()

        combined_timestamps: pyarrow.Array = pa.concat_arrays(timestamps)
        combined_tables: pyarrow.Table = pa.concat_tables(tables)

        return combined_timestamps.to_pandas(), combined_tables.to_pandas()

    def __ensure_single_parquet_file_per_topic(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ):
        """
        Support pulling data out of a single Parquet file per Topic.
        This is a non-essential limitation; it is done for expediency of initial implementation.
        This class can and should be extended to support splitting a Topic's MessagePaths
        across multiple underlying files.
        """
        repr_ids = {mapping.representation.representation_id for mapping in message_paths_to_representations}
        if len(repr_ids) > 1:
            raise NotImplementedError(
                "Support for reading data for topics whose data is split across multiple Parquet files  "
                "is not yet implemented. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support."
            )

    def __get_signed_url_for_representation_file(self, representation: RepresentationRecord) -> str:
        association = representation.association
        if association.association_type != AssociationType.File:
            raise NotImplementedError(
                "Unable to get topic data. "
                "Expected the data to be stored in a Parquet file, "
                f"but received a pointer to a '{association.association_type.value}' instead. "
                "This is likely a problem with data ingestion. Please reach out to Roboto support."
            )
        file_id = representation.association.association_id
        logger.debug("Getting signed url for file '%s'", file_id)
        signed_url_response = self.__roboto_client.get(f"v1/files/{file_id}/signed-url")
        return signed_url_response.to_dict(json_path=["data", "url"])

    def __parquet_file_from_remote_streaming(self, representation: RepresentationRecord) -> pyarrow.parquet.ParquetFile:
        """Open a Parquet file over HTTP via a signed URL (no local download)."""
        fs = import_optional_dependency("pyarrow.fs", "analytics")
        fsspec_http = import_optional_dependency("fsspec.implementations.http", "analytics")
        pq = import_optional_dependency("pyarrow.parquet", "analytics")

        http_fs = fsspec_http.HTTPFileSystem()
        signed_url = self.__get_signed_url_for_representation_file(representation)
        return pq.ParquetFile(signed_url, filesystem=fs.PyFileSystem(fs.FSSpecHandler(http_fs)))

    def __should_use_local_cache(self, column_count: int) -> bool:
        """Decide whether the Parquet file should be downloaded to local cache.

        Returns ``True`` when the column count meets or exceeds
        ``_COLUMN_COUNT_LOCAL_CACHE_THRESHOLD`` **and** a cache directory has
        been configured.
        """
        return self.__cache_dir is not None and column_count >= _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD

    def __parquet_file_from_local_cache(self, representation: RepresentationRecord) -> pyarrow.parquet.ParquetFile:
        """Download the Parquet file to local cache (if not already cached) and open it.

        Follows the same caching pattern used by :class:`McapTopicReader`:
        files are stored under ``<cache_dir>/<repr_id>_<file_id>.parquet`` and
        re-used across calls.
        """
        pq = import_optional_dependency("pyarrow.parquet", "analytics")

        if self.__cache_dir is None:  # guaranteed by __should_use_local_cache
            raise RuntimeError("Expected self.__cache_dir to be set")

        outfile = self.__cache_dir / OUTFILE_NAME_PATTERN.format(
            repr_id=representation.representation_id,
            file_id=representation.association.association_id,
        )

        if not outfile.exists():
            signed_url = self.__get_signed_url_for_representation_file(representation)
            logger.debug(
                "Downloading Parquet file for representation '%s' to %s",
                representation.representation_id,
                outfile,
            )
            urllib.request.urlretrieve(signed_url, str(outfile))  # noqa: S310 — presigned S3 URL from Roboto API

        return pq.ParquetFile(outfile)

    def __prepare_read(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        timestamp_message_path_representation_mapping: MessagePathRepresentationMapping,
    ) -> typing.Optional[_ReadContext]:
        """Shared preamble for ``get_data`` and ``get_data_as_df``.

        Validates inputs, opens the Parquet file (remotely or from local cache),
        resolves the timestamp field, and builds the column projection list.

        When the number of requested columns meets or exceeds
        ``_COLUMN_COUNT_LOCAL_CACHE_THRESHOLD`` and a *cache_dir* was provided,
        the file is downloaded to local disk first to avoid excessive HTTP
        round-trips.

        Returns ``None`` when *message_paths_to_representations* is empty
        (i.e. there is nothing to read).
        """
        self.__ensure_single_parquet_file_per_topic(
            [
                *message_paths_to_representations,
                timestamp_message_path_representation_mapping,
            ]
        )

        mapping = next(iter(message_paths_to_representations), None)
        if mapping is None:
            return None

        timestamp_message_path = self.__timestamp_message_path(timestamp_message_path_representation_mapping)

        # Use message-path count as a proxy for column count to decide
        # whether to download the file locally before opening it.
        estimated_column_count = len(list(mapping.message_paths))
        if self.__should_use_local_cache(estimated_column_count):
            logger.debug(
                "Using local cache for Parquet file (%d message paths >= %d threshold)",
                estimated_column_count,
                _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
            )
            parquet_file = self.__parquet_file_from_local_cache(mapping.representation)
        else:
            logger.debug(
                "Using remote HTTP for Parquet file (%d message paths < %d threshold)",
                estimated_column_count,
                _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
            )
            parquet_file = self.__parquet_file_from_remote_streaming(mapping.representation)

        columns = resolve_columns(parquet_file.schema_arrow, mapping.message_paths)

        # Even if the timestamp column wasn't requested in the column projection list,
        # request the data to enable timestamp filtering
        include_timestamp_column = timestamp_message_path.source_path in columns
        if not include_timestamp_column:
            columns.append(timestamp_message_path.source_path)

        timestamp_field = extract_timestamp_field(parquet_file.schema_arrow, timestamp_message_path)

        return _ReadContext(
            parquet_file=parquet_file,
            timestamp_field=timestamp_field,
            columns=columns,
            include_timestamp_column=include_timestamp_column,
        )

    def __timestamp_message_path(
        self, message_path_representation_mapping: MessagePathRepresentationMapping
    ) -> MessagePathRecord:
        for message_path in message_path_representation_mapping.message_paths:
            if message_path.canonical_data_type != CanonicalDataType.Timestamp:
                continue

            return message_path

        raise Exception(
            "Could not determine timestamp for topic ingested as Parquet. "
            "This is likely a problem with data ingestion. Please reach out to Roboto support."
        )
