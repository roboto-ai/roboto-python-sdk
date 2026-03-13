# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Seekable HTTP byte-range reader for efficient partial access to remote files.

This module provides a seekable file-like object backed by HTTP Range requests,
enabling efficient random access to remote files (e.g., MCAP files on S3) without
downloading the entire file.
"""

from __future__ import annotations

import concurrent.futures
import logging
import typing
import urllib.parse

import urllib3

from .sparse_buffer import SparseBuffer

logger = logging.getLogger(__name__)


_READ_AHEAD_SIZE = 8 * 1024 * 1024
"""Bytes fetched per HTTP range request.

Set to 8MB to minimize request count when reading consecutive data chunks.
For a 100MB time slice, this means ~13 requests instead of ~400 with 256KB.
The tradeoff is fetching slightly more data than needed for very small slices,
but HTTP request latency (~100-500ms each) dominates for most access patterns.
"""

_SMALL_FILE_THRESHOLD = 2 * 1024 * 1024
"""Files smaller than this are fetched entirely in one request.

For small files, the overhead of multiple range requests (due to MCAP's
non-linear access pattern: footer → summary → data) exceeds the cost of
just downloading the whole file. This threshold avoids that overhead.
"""

_GAP_COALESCE_THRESHOLD = 64 * 1024
"""Maximum gap size to fill when coalescing fetch ranges.

When fetching a region, if there's a cached region nearby with a gap smaller
than this threshold, we extend the fetch to fill the gap. This reduces the
total number of HTTP requests at the cost of fetching slightly more data.
"""

_MAGIC_CHECK_THRESHOLD = 64
"""Reads at position 0 smaller than this are considered magic byte checks.

MCAP's SeekingReader first reads 8 bytes at position 0 to verify the magic.
For these tiny reads at the start, we fetch only what's requested (no read-ahead)
to avoid wasting bandwidth on data we may not need.
"""

_FOOTER_READ_BEHIND_SIZE = 128 * 1024
"""Size to fetch when reading footer/summary at end of file.

MCAP footer is 22 bytes, and summary section is typically 10-100KB.
We fetch the last 256KB to cover both in one request, which is much
smaller than the 8MB data read-ahead size.
"""


# Parallel prefetch configuration.
# Each HTTP connection has setup overhead (TCP handshake + TLS + slow-start).
# The overhead varies dramatically by environment:
#   - Local/remote connections: ~700-1000ms latency, ~10 MB/s bandwidth
#   - AWS (ECS/Lambda to S3): ~1-5ms latency, ~1-3 GB/s bandwidth
#
# On slow connections, parallelization helps overcome TCP slow-start.
# On fast AWS connections, parallelization overhead may exceed the benefit.


def _is_running_in_aws() -> bool:
    """Detect if we're running in an AWS environment with fast S3 connectivity."""
    import os

    # ECS sets these environment variables
    if os.environ.get("ECS_CONTAINER_METADATA_URI"):
        return True
    if os.environ.get("ECS_CONTAINER_METADATA_URI_V4"):
        return True

    # Lambda sets this
    if os.environ.get("AWS_EXECUTION_ENV"):
        return True

    # AWS Lambda runtime
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return True

    return False


def _get_min_bytes_per_thread() -> int:
    """Get the minimum bytes per thread threshold based on environment."""
    if _is_running_in_aws():
        # In AWS: high bandwidth, low latency to S3
        # Parallelization rarely helps; use high threshold to avoid overhead
        return 100 * 1024 * 1024  # 100 MB
    else:
        # Local/remote: slower connections where parallelization helps
        # Lower threshold to parallelize earlier - connection overhead dominates
        return 2 * 1024 * 1024  # 2 MB


# Cache the result since environment doesn't change at runtime
_IN_AWS = _is_running_in_aws()
_MIN_BYTES_PER_THREAD = _get_min_bytes_per_thread()


def _get_max_prefetch_threads() -> int:
    """Calculate max parallel connections based on available CPUs.

    Uses ~75% of available CPUs, with a floor of 2 and ceiling of 12.
    The ceiling prevents overwhelming the network/server even on large machines.
    """
    import os

    cpu_count = os.cpu_count() or 4  # Default to 4 if detection fails
    threads = max(2, int(cpu_count * 0.75))
    return min(threads, 12)  # Cap at 12 to avoid overwhelming network


_MAX_PREFETCH_THREADS = _get_max_prefetch_threads()


