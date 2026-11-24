# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import pathlib
import typing

from ....association import AssociationType
from ....compat import import_optional_dependency
from ....formats import FieldSelection
from ....formats.parquet import (
    Timestamp as TimestampDescriptor,
)
from ....formats.parquet import (
    compute_time_filter_mask,
    extract_timestamp_field,
    extract_timestamps,
    parquet_file_from_url,
    resolve_columns,
    select_fields,
    should_read_row_group,
)
from ....http import RobotoClient
from ....logging import default_logger
from ....storage.cache import (
    COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
    CachePolicy,
    FetchMode,
    choose_fetch_mode,
    download_to_cache,
)
from ..record import (
    CanonicalDataType,
    MessagePathMetadataWellKnown,
    MessagePathRecord,
    MessagePathRepresentationMapping,
    RepresentationRecord,
    RepresentationStorageFormat,
)
from ..topic_reader import Timestamp, TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


logger = default_logger()

OUTFILE_NAME_PATTERN = "{repr_id}_{file_id}.parquet"
"""Name of a Parquet file in the local cache, filled in with the representation's ID and the file's ID."""


class _ReadContext(typing.NamedTuple):
    """The opened Parquet file and what to read from it, shared by ``get_data`` and ``get_data_as_df``."""

    parquet_file: pyarrow.parquet.ParquetFile
    timestamp_field: TimestampDescriptor
    columns: list[str]
    fields: list[FieldSelection]


