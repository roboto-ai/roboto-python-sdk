# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import concurrent.futures
import logging
import os
import typing
import urllib.parse

import urllib3

from ..http.tls import https_ssl_context
from .sparse_buffer import SparseBuffer

logger = logging.getLogger(__name__)


_READ_AHEAD_SIZE = 8 * 1024 * 1024
"""Default number of bytes a read fetches from its position when the cache lacks them.

A large value keeps the request count low when reading consecutive data, at the cost of fetching bytes past the end
of a small read; the latency of each request costs more than the extra bytes for most reads.
"""

_SMALL_FILE_THRESHOLD = 2 * 1024 * 1024
"""Number of bytes at or below which the reader fetches the whole file when it opens.

An MCAP reader reads the footer, then the summary, then the data, so a small file read range by range costs more
requests than fetching it whole.
"""

_GAP_COALESCE_THRESHOLD = 64 * 1024
"""Number of bytes at or below which a fetch extends across the gap between it and a cached range.

Fetching the gap with the read joins the new bytes to the cached range, so a later read of the gap needs no request
of its own.
"""

_MAGIC_CHECK_THRESHOLD = 64
"""Number of bytes at or below which a read at offset 0 fetches only the bytes it asks for.

Such a read is a check of the file's magic bytes, as ``mcap.reader.SeekingReader`` makes on its first 8 bytes, so
read-ahead would fetch data the caller may never read.
"""

_FOOTER_READ_BEHIND_SIZE = 128 * 1024
"""Number of bytes at the end of the file that the reader fetches together, in one request.

An MCAP file keeps its summary and footer there, and a reader reads both before any data, so one request serves
them.
"""


def _is_running_in_aws() -> bool:
    """Return whether the process runs on Amazon ECS or AWS Lambda, judged by environment variables they set."""

    if os.environ.get("ECS_CONTAINER_METADATA_URI"):
        return True
    if os.environ.get("ECS_CONTAINER_METADATA_URI_V4"):
        return True

    if os.environ.get("AWS_EXECUTION_ENV"):
        return True

    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return True

    return False


def _get_min_bytes_per_thread() -> int:
    """Return how many bytes of a prefetch range justify one more parallel connection.

    Each connection pays for a TCP handshake, TLS negotiation and TCP slow start. On a slow link, parallel
    connections make up for slow start, so the threshold is 1 MiB. On Amazon ECS or AWS Lambda the network is fast
    enough that the setup of more connections usually costs more than it saves, so the threshold is 100 MiB.
    """
    if _is_running_in_aws():
        return 100 * 1024 * 1024
    else:
        return 1024 * 1024


_MIN_BYTES_PER_THREAD = _get_min_bytes_per_thread()


_MAX_PREFETCH_THREADS = 32
"""Maximum number of connections a reader opens, and of parallel requests in one prefetch.

Range requests spend their time waiting on the network, not the CPU, so the limit does not scale with the core
count; 32 is the cap ``concurrent.futures.ThreadPoolExecutor`` puts on its default worker count.
``_MIN_BYTES_PER_THREAD`` keeps a small prefetch from using that many.
"""


def _raise_for_status(resp: typing.Any, what: str, url: str) -> None:
    """Reject a range request's response whose status is not 200 or 206, by raising ``OSError``.

    A server answers a range request with 206 (Partial Content), or with 200 and the whole file when it ignores the
    ``Range`` header. Any other status, such as 403 for an expired signed URL, comes with an error payload, which
    must never be stored as file bytes.
    """
    status = getattr(resp, "status", None)
    if status is not None and status not in (200, 206):
        raise OSError(
            f"HTTP {status} from {what}; the response body is an error payload, not file bytes. "
            f"This is a transport/auth failure (e.g. an expired presigned URL), "
            f"not a lack of HTTP Range support. URL: {url}"
        )


