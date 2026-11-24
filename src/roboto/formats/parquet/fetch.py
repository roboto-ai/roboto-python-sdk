# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import typing

from ...compat import import_optional_dependency
from ...logging import default_logger
from ...storage.cache import (
    CachePolicy,
    FetchMode,
    cached_file_is_current,
    choose_fetch_mode,
    download_to_cache,
)

if typing.TYPE_CHECKING:
    import pyarrow.parquet  # pants: no-infer-dep

logger = default_logger()

_STREAM_WHOLE_FILE_PROBE_BYTES = 16 * 1024 * 1024
"""Number of bytes ``parquet_file_from_url`` fetches in its first request; a smaller file arrives whole in it."""


def parquet_file_from_url(
    signed_url: str,
    size_bytes: typing.Optional[int] = None,
) -> pyarrow.parquet.ParquetFile:
    """Open a Parquet file from a signed URL, reading it over HTTP without writing it to disk.

    The file is read in one of two ways:

    1. Unless ``size_bytes`` is at least 16 MiB, one request fetches the file's first 16 MiB. When fewer bytes come
       back, that is the whole file, and it is read from memory with no further request.
    2. When ``size_bytes`` is at least 16 MiB, or the first request returns 16 MiB or fails, the file is read with
       HTTP range requests, each fetching only the bytes a read needs.

    Args:
        signed_url: Signed URL of the file, such as one :py:meth:`~roboto.domain.files.File.get_signed_url` returns.
        size_bytes: Size of the file in bytes. ``None`` when unknown. A size of at least 16 MiB skips the first
            request, which could not return the whole file.

    Raises:
        ValueError: The first request succeeds but returns no bytes: the file is empty, so it is not a Parquet file.
        ImportError: The ``roboto[analytics]`` extra is not installed.
    """
    fs = import_optional_dependency("pyarrow.fs", "analytics")
    fsspec_http = import_optional_dependency("fsspec.implementations.http", "analytics")
    pa = import_optional_dependency("pyarrow", "analytics")
    pq = import_optional_dependency("pyarrow.parquet", "analytics")

    http_fs = fsspec_http.HTTPFileSystem()

    def _range_stream() -> pyarrow.parquet.ParquetFile:
        return pq.ParquetFile(signed_url, filesystem=fs.PyFileSystem(fs.FSSpecHandler(http_fs)))

    if size_bytes is not None and size_bytes >= _STREAM_WHOLE_FILE_PROBE_BYTES:
        return _range_stream()

    try:
        data = http_fs.cat_file(signed_url, start=0, end=_STREAM_WHOLE_FILE_PROBE_BYTES)
    except Exception:
        # Suppress any Exception: range requests may still read a file whose first request failed.
        logger.debug(
            "Head probe of streamed Parquet file failed; falling back to range-request streaming",
            exc_info=True,
        )
        data = None

    # Raising here replaces the less clear parse error pyarrow would raise reading an empty file over range requests.
    if data is not None and len(data) == 0:
        raise ValueError(
            "The backing Parquet object is empty (0 bytes) and cannot be read. "
            "This likely indicates a corrupt or incompletely-written file; "
            "please reach out to Roboto support if the problem persists."
        )

    if data is not None and len(data) < _STREAM_WHOLE_FILE_PROBE_BYTES:
        return pq.ParquetFile(pa.BufferReader(data))

    return _range_stream()


def open_parquet_file(
    url_provider: typing.Callable[[], str],
    cache_outfile: typing.Optional[pathlib.Path],
    policy: CachePolicy,
    estimated_column_count: int,
    size_bytes: typing.Optional[int] = None,
) -> pyarrow.parquet.ParquetFile:
    """Open a remote Parquet file from the local cache, a new download to it, or HTTP, as a cache policy selects.

    :py:func:`~roboto.storage.cache.choose_fetch_mode` selects one of three sources:

    1. A copy already at ``cache_outfile``, read without a request.
    2. A copy downloaded to ``cache_outfile`` by :py:func:`~roboto.storage.cache.download_to_cache`, which never
       leaves a partial file there.
    3. The remote file, read over HTTP by ``parquet_file_from_url`` without writing to disk.

    Args:
        url_provider: Function that returns a signed URL for the file. Called at most once, and only when the file is
            downloaded or read over HTTP.
        cache_outfile: Local cache path of the file. ``None`` reads the file over HTTP, whatever ``policy`` says.
        policy: Cache policy of the read.
        estimated_column_count: Number of columns the read is expected to need. Under
            :py:attr:`~roboto.storage.CachePolicy.ADAPTIVE`, it decides between downloading the file and reading it
            over HTTP.
        size_bytes: Size of the remote file in bytes, as Roboto reports it. ``None`` when unknown, which accepts a
            cached copy of any size and skips the downloaded file's size check. When given, a cached copy of a
            different size is not read, and a size of at least 16 MiB skips the first request of
            ``parquet_file_from_url``.

    Raises:
        ValueError: The downloaded file's size differs from ``size_bytes``, or the file read over HTTP is empty.
        urllib.error.URLError: The download request fails.
        ImportError: The ``roboto[analytics]`` extra is not installed.
    """
    pq = import_optional_dependency("pyarrow.parquet", "analytics")

    effective_policy = policy if cache_outfile is not None else CachePolicy.NEVER
    mode = choose_fetch_mode(
        policy=effective_policy,
        already_cached=cache_outfile is not None and cached_file_is_current(cache_outfile, size_bytes),
        estimated_column_count=estimated_column_count,
    )

    if mode is FetchMode.STREAM:
        logger.debug("Streaming Parquet file over HTTP (policy=%s)", effective_policy.value)
        return parquet_file_from_url(url_provider(), size_bytes=size_bytes)

    # choose_fetch_mode returns CACHED or DOWNLOAD only when cache_outfile is set.
    outfile = typing.cast(pathlib.Path, cache_outfile)
    if mode is FetchMode.DOWNLOAD:
        logger.debug("Downloading Parquet file to local cache at %s (policy=%s)", outfile, effective_policy.value)
        download_to_cache(url_provider, outfile, expected_size=size_bytes)
    else:
        logger.debug("Using already-cached Parquet file at %s", outfile)
    return pq.ParquetFile(outfile)
