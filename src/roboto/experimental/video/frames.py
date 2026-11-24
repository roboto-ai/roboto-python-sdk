# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import itertools
import typing

from .codec import H264, VideoCodec
from .decoder import (
    DecodedVideoFrame,
    decode_stream,
)

MessageRangeLoader = typing.Callable[[int, int], collections.abc.Iterable[tuple[int, bytes]]]
"""Function that loads a topic's messages for a time range, and returns them as ``(log_time, data)`` pairs.

It receives the start and end of the range as positional arguments, in nanoseconds since the Unix epoch, and returns
the pairs in ascending log-time order, each ``data`` one encoded frame. The end may be inclusive or exclusive:
``decode_frames_in_range`` discards any lookback message at or after the range's first message. The ``load_messages``
argument of ``decode_frames_in_range`` says when it is called.
"""

DEFAULT_KEYFRAME_LOOKBACK_NS: int = 10 * 1_000_000_000
"""Default limit, in nanoseconds (10 seconds), on how far back ``decode_frames_in_range`` searches for a keyframe.

The limit caps how much earlier video one call loads and decodes when a stream's keyframes are far apart.
"""


def decode_frames_in_range(
    load_messages: MessageRangeLoader,
    start_time: int,
    end_time: int,
    keyframe_lookback_ns: int = DEFAULT_KEYFRAME_LOOKBACK_NS,
    codec: VideoCodec = H264,
) -> collections.abc.Generator[DecodedVideoFrame, None, None]:
    """Decode the frames of a compressed-video topic in a time range, where each message holds one encoded frame.

    A frame other than a keyframe decodes only after the frames back to the keyframe before it. When the first message
    in the range is not a keyframe, this loads the messages from up to ``keyframe_lookback_ns`` before that message,
    decodes them from the latest keyframe among them, and yields none of them. When none of them is a keyframe, the
    range's frames before its first keyframe are omitted. Corrupt frames are omitted too, as ``decode_stream``
    describes.

    Args:
        load_messages: Function that loads the topic's messages for a time range. It is called once for the range and,
            when the range's first message is not a keyframe, once more for the lookback before that message.
        start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch.
        end_time: End of the time range, in the same form, passed to ``load_messages`` unchanged. Whether it is
            inclusive depends on ``load_messages``.
        keyframe_lookback_ns: Maximum time before the range's first message to search for a keyframe, in nanoseconds.
        codec: Codec of every message's frame. Defaults to ``H264``. ``resolve_codec`` returns the codec for a
            message's ``format`` field.

    Yields:
        One ``DecodedVideoFrame`` per decodable frame with a log time at or after ``start_time``, in ascending log-time
        order.

    Raises:
        ImportError: The ``roboto[video]`` extra is not installed. It surfaces on the first iteration, when the range
            holds any message.

    Examples:
        >>> from roboto.experimental.video import decode_frames_in_range
        >>> frames = decode_frames_in_range(  # doctest: +SKIP
        ...     load_messages=my_loader, start_time=start_ns, end_time=end_ns
        ... )
        >>> next(frames).to_image()  # doctest: +SKIP
    """
    messages = iter(load_messages(start_time, end_time))
    first = next(messages, None)
    if first is None:
        return

    prefix: list[tuple[int, bytes]] = []
    if not codec.is_keyframe(first[1]):
        prefix = _load_gop_prefix(
            load_messages, before=first[0], keyframe_lookback_ns=keyframe_lookback_ns, codec=codec
        )

    for decoded in decode_stream(itertools.chain(prefix, [first], messages), codec):
        if decoded.log_time >= start_time:
            yield decoded


def _load_gop_prefix(
    load_messages: MessageRangeLoader,
    before: int,
    keyframe_lookback_ns: int,
    codec: VideoCodec,
) -> list[tuple[int, bytes]]:
    """Load the messages from the latest keyframe in the ``keyframe_lookback_ns`` before ``before`` up to ``before``.

    The result excludes ``before`` itself, and is empty when no message in that window is a keyframe.
    """
    lookback_start = max(before - keyframe_lookback_ns, 0)
    if lookback_start >= before:
        return []

    candidates = [(log_time, data) for log_time, data in load_messages(lookback_start, before) if log_time < before]
    for i in range(len(candidates) - 1, -1, -1):
        if codec.is_keyframe(candidates[i][1]):
            return candidates[i:]
    return []