class HttpRangeReader:
    """A seekable, buffered byte-range reader backed by an HTTP URL.

    Uses HTTP range requests so only the requested byte ranges are fetched,
    allowing efficient partial access to remote files (e.g., reading just the
    MCAP summary/index section at the end of a file without downloading the
    full data payload).

    Reads are satisfied from an in-memory sparse cache. HTTP requests are only
    issued on a cache miss, fetching _READ_AHEAD_SIZE bytes at a time. Unlike a
    simple single-buffer approach, this cache retains all fetched regions, so
    seeking back to previously-read data doesn't trigger re-fetches.

    This class implements the IO[bytes] protocol methods needed by mcap.reader.

    Uses urllib3 connection pooling to reuse HTTP connections across requests,
    reducing TCP handshake and TLS negotiation overhead.
    """

    __pool: urllib3.HTTPConnectionPool | urllib3.HTTPSConnectionPool

    def __init__(self, url: str, read_ahead_size: int = _READ_AHEAD_SIZE):
        """
        Initialize the reader with a presigned URL.

        Args:
            url: HTTP(S) URL supporting Range requests (e.g., S3 presigned URL)
            read_ahead_size: Number of bytes to fetch per cache miss
        """
        self.__url = url
        self.__read_ahead_size = read_ahead_size
        self.__pos = 0

        # Parse URL to set up connection pool
        parsed = urllib.parse.urlparse(url)
        self.__scheme = parsed.scheme
        self.__host = parsed.netloc
        # Reconstruct path with query string for requests
        self.__path = parsed.path
        if parsed.query:
            self.__path += "?" + parsed.query

        # Create a connection pool for HTTP connection reuse.
        # This avoids TCP handshake + TLS negotiation overhead on subsequent requests.
        # Pool size matches max parallel threads - connections are reused across
        # sequential reads (header/footer/summary) and parallel prefetch phases.
        if self.__scheme == "https":
            self.__pool = urllib3.HTTPSConnectionPool(
                self.__host, maxsize=_MAX_PREFETCH_THREADS, block=True, retries=urllib3.Retry(total=3)
            )
        else:
            self.__pool = urllib3.HTTPConnectionPool(
                self.__host, maxsize=_MAX_PREFETCH_THREADS, block=True, retries=urllib3.Retry(total=3)
            )

        # Fetch magic bytes (first 8 bytes) and get file size from Content-Range header.
        # This combines the size probe and magic check into a single request.
        resp = self.__pool.request("GET", self.__path, headers={"Range": "bytes=0-7"})
        magic_data = resp.data
        content_range = resp.headers.get("Content-Range", "")
        # Content-Range header looks like: bytes 0-7/<total>
        if not content_range or "/" not in content_range:
            raise ValueError(
                f"Server does not support HTTP Range requests. "
                f"Expected 'Content-Range' header in response, got: {resp.headers!r}. "
                f"URL: {url}"
            )
        try:
            self.__size = int(content_range.split("/")[-1])
        except ValueError as e:
            raise ValueError(
                f"Failed to parse file size from Content-Range header: {content_range!r}. URL: {url}"
            ) from e

        # Initialize sparse buffer now that we know the file size
        self.__buffer = SparseBuffer(self.__size)
        self.__buffer.add_region(0, magic_data)

        # For small files, fetch everything upfront to avoid multiple range requests
        # due to MCAP's non-linear access pattern (footer → summary → data).
        if self.__size <= _SMALL_FILE_THRESHOLD:
            # Fetch rest of file (we already have 0-7)
            remaining = self.__fetch(8, self.__size - 8)
            self.__buffer.add_region(8, remaining)

    def __enter__(self) -> "HttpRangeReader":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def size(self) -> int:
        """Get the total size of the remote file in bytes."""
        return self.__size

    def close(self) -> None:
        """Close the reader and release resources."""
        self.__buffer.clear()
        self.__pool.close()

    def prefetch_range(self, start: int, end: int) -> None:
        """Prefetch a byte range using parallel HTTP requests.

        Args:
            start: Start byte offset (inclusive)
            end: End byte offset (inclusive)
        """
        total_size = end - start + 1

        # Use same logic as __fetch_batches_parallel for thread count
        num_batches = max(1, min(total_size // _MIN_BYTES_PER_THREAD, _MAX_PREFETCH_THREADS))
        chunk_size = (total_size + num_batches - 1) // num_batches

        batches: list[tuple[int, int]] = []
        pos = start
        while pos <= end:
            batch_end = min(pos + chunk_size - 1, end)
            batches.append((pos, batch_end))
            pos = batch_end + 1

        self.__fetch_batches_parallel(batches)

    def read(self, size: int = -1) -> bytes:
        if self.__pos >= self.__size:
            return b""
        if size < 0:
            size = self.__size - self.__pos

        # Clamp to file size
        size = min(size, self.__size - self.__pos)

        # Check if fully cached first (fast path)
        cached = self.__buffer.find_region(self.__pos, size)
        if cached is not None:
            self.__pos += len(cached)
            return cached

        # Not fully cached - fetch missing data
        fetch_start, fetch_end = self.__compute_fetch_range(self.__pos, size)
        if fetch_start < fetch_end:
            data = self.__fetch(fetch_start, fetch_end - fetch_start)
            self.__buffer.add_region(fetch_start, data)

        # Read from buffer - should now be fully satisfied
        self.__buffer.seek(self.__pos)
        result = self.__buffer.read(size)

        if len(result) < size:
            raise RuntimeError(
                f"Incomplete read after fetch: got {len(result)}, expected {size}. "
                f"pos={self.__pos}, fetch_range=({fetch_start}, {fetch_end}). "
                f"This indicates a bug in fetch range calculation or buffer merge logic."
            )

        self.__pos += len(result)
        return result

    def readable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.__pos = offset
        elif whence == 1:
            self.__pos += offset
        elif whence == 2:
            self.__pos = self.__size + offset
        return self.__pos

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.__pos

    def writable(self) -> bool:
        return False

    def __compute_fetch_range(self, start: int, min_size: int) -> tuple[int, int]:
        """Compute optimal fetch range, avoiding re-fetching cached data.

        Returns (fetch_start, fetch_end) where fetch_end is exclusive.
        """
        # Detect magic byte check: small read at position 0
        # For these, don't use read-ahead - just fetch what's requested
        # (magic bytes are already cached from __init__, so this rarely triggers)
        if start == 0 and min_size <= _MAGIC_CHECK_THRESHOLD:
            return 0, min_size

        # For reads near end of file (footer/summary area), use "read-behind"
        # with a smaller fetch size to grab footer + summary without wasting bandwidth.
        # MCAP footer is 22 bytes at very end, summary is typically 10-100KB before it.
        end_of_file_threshold = self.__size - _FOOTER_READ_BEHIND_SIZE
        if start >= end_of_file_threshold:
            # Fetch last _FOOTER_READ_BEHIND_SIZE bytes to cover footer + summary
            fetch_start = max(0, self.__size - _FOOTER_READ_BEHIND_SIZE)
            fetch_end = self.__size
        else:
            # Normal read-ahead for data section
            fetch_start = start
            fetch_end = min(start + max(min_size, self.__read_ahead_size), self.__size)

        # Adjust fetch range to avoid re-fetching already cached data.
        # Note: If a cached region is entirely within the fetch range, we may
        # re-fetch it (simpler than splitting into multiple fetches). The buffer's
        # add_region handles merging correctly.
        for region_start, region_end in self.__buffer.regions:
            # If our fetch start is inside a cached region, skip past it
            if region_start <= fetch_start < region_end:
                fetch_start = region_end

            # If our fetch end overlaps into a cached region, stop before it
            if region_start < fetch_end <= region_end:
                fetch_end = region_start

            # If there's a cached region just before our fetch start with a small gap
            if region_end < fetch_start and fetch_start - region_end <= _GAP_COALESCE_THRESHOLD:
                fetch_start = region_end  # Fill the gap

            # If there's a cached region just after our fetch end with a small gap
            if region_start > fetch_end and region_start - fetch_end <= _GAP_COALESCE_THRESHOLD:
                fetch_end = region_start  # Extend to fill the gap

        # Ensure we still fetch something
        if fetch_start >= fetch_end:
            return start, start  # Nothing to fetch (fully cached)

        return fetch_start, fetch_end

    def __fetch(self, start: int, length: int) -> bytes:
        """Fetch bytes from remote URL using HTTP Range request."""
        end = min(start + length - 1, self.__size - 1)
        resp = self.__pool.request("GET", self.__path, headers={"Range": f"bytes={start}-{end}"})
        return resp.data

    def __fetch_batches_parallel(self, batches: list[tuple[int, int]]) -> None:
        """Fetch batches in parallel using connection pool."""
        if not batches:
            return

        if len(batches) == 1:
            batch_start, batch_end = batches[0]
            data = self.__fetch(batch_start, batch_end - batch_start + 1)
            self.__buffer.add_region(batch_start, data)
            return

        def fetch_one(batch: tuple[int, int]) -> tuple[int, bytes]:
            batch_start, batch_end = batch
            resp = self.__pool.request("GET", self.__path, headers={"Range": f"bytes={batch_start}-{batch_end}"})
            return (batch_start, resp.data)

        results: list[tuple[int, bytes]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batches)) as executor:
            futures = [executor.submit(fetch_one, batch) for batch in batches]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        for start, data in results:
            self.__buffer.add_region(start, data)


def as_io_bytes(reader: HttpRangeReader) -> typing.IO[bytes]:
    """Cast an HttpRangeReader to typing.IO[bytes] for type-checking purposes."""
    return typing.cast(typing.IO[bytes], reader)