class ParquetTopicReader(TopicReader):
    """Reader of topic data stored in Parquet files.

    The SDK's own code uses it; to read topic data, use the ``get_data`` or ``get_data_as_df`` methods of
    :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath` or
    :py:class:`~roboto.domain.events.Event` instead.

    Skips each row group whose timestamp statistics show it lies outside the requested time range, and reads only
    the columns that hold the requested message paths and the timestamp. Without a cache directory, it reads every
    file over HTTP and writes nothing to disk.

    Args:
        roboto_client: Client to make requests to Roboto with.
        cache_dir: Directory to keep downloaded Parquet files in. A file already there is read from it; a file not
            there is downloaded to it when the read requests at least 10 message paths
            (:py:const:`~roboto.storage.cache.COLUMN_COUNT_LOCAL_CACHE_THRESHOLD`), and read over HTTP otherwise.
            ``None`` caches nothing.
    """

    __cache_dir: typing.Optional[pathlib.Path]
    __roboto_client: RobotoClient

    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ) -> bool:
        """Return whether every mapping's representation is stored as Parquet, and so whether this reader can read it.

        An empty iterable returns ``True``.
        """
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
        """Yield ``(timestamp, row)`` pairs from the Parquet file that stores the message paths, in file order.

        A message path the file has no column for is left out of every row, and a row whose timestamp is null is
        skipped; each logs a warning. As a generator, it raises each exception under Raises on the first iteration,
        not when called.

        Args:
            message_paths_to_representations: Message paths to read, each paired with the representation that stores
                it. Every mapping must name the same representation, and only the first mapping's message paths are
                read.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the
                range unbounded below.
            end_time: Exclusive end of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
                unbounded above.
            timestamp_message_path_representation_mapping: Mapping whose message paths include the one with canonical
                data type :py:attr:`~roboto.domain.topics.CanonicalDataType.Timestamp`, stored in the same
                representation. Its values become each row's timestamp and are compared with the time range.

        Yields:
            ``(timestamp, row)`` tuples: the timestamp in nanoseconds since the Unix epoch, and a dictionary of the
            row's requested fields.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            NotImplementedError: ``timestamp_message_path_representation_mapping`` is ``None``, the mappings name
                more than one representation, or the representation does not belong to a file.
            Exception: The timestamp mapping has no message path with canonical data type ``Timestamp``.
        """
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
            row_group_table = select_fields(row_group_table, ctx.fields)

            filter_mask = compute_time_filter_mask(timestamps, start_time, end_time)
            if filter_mask is not None:
                row_group_table = pc.filter(row_group_table, filter_mask)
                timestamps = pc.filter(timestamps, filter_mask)

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
        """Read the requested rows of the Parquet file as a series of timestamps and a data frame.

        A message path the file has no column for is left out of the data frame, with a logged warning.

        Args:
            message_paths_to_representations: Message paths to read, as for ``get_data``.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the
                range unbounded below.
            end_time: Exclusive end of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
                unbounded above.
            timestamp_message_path_representation_mapping: Mapping that holds the timestamp message path, as for
                ``get_data``.

        Returns:
            ``(timestamps, data_frame)``: the timestamp of each row in nanoseconds since the Unix epoch, and a data
            frame with one row per Parquet row read. Both are empty when there is no message path to read or no row
            group overlaps the time range.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            NotImplementedError: ``timestamp_message_path_representation_mapping`` is ``None``, the mappings name
                more than one representation, or the representation does not belong to a file.
            Exception: The timestamp mapping has no message path with canonical data type
                :py:attr:`~roboto.domain.topics.CanonicalDataType.Timestamp`.
        """
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
            row_group_table = select_fields(row_group_table, ctx.fields)

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
        """Reject mappings that name more than one representation, by raising ``NotImplementedError``.

        This reader reads one Parquet file per topic, so it cannot read a topic whose message paths are split across
        several files.
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
        signed_url = self.__get_signed_url_for_representation_file(representation)
        return parquet_file_from_url(signed_url)

    def __cached_outfile_for(self, representation: RepresentationRecord) -> pathlib.Path:
        """Return the local cache path for a representation.

        Raises ``RuntimeError`` when ``cache_dir`` is ``None``.
        """
        if self.__cache_dir is None:
            raise RuntimeError("Expected self.__cache_dir to be set")
        return self.__cache_dir / OUTFILE_NAME_PATTERN.format(
            repr_id=representation.representation_id,
            file_id=representation.association.association_id,
        )

    def __open_parquet_file(
        self, representation: RepresentationRecord, estimated_column_count: int
    ) -> pyarrow.parquet.ParquetFile:
        """Open the representation's Parquet file from the first of these sources that applies.

        1. With ``cache_dir`` set and the file already in the cache, the cached copy, however many columns the read
           needs.
        2. With ``cache_dir`` set and ``estimated_column_count`` at least 10
           (:py:const:`~roboto.storage.cache.COLUMN_COUNT_LOCAL_CACHE_THRESHOLD`), a copy downloaded to the cache.
        3. Otherwise, the remote file, read over HTTP without writing to disk.
        """
        mode = choose_fetch_mode(
            policy=CachePolicy.ADAPTIVE if self.__cache_dir is not None else CachePolicy.NEVER,
            already_cached=self.__cache_dir is not None and self.__cached_outfile_for(representation).exists(),
            estimated_column_count=estimated_column_count,
        )

        if mode is FetchMode.CACHED:
            logger.debug("Using already-cached Parquet file for representation '%s'", representation.representation_id)
            return self.__parquet_file_from_local_cache(representation)

        if mode is FetchMode.DOWNLOAD:
            logger.debug(
                "Downloading Parquet file to local cache (%d message paths >= %d threshold)",
                estimated_column_count,
                COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
            )
            return self.__parquet_file_from_local_cache(representation)

        logger.debug(
            "Using remote HTTP for Parquet file (%d message paths < %d threshold, or no cache_dir)",
            estimated_column_count,
            COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
        )
        return self.__parquet_file_from_remote_streaming(representation)

    def __parquet_file_from_local_cache(self, representation: RepresentationRecord) -> pyarrow.parquet.ParquetFile:
        """Download the Parquet file to ``<cache_dir>/<repr_id>_<file_id>.parquet`` unless it is there, and open it.

        Threads in one process that ask for the same file wait on a lock keyed on its cache path, so the file is
        downloaded once. The download is written to a temporary file and renamed into place when complete, so no
        reader in any process finds a partial file at the cache path.
        """
        pq = import_optional_dependency("pyarrow.parquet", "analytics")

        outfile = self.__cached_outfile_for(representation)
        if not outfile.exists():
            download_to_cache(
                lambda: self.__get_signed_url_for_representation_file(representation),
                outfile,
            )

        return pq.ParquetFile(outfile)

    def __prepare_read(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        timestamp_message_path_representation_mapping: MessagePathRepresentationMapping,
    ) -> typing.Optional[_ReadContext]:
        """Open the Parquet file and find the timestamp field and the columns to read, for both read methods.

        A message path the file has no column for is left out of the fields to read, with a logged warning.

        Returns:
            The read's context, or ``None`` when ``message_paths_to_representations`` is empty.
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
        parquet_file = self.__open_parquet_file(mapping.representation, estimated_column_count)

        column_names = frozenset(parquet_file.schema_arrow.names)
        fields: list[FieldSelection] = []
        missing: list[str] = []
        for record in mapping.message_paths:
            field = record.to_field_selection()
            if field.path_in_schema and field.path_in_schema[0] not in column_names:
                missing.append(record.message_path)
            else:
                fields.append(field)
        if missing:
            logger.warning(
                "Topic data file has no column for message paths %s, so they are left out of the result. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support.",
                missing,
            )
        timestamp_selection = timestamp_message_path.to_field_selection()

        # The timestamp field is read even when it is not among the requested fields, to filter rows by time;
        # select_fields leaves it out of each row group's table in that case.
        columns = resolve_columns(parquet_file.schema_arrow, [*fields, timestamp_selection])

        timestamp_field = extract_timestamp_field(
            parquet_file.schema_arrow,
            timestamp_selection,
            unit_hint=timestamp_message_path.metadata.get(MessagePathMetadataWellKnown.Unit.value),
        )

        return _ReadContext(
            parquet_file=parquet_file,
            timestamp_field=timestamp_field,
            columns=columns,
            fields=fields,
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
