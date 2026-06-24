# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import mcap.reader

from ...storage import HttpRangeReader, as_io_bytes


def open_for_window(
    signed_url: str,
    start_time: typing.Optional[int] = None,
    end_time: typing.Optional[int] = None,
) -> HttpRangeReader:
    """Open a remote MCAP file for reading, prefetching only the chunks in a log-time window.

    Reads the file's summary section to locate its chunk index, identifies the
    chunks whose message log times intersect ``[start_time, end_time)``, and
    prefetches that byte range in parallel so subsequent sequential reads hit
    the local buffer instead of issuing many small HTTP range requests. The
    returned reader is positioned at the start of the file. The caller owns it
    and must :py:meth:`~roboto.storage.HttpRangeReader.close` it.

    The window is matched against the chunk index's *log-time* bounds; when row
    timestamps come from somewhere other than the message log time, pass no
    bounds (prefetching then covers every chunk) and filter rows after decode.

    Args:
        signed_url: Resolved download URL of the MCAP file.
        start_time: Inclusive window lower bound in nanoseconds, or ``None`` for unbounded.
        end_time: Exclusive window upper bound in nanoseconds, or ``None`` for unbounded.

    Returns:
        An :py:class:`~roboto.storage.HttpRangeReader` over the file, primed
        with the in-window chunk bytes and positioned at offset 0.
    """
    http_reader = HttpRangeReader(signed_url)
    try:
        seeking_reader = mcap.reader.SeekingReader(as_io_bytes(http_reader))
        summary = seeking_reader.get_summary()

        if summary and summary.chunk_indexes:
            # Prefetch each in-window chunk's span on its own rather than one
            # bounding box over all of them. The MCAP spec does not guarantee
            # chunk-index entries are time-sorted or file-contiguous, so a single
            # [min start, max end] range over sparse in-window chunks would pull
            # every intervening out-of-window chunk's bytes; a per-chunk prefetch
            # leaves those gaps unfetched.
            for chunk_index in summary.chunk_indexes:
                if start_time is not None and chunk_index.message_end_time < start_time:
                    continue
                if end_time is not None and chunk_index.message_start_time > end_time:
                    continue

                chunk_start = chunk_index.chunk_start_offset
                chunk_end = chunk_start + chunk_index.chunk_length - 1
                http_reader.prefetch_range(chunk_start, chunk_end)

        http_reader.seek(0)
        return http_reader
    except BaseException:
        http_reader.close()
        raise
