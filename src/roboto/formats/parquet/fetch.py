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
    choose_fetch_mode,
    download_to_cache,
)

if typing.TYPE_CHECKING:
    import pyarrow.parquet  # pants: no-infer-dep

logger = default_logger()

_STREAM_WHOLE_FILE_PROBE_BYTES = 16 * 1024 * 1024
"""Streamed Parquet files whose head probe returns fewer bytes than this are read whole from memory."""


def parquet_file_from_url(
    signed_url: str,
    size_bytes: typing.Optional[int] = None,
) -> pyarrow.parquet.ParquetFile:
    """Open a Parquet file over HTTP via a signed URL (no local download).

    A single ranged GET over fsspec's shared HTTP session probes the first
    ``_STREAM_WHOLE_FILE_PROBE_BYTES`` of the file. A file smaller than the probe
    arrives whole in that one request and is read from an in-memory buffer; a
    larger file (or a failed probe) falls back to HTTP range-request streaming
    through pyarrow's filesystem layer.

    When ``size_bytes`` is known and at least ``_STREAM_WHOLE_FILE_PROBE_BYTES``,
    the file is known-large up front: the whole-file probe could never win (a
    BufferReader read is taken only for sub-threshold files), so it is skipped
    and the file is range-streamed directly, avoiding a wasted 16 MiB GET.
    ``size_bytes`` of ``None`` (an older server omits the size) preserves the
    probe-then-decide behavior.

    Args:
        signed_url: The file's signed download URL.
        size_bytes: The backing object's size in bytes when the server reports
            it; ``None`` when unknown.

    Raises:
        ValueError: The probe succeeds but the object is empty (0 bytes), which
            is not a readable Parquet file.
    """
    fs = import_optional_dependency("pyarrow.fs", "analytics")
    fsspec_http = import_optional_dependency("fsspec.implementations.http", "analytics")
    pa = import_optional_dependency("pyarrow", "analytics")
    pq = import_optional_dependency("pyarrow.parquet", "analytics")

    http_fs = fsspec_http.HTTPFileSystem()

    def _range_stream() -> pyarrow.parquet.ParquetFile:
        return pq.ParquetFile(signed_url, filesystem=fs.PyFileSystem(fs.FSSpecHandler(http_fs)))

    if size_bytes is not None and size_bytes >= _STREAM_WHOLE_FILE_PROBE_BYTES:
        # Known-large file: skip the probe that could never win and stream directly.
        return _range_stream()

    try:
        data = http_fs.cat_file(signed_url, start=0, end=_STREAM_WHOLE_FILE_PROBE_BYTES)
    except Exception:
        logger.debug(
            "Head probe of streamed Parquet file failed; falling back to range-request streaming",
            exc_info=True,
        )
        data = None

    # A successful probe that returns zero bytes is an empty (0-byte) object, not
    # a small Parquet file: surface a clear error here rather than range-stream
    # into an obscure pyarrow parse failure. A failed probe (``data is None``)
    # instead falls back to range-streaming, as the file may simply be unprobeable.
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
    """Open a remote Parquet file under a cache policy, from the cheapest available source.

    Dispatches on :py:func:`~roboto.storage.cache.choose_fetch_mode`: an
    already-cached copy is reused, a download is performed (concurrency-safe,
    atomic) when the policy calls for one, and otherwise the file is streamed
    over HTTP range requests without touching disk.

    Args:
        url_provider: Resolves the file's signed download URL. Called at most
            once, and only when the chosen mode actually needs the URL.
        cache_outfile: The file's stable local cache path, or ``None`` when no
            cache location is configured (forces streaming).
        policy: The caller's cache policy.
        estimated_column_count: How many columns the read is expected to
            project; informs the ``ADAPTIVE`` download-vs-stream choice.
        size_bytes: The backing object's size in bytes when the server reports
            it; ``None`` when unknown. On the STREAM path it lets a known-large
            file skip the whole-file head probe; on the DOWNLOAD path it verifies
            the downloaded file is complete before it is promoted to the cache.

    Returns:
        An open ``pyarrow.parquet.ParquetFile``.
    """
    pq = import_optional_dependency("pyarrow.parquet", "analytics")

    effective_policy = policy if cache_outfile is not None else CachePolicy.NEVER
    mode = choose_fetch_mode(
        policy=effective_policy,
        already_cached=cache_outfile is not None and cache_outfile.exists(),
        estimated_column_count=estimated_column_count,
    )

    if mode is FetchMode.STREAM:
        logger.debug("Streaming Parquet file over HTTP (policy=%s)", effective_policy.value)
        return parquet_file_from_url(url_provider(), size_bytes=size_bytes)

    # choose_fetch_mode returns CACHED or DOWNLOAD only when a cache path exists.
    outfile = typing.cast(pathlib.Path, cache_outfile)
    if mode is FetchMode.DOWNLOAD:
        logger.debug("Downloading Parquet file to local cache at %s (policy=%s)", outfile, effective_policy.value)
        download_to_cache(url_provider, outfile, expected_size=size_bytes)
    else:
        logger.debug("Using already-cached Parquet file at %s", outfile)
    return pq.ParquetFile(outfile)
