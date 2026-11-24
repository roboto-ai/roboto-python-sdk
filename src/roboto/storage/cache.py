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
"""Number of columns at or above which a ``CachePolicy.ADAPTIVE`` read downloads a file.

Reading over HTTP fetches only the requested columns, but requests each column's bytes separately, so it slows as the
number of columns grows. Below 10 columns, reading over HTTP is faster; from 10 on, downloading the whole file once is.
"""


class CachePolicy(str, enum.Enum):
    """Cache policy of a topic data read: whether each data file is downloaded to the local cache before it is read.

    Applies to Parquet data files. MCAP data files are always read over HTTP, whatever the policy.
    """

    ALWAYS = "always"
    """Each file is downloaded to the local cache before it is read, unless a copy is already there."""

    ADAPTIVE = "adaptive"
    """A copy already in the local cache is read from there; otherwise the column count picks download or HTTP.

    The file is downloaded when the read needs at least 10 columns
    (``COLUMN_COUNT_LOCAL_CACHE_THRESHOLD``), and read over HTTP when it needs fewer.
    """

    NEVER = "never"
    """Every file is read over HTTP; the local cache is neither read nor written."""


class FetchMode(enum.Enum):
    """Source a remote data file is opened from, as ``choose_fetch_mode`` chooses it.

    :py:meth:`~roboto.domain.topics.Topic.get_data` and :py:func:`~roboto.formats.parquet.open_parquet_file` open
    Parquet files through it, so most code never uses it.
    """

    CACHED = enum.auto()
    """Copy already in the local cache."""

    DOWNLOAD = enum.auto()
    """Copy downloaded to the local cache for this read."""

    STREAM = enum.auto()
    """Remote file, read over HTTP without writing to disk."""


def choose_fetch_mode(
    policy: CachePolicy,
    already_cached: bool,
    estimated_column_count: int,
) -> FetchMode:
    """Choose the source to open a remote data file from, under a cache policy.

    :py:meth:`~roboto.domain.topics.Topic.get_data` and :py:func:`~roboto.formats.parquet.open_parquet_file` choose
    how to open each Parquet file through it, so most code never calls it. A copy already in the local cache is used
    under every policy except ``CachePolicy.NEVER``, however many columns the read needs, because opening it makes no
    request.

    Args:
        policy: Cache policy of the read.
        already_cached: Whether a usable copy of the file is already in the local cache.
        estimated_column_count: Number of columns the read is expected to need. Under ``ADAPTIVE``, compared with
            ``COLUMN_COUNT_LOCAL_CACHE_THRESHOLD``.
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


def cached_file_is_current(path: pathlib.Path, expected_size: typing.Optional[int]) -> bool:
    """Check whether the file at a local cache path can be read instead of downloaded again.

    :py:func:`~roboto.formats.parquet.open_parquet_file` checks a cached copy through it before reading it, so most
    code never calls it. The file is current when it exists and its size equals ``expected_size``, or when
    ``expected_size`` is ``None``. A file of a different size no longer matches the remote file, so it is downloaded
    again.

    Args:
        path: Local cache path to check.
        expected_size: Current size of the remote file, in bytes. ``None`` accepts a cached file of any size.

    Returns:
        ``True`` when the cached file can be read; ``False`` when it is missing or its size differs.
    """
    if not path.exists():
        return False
    if expected_size is None:
        return True
    return path.stat().st_size == expected_size


_download_locks: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
"""Download locks for this process, keyed by cache path.

Threads in this process that download the same file share one lock, so the file is downloaded once. Processes do not
share these locks; ``download_to_cache`` renames each finished download into place, so a reader in any process finds
either no file or a complete one.

The dictionary holds its locks weakly. An entry lives while a caller of ``download_to_cache`` holds its lock and
disappears after the last one returns, so the dictionary holds only the locks of downloads in progress.
"""

_download_locks_guard = threading.Lock()
"""Makes the lookup and insert in ``get_download_lock`` one step, so two threads asking for one path get one lock."""


def get_download_lock(key: str) -> threading.Lock:
    """Return this process's download lock for a cache path, creating it on first use.

    ``download_to_cache`` takes its lock through it, so most code never calls it. Threads that download the same file
    share the lock, so they wait for one another.

    Args:
        key: Cache path of the file, as a string.
    """
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
    """Download a remote file to a local cache path, so that no reader ever finds a partial file there.

    :py:meth:`~roboto.domain.topics.Topic.get_data` and :py:func:`~roboto.formats.parquet.open_parquet_file` download
    files to the local cache through it, so most code never calls it. It works in these steps:

    1. Wait for this process's lock on ``outfile``, so threads that download the same file download it once.
    2. Return if a current copy is already at ``outfile`` (see
       ``cached_file_is_current``); another thread may have downloaded it during the wait.
    3. Create ``outfile``'s directory if needed, and download to a uniquely named ``.part`` file beside it.
    4. When ``expected_size`` is given, compare the ``.part`` file's size with it. ``urllib.request.urlretrieve`` does
       not detect a truncated body when the response has no ``Content-Length``, so this check keeps a truncated
       download out of the cache.
    5. Rename the ``.part`` file to ``outfile`` with ``os.replace``, which replaces it in one step on POSIX and
       Windows. When two processes download the same file, the later rename replaces one complete file with another.

    If the download, the size check or the rename raises, including on ``KeyboardInterrupt``, the ``.part`` file is
    deleted, ``outfile`` is left as it was, and the exception propagates.

    Args:
        url_provider: Function that returns a signed URL for the file. Called only when the file is downloaded, so no
            URL is signed for a file already in the cache.
        outfile: Local cache path to download the file to.
        expected_size: Size of the remote file in bytes, as Roboto reports it. ``None`` skips the size check and
            accepts any copy already at ``outfile``.

    Raises:
        ValueError: ``expected_size`` is given and the downloaded file has a different size.
        urllib.error.URLError: The download request fails.
    """
    lock = get_download_lock(str(outfile))
    with lock:
        if cached_file_is_current(outfile, expected_size):
            return

        outfile.parent.mkdir(parents=True, exist_ok=True)
        tmpfile = outfile.with_name(f"{outfile.name}.{uuid.uuid4().hex}.part")

        url = url_provider()
        logger.debug("Downloading file to local cache at %s", outfile)
        try:
            urllib.request.urlretrieve(url, str(tmpfile))  # noqa: S310 — signed URL from Roboto
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
