# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import enum
import os
import pathlib
import threading
import typing
import urllib.request
import uuid
import weakref

from ..logging import default_logger

logger = default_logger()

COLUMN_COUNT_LOCAL_CACHE_THRESHOLD = 10
"""Column count at or above which an ``ADAPTIVE`` read downloads the whole file instead of streaming.

Streaming projects only the requested columns but pays a per-column HTTP cost,
so reading many columns over the network grows slow; downloading fetches the
whole file once. 10 is the crossover: below it, streaming's wasted-bytes savings
win; at or above it, the per-column overhead dominates and the local copy is
reliably faster.
"""


class CachePolicy(str, enum.Enum):
    """Governs whether a fetched data file is cached to local disk before reading.

    The policy applies to formats with a disk-cache path (Parquet today); a
    format that always streams (MCAP) ignores it.
    """

    ALWAYS = "always"
    """Download the file to the local cache before reading, regardless of how much of it the read projects."""

    ADAPTIVE = "adaptive"
    """Reuse an already-cached file; otherwise download when the read projects enough columns
    (:py:data:`COLUMN_COUNT_LOCAL_CACHE_THRESHOLD`) to justify it, and stream over HTTP when it does not."""

    NEVER = "never"
    """Always stream over HTTP; never write to local disk."""


class FetchMode(enum.Enum):
    """How a single remote file will be opened, as chosen by :py:func:`choose_fetch_mode`."""

    CACHED = enum.auto()
    """Open the already-downloaded copy in the local cache."""

    DOWNLOAD = enum.auto()
    """Download to the local cache, then open the downloaded copy."""

    STREAM = enum.auto()
    """Open over HTTP without writing to disk."""


def choose_fetch_mode(
    policy: CachePolicy,
    already_cached: bool,
    estimated_column_count: int,
) -> FetchMode:
    """Pick the cheapest way to open a remote columnar file under a cache policy.

    A previously-downloaded file is always cheaper to open than streaming over
    HTTP, regardless of how many columns the current read projects, so an
    existing cached copy wins under every policy except ``NEVER`` (which never
    touches the disk cache at all, not even to read it).

    Args:
        policy: The caller's cache policy.
        already_cached: Whether a complete copy already exists in the local cache.
        estimated_column_count: How many columns the read is expected to project;
            compared against :py:data:`COLUMN_COUNT_LOCAL_CACHE_THRESHOLD` under
            ``ADAPTIVE``.

    Returns:
        The fetch mode to use.
    """
    if policy is CachePolicy.NEVER:
        return FetchMode.STREAM
    if already_cached:
        return FetchMode.CACHED
    if policy is CachePolicy.ALWAYS:
        return FetchMode.DOWNLOAD
    if estimated_column_count >= COLUMN_COUNT_LOCAL_CACHE_THRESHOLD:
        return FetchMode.DOWNLOAD
    return FetchMode.STREAM


_download_locks: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
"""In-process registry of per-file download locks, keyed by absolute cache path.

Dedupes concurrent downloads of the same file within a single process.
Cross-process concurrency is handled by the atomic-rename pattern in
``download_to_cache`` (last writer wins, but every observed file is complete),
not by this lock.

Values are held weakly: while at least one caller is inside
``download_to_cache`` for a path, that caller's local reference keeps the lock
alive and concurrent callers share it; once the last returns, the entry is
evicted automatically. Footprint stays bounded by in-flight downloads rather
than by lifetime-unique paths.
"""

_download_locks_guard = threading.Lock()
"""Guards inserts into ``_download_locks``."""


def get_download_lock(key: str) -> threading.Lock:
    """Return the in-process download lock for a cache path, creating it on first use."""
    with _download_locks_guard:
        lock = _download_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _download_locks[key] = lock
        return lock


def download_to_cache(
    url_provider: typing.Callable[[], str],
    outfile: pathlib.Path,
    expected_size: typing.Optional[int] = None,
) -> None:
    """Download a remote file to ``outfile`` safely under concurrency.

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

    When ``expected_size`` is supplied, the written ``.part`` file's size is
    verified against it before the atomic rename. A truncated body — which
    :func:`urllib.request.urlretrieve` does not flag when the response carries
    no ``Content-Length`` — fails this check, so the ``.part`` is discarded and
    nothing is promoted to the cache: a partial download is never made sticky.

    Args:
        url_provider: Resolves the download URL. Called only when the download
            actually proceeds, so a signed URL is not minted for a file that
            turns out to already be cached.
        outfile: Final cache path for the downloaded file.
        expected_size: The backing object's size in bytes when the server
            reports it; ``None`` skips the completeness check.

    Raises:
        ValueError: ``expected_size`` is supplied and the downloaded file's size
            does not match it (a truncated or otherwise incomplete download).
    """
    lock = get_download_lock(str(outfile))
    with lock:
        if outfile.exists():
            return

        outfile.parent.mkdir(parents=True, exist_ok=True)
        tmpfile = outfile.with_name(f"{outfile.name}.{uuid.uuid4().hex}.part")

        url = url_provider()
        logger.debug("Downloading file to local cache at %s", outfile)
        try:
            urllib.request.urlretrieve(url, str(tmpfile))  # noqa: S310 — presigned S3 URL from Roboto API
            if expected_size is not None:
                actual_size = tmpfile.stat().st_size
                if actual_size != expected_size:
                    raise ValueError(
                        f"Downloaded file size {actual_size} does not match the expected size "
                        f"{expected_size}; the download was truncated or otherwise incomplete. "
                        "Rejecting it rather than caching a partial file."
                    )
            os.replace(tmpfile, outfile)
        except BaseException:
            tmpfile.unlink(missing_ok=True)
            raise
