# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import os
import pathlib
import threading
import typing
import urllib.request
import uuid
import weakref

from ....association import AssociationType
from ....compat import import_optional_dependency
from ....http import RobotoClient
from ....logging import default_logger
from ..record import (
    CanonicalDataType,
    MessagePathRecord,
    MessagePathRepresentationMapping,
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

_download_locks: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
"""In-process registry of per-file download locks, keyed by absolute cache path.

Dedupes concurrent downloads of the same Parquet file within a single process.
Cross-process concurrency is handled by the atomic-rename pattern in
``__download_to_cache`` (last writer wins, but every observed file is complete),
not by this lock.

Entries hold the lock by weak reference: as long as at least one caller is
inside ``__download_to_cache`` for a given path, its local strong reference
keeps the lock alive and concurrent callers share the same instance. Once the
last caller returns, the lock becomes unreferenced and the entry is evicted
automatically, so the registry's footprint is bounded by in-flight downloads
rather than by lifetime-unique paths.
"""

_download_locks_guard = threading.Lock()
"""Guards inserts into ``_download_locks``."""


def _get_download_lock(key: str) -> threading.Lock:
    with _download_locks_guard:
        lock = _download_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _download_locks[key] = lock
        return lock


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

    def __cached_outfile_for(self, representation: RepresentationRecord) -> pathlib.Path:
        """Return the local cache path for a representation. Requires ``cache_dir`` to be set."""
        if self.__cache_dir is None:
            raise RuntimeError("Expected self.__cache_dir to be set")
        return self.__cache_dir / OUTFILE_NAME_PATTERN.format(
            repr_id=representation.representation_id,
            file_id=representation.association.association_id,
        )

    def __open_parquet_file(
        self, representation: RepresentationRecord, estimated_column_count: int
    ) -> pyarrow.parquet.ParquetFile:
        """Pick the cheapest available source for the Parquet file.

        Priority:

        1. If ``cache_dir`` is configured and the file is already cached locally,
           use it. A previously-downloaded file is always cheaper to open than
           streaming over HTTP, regardless of how many columns the current call
           projects.
        2. Else, if a ``cache_dir`` is configured and the request projects enough
           columns to justify a full download (``>=
           _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD``), download to cache and use it.
        3. Else, stream via HTTP range requests without writing to disk.
        """
        if self.__cache_dir is not None and self.__cached_outfile_for(representation).exists():
            logger.debug("Using already-cached Parquet file for representation '%s'", representation.representation_id)
            return self.__parquet_file_from_local_cache(representation)

        if self.__cache_dir is not None and estimated_column_count >= _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD:
            logger.debug(
                "Downloading Parquet file to local cache (%d message paths >= %d threshold)",
                estimated_column_count,
                _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
            )
            return self.__parquet_file_from_local_cache(representation)

        logger.debug(
            "Using remote HTTP for Parquet file (%d message paths < %d threshold, or no cache_dir)",
            estimated_column_count,
            _COLUMN_COUNT_LOCAL_CACHE_THRESHOLD,
        )
        return self.__parquet_file_from_remote_streaming(representation)

    def __parquet_file_from_local_cache(self, representation: RepresentationRecord) -> pyarrow.parquet.ParquetFile:
        """Download the Parquet file to local cache (if not already cached) and open it.

        Files are stored under ``<cache_dir>/<repr_id>_<file_id>.parquet`` and
        re-used across calls. Concurrent access is safe: an in-process lock keyed
        on the cache path dedupes downloads between threads, and an atomic
        temp-file-plus-rename pattern guarantees that any file visible at the
        final path is complete — readers in this or other processes never
        observe a partial download.
        """
        pq = import_optional_dependency("pyarrow.parquet", "analytics")

        outfile = self.__cached_outfile_for(representation)
        if not outfile.exists():
            self.__download_to_cache(representation, outfile)

        return pq.ParquetFile(outfile)

    def __download_to_cache(self, representation: RepresentationRecord, outfile: pathlib.Path) -> None:
        """Download the representation's file to ``outfile`` safely under concurrency.

        Acquires a per-path lock to dedupe in-process downloads, double-checks
        existence (another thread may have completed the download while we were
        waiting), creates the cache directory lazily, and writes via a uniquely
        named ``.part`` file followed by :func:`os.replace`. The rename is atomic
        on POSIX and Windows, so:

        * Readers never see a partial file at ``outfile``.
        * Two processes racing both produce a complete file; the second
          ``os.replace`` simply overwrites the first.
        * If the download raises, the ``.part`` file is removed and ``outfile``
          is left untouched.
        """
        lock = _get_download_lock(str(outfile))
        with lock:
            if outfile.exists():
                return

            outfile.parent.mkdir(parents=True, exist_ok=True)
            tmpfile = outfile.with_name(f"{outfile.name}.{uuid.uuid4().hex}.part")

            signed_url = self.__get_signed_url_for_representation_file(representation)
            logger.debug(
                "Downloading Parquet file for representation '%s' to %s",
                representation.representation_id,
                outfile,
            )
            try:
                urllib.request.urlretrieve(signed_url, str(tmpfile))  # noqa: S310 — presigned S3 URL from Roboto API
                os.replace(tmpfile, outfile)
            except BaseException:
                tmpfile.unlink(missing_ok=True)
                raise

    def __prepare_read(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        timestamp_message_path_representation_mapping: MessagePathRepresentationMapping,
    ) -> typing.Optional[_ReadContext]:
        """Shared preamble for ``get_data`` and ``get_data_as_df``.

        Validates inputs, opens the Parquet file (via ``__open_parquet_file``,
        which prefers an existing local cache file, falls back to downloading
        when the projection is column-heavy enough to justify it, and otherwise
        streams via HTTP), resolves the timestamp field, and builds the column
        projection list.

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
        parquet_file = self.__open_parquet_file(mapping.representation, estimated_column_count)

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
