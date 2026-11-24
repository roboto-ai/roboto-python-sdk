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
    """Open an MCAP file at a URL for reading, prefetching only the chunks in a log-time window and on one topic.

    :py:meth:`~roboto.domain.topics.Topic.get_data` opens MCAP files through it, so most code never calls it.

    Reads the file's summary section, then prefetches in parallel each chunk whose log-time range, as its chunk index
    records it, overlaps ``[start_time, end_time)`` and, given a ``topic_name``, whose chunk index lists a message
    index for a channel on that topic. Later reads of those chunks make no request. A file with no summary section or
    no chunk index opens with no chunk prefetched.

    Given a ``topic_name``, a chunk whose index lists no message indexes is not prefetched, since the index does not
    show which topics the chunk holds; its bytes are downloaded when it is read.

    Chunks are selected by log time only. To select messages by another timestamp, pass no bounds, which prefetches
    every chunk, and filter the messages after decoding them.

    Args:
        signed_url: URL of the MCAP file, such as a signed download URL. The server must answer HTTP ``Range``
            requests.
        start_time: Inclusive start of the window, in nanoseconds of message log time. ``None`` leaves the window
            open at the start.
        end_time: Exclusive end of the window, in the same form. ``None`` leaves the window open at the end.
        topic_name: Topic whose chunks to prefetch. ``None`` prefetches the chunks of every topic.

    Returns:
        :py:class:`~roboto.storage.HttpRangeReader` over the file, positioned at its first byte, with the selected
        chunks already downloaded. You own the returned reader: close it with
        :py:meth:`~roboto.storage.HttpRangeReader.close`, or use it as a context manager.

    Raises:
        OSError: A response has an HTTP error status or holds bytes other than the ones requested, or the server
            sends no ``Content-Range`` header with the file's size.
        urllib3.exceptions.MaxRetryError: A request still fails with a network error after 3 retries.
        mcap.exceptions.McapError: The file does not end with an MCAP footer, or its summary section cannot be read.
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
            # Prefetch each selected chunk's byte range separately, not one range from the first to the last:
            # chunks outside the window or on other topics can sit between selected ones in the file, and one
            # range would download them too.
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
        # A caller whose call raised has no reader to close, so close its connections on any exception, then
        # re-raise it.
        http_reader.close()
        raise