class HttpRangeReader:
    """A seekable, read-only file-like object over a file at an HTTP URL, which fetches only the bytes it reads.

    It implements the methods of ``typing.IO[bytes]`` that ``mcap.reader`` calls, such as ``read``, ``seek`` and
    ``tell``; ``as_io_bytes`` types it as ``typing.IO[bytes]``.

    Constructing the reader requests the file's first 8 bytes and its last 128 KiB at the same time, and takes the
    file's size from the first response. A file of at most 2 MiB is then fetched whole.

    Reads come from an in-memory cache that keeps every byte fetched, so reading the same bytes again makes no
    request. A read the cache cannot serve fetches ``read_ahead_size`` bytes from its position, or the whole of the
    file's last 128 KiB when it starts there. A fetch leaves out cached bytes at either end, and extends across a gap
    of at most 64 KiB to a neighboring cached range. ``prefetch_range`` fetches a known range ahead of reads, over
    parallel connections.

    Requests share a pool of at most 32 connections to the URL's host, and each request is retried up to 3 times on
    a network error.

    Args:
        url: URL of the file, such as a signed download URL. The server must answer HTTP ``Range`` requests.
        read_ahead_size: Number of bytes a read fetches from its position when the cache lacks them, unless the read
            asks for more. Defaults to 8 MiB.

    Raises:
        OSError: The server answers either opening request with a status other than 200 or 206, sends no
            ``Content-Range`` header with the file's size, or, for a file of at most 2 MiB, returns a last-128-KiB
            response that stops short of the end of the file. Later reads and prefetches raise ``OSError`` when a
            response has an HTTP error status or holds bytes other than the ones requested.
        urllib3.exceptions.MaxRetryError: An opening request still fails with a network error after 3 retries. Later
            reads and prefetches raise it the same way.
    """

    __pool: urllib3.HTTPConnectionPool | urllib3.HTTPSConnectionPool

    def __init__(self, url: str, read_ahead_size: int = _READ_AHEAD_SIZE):
        self.__url = url
        self.__read_ahead_size = read_ahead_size
        self.__pos = 0

        parsed = urllib.parse.urlparse(url)
        self.__scheme = parsed.scheme
        self.__host = parsed.netloc
        # Requests carry the query string too, since a signed URL's signature is in it.
        self.__path = parsed.path
        if parsed.query:
            self.__path += "?" + parsed.query

        # Requests reuse the pool's connections instead of repeating TCP and TLS setup. With block=True, a
        # request waits for a free connection rather than opening more than _MAX_PREFETCH_THREADS.
        if self.__scheme == "https":
            self.__pool = urllib3.HTTPSConnectionPool(
                self.__host,
                maxsize=_MAX_PREFETCH_THREADS,
                block=True,
                retries=urllib3.Retry(total=3),
                ssl_context=https_ssl_context(),
            )
        else:
            self.__pool = urllib3.HTTPConnectionPool(
                self.__host, maxsize=_MAX_PREFETCH_THREADS, block=True, retries=urllib3.Retry(total=3)
            )

        # The pool holds sockets, and a caller whose constructor call raised has no reader to close. Close the
        # pool on any exception from the opening requests, then re-raise it.
        try:
            self.__open(url)
        except BaseException:
            self.__pool.close()
            raise

    def __enter__(self) -> "HttpRangeReader":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def size(self) -> int:
        """Size of the file, in bytes."""
        return self.__size

    def close(self) -> None:
        """Release the reader's cached bytes and its HTTP connections."""
        self.__buffer.clear()
        self.__pool.close()

    def prefetch_range(self, start: int, end: int) -> None:
        """Download the bytes from ``start`` through ``end`` into the cache, over parallel requests.

        Bytes the cache already holds, such as the ones fetched when the reader opened, are not fetched again. The
        rest are fetched in parallel requests of at most 1/N of the whole range each, where N is the number of whole
        MiB in the range, from 1 to 32. On Amazon ECS or AWS Lambda, N counts whole 100 MiB instead, since more
        connections rarely make the transfer faster there.

        Args:
            start: Offset of the first byte to fetch.
            end: Offset of the last byte to fetch. The range includes it.

        Raises:
            OSError: A response has an HTTP error status or holds bytes other than the ones requested.
            urllib3.exceptions.MaxRetryError: A request still fails with a network error after 3 retries.
        """
        # Subtract cached regions from [start, end], leaving uncovered spans.
        spans = [(start, end)]
        for region_start, region_end in self.__buffer.regions:  # region_end is exclusive
            remaining: list[tuple[int, int]] = []
            for span_start, span_end in spans:
                if region_end <= span_start or region_start > span_end:
                    remaining.append((span_start, span_end))
                    continue
                if span_start < region_start:
                    remaining.append((span_start, region_start - 1))
                if span_end >= region_end:
                    remaining.append((region_end, span_end))
            spans = remaining
            if not spans:
                return

        # Size the batches from the whole range, not the uncached bytes, so cached bytes never lower the number of
        # parallel requests below what the uncached range would get.
        total_size = end - start + 1
        num_batches = max(1, min(total_size // _MIN_BYTES_PER_THREAD, _MAX_PREFETCH_THREADS))
        chunk_size = (total_size + num_batches - 1) // num_batches

        batches: list[tuple[int, int]] = []
        for span_start, span_end in spans:
            pos = span_start
            while pos <= span_end:
                batch_end = min(pos + chunk_size - 1, span_end)
                batches.append((pos, batch_end))
                pos = batch_end + 1

        self.__fetch_batches_parallel(batches)

    def read(self, size: int = -1) -> bytes:
        if self.__pos >= self.__size:
            return b""
        if size < 0:
            size = self.__size - self.__pos

        size = min(size, self.__size - self.__pos)

        # Serve the read from the cache when one cached range holds every requested byte.
        cached = self.__buffer.find_region(self.__pos, size)
        if cached is not None:
            self.__pos += len(cached)
            return cached

        fetch_start, fetch_end = self.__compute_fetch_range(self.__pos, size)
        if fetch_start < fetch_end:
            data = self.__fetch(fetch_start, fetch_end - fetch_start)
            self.__buffer.add_region(fetch_start, data)

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
        """Return the ``(fetch_start, fetch_end)`` byte range to fetch for a read of ``min_size`` bytes at ``start``.

        ``fetch_end`` is exclusive. The range is empty when there is nothing to fetch.
        """
        # Opening the reader caches the first 8 bytes, so this applies to reads of 9 to _MAGIC_CHECK_THRESHOLD bytes.
        if start == 0 and min_size <= _MAGIC_CHECK_THRESHOLD:
            return 0, min_size

        # A read in the file's last _FOOTER_READ_BEHIND_SIZE bytes fetches all of them instead of reading ahead.
        end_of_file_threshold = self.__size - _FOOTER_READ_BEHIND_SIZE
        if start >= end_of_file_threshold:
            fetch_start = max(0, self.__size - _FOOTER_READ_BEHIND_SIZE)
            fetch_end = self.__size
        else:
            fetch_start = start
            fetch_end = min(start + max(min_size, self.__read_ahead_size), self.__size)

        # Trim cached bytes off either end of the fetch. A cached region strictly inside the fetch is fetched again
        # rather than splitting the request in two; add_region merges the overlap.
        for region_start, region_end in self.__buffer.regions:
            # Move fetch_start to this region's end when it lies inside the region, whose bytes are cached, or
            # within _GAP_COALESCE_THRESHOLD bytes past it, so the fetch also covers that gap.
            if region_start <= fetch_start <= region_end + _GAP_COALESCE_THRESHOLD:
                fetch_start = region_end

            # Move fetch_end to this region's start under the same two conditions, mirrored.
            if region_start - _GAP_COALESCE_THRESHOLD <= fetch_end <= region_end:
                fetch_end = region_start

        if fetch_start >= fetch_end:
            return start, start

        return fetch_start, fetch_end

    def __fetch(self, start: int, length: int) -> bytes:
        """Download ``length`` bytes at ``start`` in one range request, stopping at the end of the file."""
        end = min(start + length - 1, self.__size - 1)
        resp = self.__pool.request("GET", self.__path, headers={"Range": f"bytes={start}-{end}"})
        return self.__ranged_bytes(resp, start, f"range fetch bytes={start}-{end}")

    def __fetch_batches_parallel(self, batches: list[tuple[int, int]]) -> None:
        """Download each ``(start, end)`` batch, ends inclusive, into the cache, in parallel when there are several."""
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
            return (
                batch_start,
                self.__ranged_bytes(resp, batch_start, f"parallel range fetch bytes={batch_start}-{batch_end}"),
            )

        results: list[tuple[int, bytes]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batches)) as executor:
            futures = [executor.submit(fetch_one, batch) for batch in batches]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        # Insert in offset order so adjacent batches extend the buffer's regions
        # sequentially rather than triggering repeated merge copies.
        results.sort(key=lambda r: r[0])
        for start, data in results:
            self.__buffer.add_region(start, data)

    def __open(self, url: str) -> None:
        """Learn the file's size and fill the cache with the bytes an MCAP reader reads first.

        Fetches the file's first 8 bytes and its last ``_FOOTER_READ_BEHIND_SIZE`` bytes, and for a file of at most
        ``_SMALL_FILE_THRESHOLD`` bytes the rest of it. ``__init__`` closes the connection pool when this raises.
        """
        # The first request's Content-Range header carries the file's size. The second asks for a suffix range,
        # which is the whole file when the file is smaller than _FOOTER_READ_BEHIND_SIZE.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            head_future = executor.submit(self.__pool.request, "GET", self.__path, headers={"Range": "bytes=0-7"})
            tail_future = executor.submit(
                self.__pool.request, "GET", self.__path, headers={"Range": f"bytes=-{_FOOTER_READ_BEHIND_SIZE}"}
            )
            head_resp = head_future.result()
            tail_resp = tail_future.result()

        # Check the status before reading either body. An expired signed URL answers 403 with an error payload and
        # no Content-Range, which the check below would misreport as a server without Range support.
        _raise_for_status(head_resp, "open-time magic-prefix request", url)
        _raise_for_status(tail_resp, "open-time footer-suffix request", url)

        content_range = head_resp.headers.get("Content-Range", "")
        # Content-Range header looks like: `bytes 0-7/<total>`
        if not content_range or "/" not in content_range:
            raise OSError(
                f"Server does not support HTTP Range requests. "
                f"Expected 'Content-Range' header in response, got: {head_resp.headers!r}. "
                f"URL: {url}"
            )
        try:
            self.__size = int(content_range.split("/")[-1])
        except ValueError:
            raise OSError(f"Failed to parse file size from Content-Range header: {content_range!r}. URL: {url}")

        self.__buffer = SparseBuffer(self.__size)
        self.__buffer.add_region(0, head_resp.data)

        # Cache the tail bytes only when a Content-Range of `bytes <start>-<end>/<total>` gives their offset.
        tail_start = self.__size
        tail_reaches_eof = False
        if tail_resp.data:
            tail_content_range = tail_resp.headers.get("Content-Range", "")
            range_spec = tail_content_range.split("/")[0].removeprefix("bytes").strip()
            try:
                tail_start = int(range_spec.split("-")[0])
                tail_end = int(range_spec.split("-")[1])
            except (ValueError, IndexError):
                tail_start = self.__size
            else:
                self.__buffer.add_region(tail_start, tail_resp.data)
                # A proxy that rewrites the suffix range can return bytes that stop short of the end of the file.
                tail_reaches_eof = tail_end == self.__size - 1

        if self.__size <= _SMALL_FILE_THRESHOLD:
            # The gap fetch below stops at tail_start, so the tail must reach the end of the file for the cache to
            # hold all of it.
            if not tail_reaches_eof:
                raise OSError(
                    f"Suffix-range (footer) response did not reach end of file: "
                    f"tail covers up to {tail_start}-?, file size is {self.__size}. "
                    f"The server/proxy returned an incomplete tail, which would leave "
                    f"a coverage gap at EOF. URL: {url}"
                )

            if tail_start > 8:
                # Fetch the bytes between the first 8 and the cached tail.
                remaining = self.__fetch(8, tail_start - 8)
                self.__buffer.add_region(8, remaining)

    def __ranged_bytes(self, resp: typing.Any, expected_start: int, what: str) -> bytes:
        """Return a range response's body, after checking that it holds the bytes starting at ``expected_start``.

        Raises ``OSError`` otherwise. A 206 response must carry a Content-Range whose start is ``expected_start``. A
        200 response, sent by a server that ignored the Range header, holds the whole file, which is the requested
        bytes only when ``expected_start`` is 0; at any other offset, caching it would corrupt later reads.
        """
        _raise_for_status(resp, what, self.__url)
        status = getattr(resp, "status", None)
        if status == 200:
            if expected_start == 0:
                return resp.data
            raise OSError(
                f"HTTP 200 (full body) from {what}: the server ignored the Range header and "
                f"returned the whole object, which cannot be stored at nonzero offset "
                f"{expected_start} without corrupting the read. URL: {self.__url}"
            )

        # _raise_for_status rejected every status but 200 and 206, so this is a 206. Parse the start of its
        # Content-Range (`bytes <start>-<end>/<total>`); a missing or malformed header leaves returned_start None,
        # which fails the comparison below.
        content_range = resp.headers.get("Content-Range", "")
        spec = content_range.split("/")[0].removeprefix("bytes").strip()
        try:
            returned_start: typing.Optional[int] = int(spec.split("-")[0])
        except (ValueError, IndexError):
            returned_start = None

        if returned_start != expected_start:
            raise OSError(
                f"Ranged {what} returned Content-Range {content_range!r} (start {returned_start}), "
                f"expected start {expected_start}; response cannot be trusted as the requested "
                f"bytes. URL: {self.__url}"
            )

        return resp.data


def as_io_bytes(reader: HttpRangeReader) -> typing.IO[bytes]:
    """Return ``reader`` unchanged, typed as ``typing.IO[bytes]`` for type checkers.

    ``HttpRangeReader`` implements only the methods of ``typing.IO[bytes]`` that
    ``mcap.reader`` calls, such as ``read``, ``seek`` and ``tell``, so pass the result only to code that calls no
    others.

    Args:
        reader: Reader to pass where a ``typing.IO[bytes]`` is expected.
    """
    return typing.cast(typing.IO[bytes], reader)
