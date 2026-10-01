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
    topic_name: typing.Optional[str] = None,
) -> HttpRangeReader:
    """Open a remote MCAP file for reading, prefetching only the chunks in a log-time window and of one topic.

    Reads the file's summary section to locate its chunk index, then prefetches
    in parallel each chunk whose message log times intersect ``[start_time, end_time)``
    and, given a ``topic_name``, whose chunk index lists a message index for a channel of that topic.
    Later reads of those chunks are answered from the reader's in-memory cache.
    The returned reader is positioned at the start of the file. The
    caller owns it and must :py:meth:`~roboto.storage.HttpRangeReader.close` it.

    The window is matched against the chunk index's log-time bounds; when row
    timestamps come from somewhere other than the message log time, pass no
    bounds (prefetching then covers every chunk) and filter rows after decode.

    :py:class:`~roboto.formats.mcap.McapReader` reads through :py:meth:`mcap.reader.SeekingReader.iter_messages`,
    which picks chunks for a window and topic by the same log-time and channel rules, with one addition:
    when given topics, it also reads a chunk whose chunk index names no message index,
    since that chunk's topics are unknown until it is scanned.
    This function does not prefetch such a chunk, so its bytes are downloaded when it is read.

    Args:
        signed_url: Resolved download URL of the MCAP file.
        start_time: Inclusive window lower bound in nanoseconds, or ``None`` for unbounded.
        end_time: Exclusive window upper bound in nanoseconds, or ``None`` for unbounded.
        topic_name: Prefetch only the chunks holding a message on an MCAP channel of this topic,
            or chunks of every topic when ``None``.

    Returns:
        An :py:class:`~roboto.storage.HttpRangeReader` over the file, primed
        with the selected chunks' bytes and positioned at offset 0.
    """
    http_reader = HttpRangeReader(signed_url)
    try:
        seeking_reader = mcap.reader.SeekingReader(as_io_bytes(http_reader))
        summary = seeking_reader.get_summary()

        if summary and summary.chunk_indexes:
            topic_channel_ids = (
                {channel.id for channel in summary.channels.values() if channel.topic == topic_name}
                if topic_name is not None
                else None
            )
            # Prefetch each in-window chunk's byte span separately. The MCAP spec does not guarantee
            # chunk-index entries are time-sorted or file-contiguous, so out-of-window chunks can sit
            # between in-window ones in the file; separate prefetches leave their bytes unfetched.
            # A chunk is in the window when its message log times overlap [start_time, end_time).
            for chunk_index in summary.chunk_indexes:
                if start_time is not None and chunk_index.message_end_time < start_time:
                    continue
                if end_time is not None and chunk_index.message_start_time >= end_time:
                    continue
                if topic_channel_ids is not None and topic_channel_ids.isdisjoint(chunk_index.message_index_offsets):
                    continue

                chunk_start = chunk_index.chunk_start_offset
                chunk_end = chunk_start + chunk_index.chunk_length - 1
                http_reader.prefetch_range(chunk_start, chunk_end)

        http_reader.seek(0)
        return http_reader
    except BaseException:
        http_reader.close()
        raise
