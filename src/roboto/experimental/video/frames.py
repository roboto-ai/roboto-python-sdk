# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""On-demand extraction of decoded frames from a time range of compressed video.

A time range of video usually starts mid-GOP: its leading delta frames are
only decodable after the keyframe that precedes the range. This module hides
that — callers provide a way to load ``(log_time, data)`` messages for a time
range, ask for a range, and receive one decoded frame per decodable frame in
it. When the range starts mid-GOP, the preceding keyframe is found by walking
backward (bounded by ``keyframe_lookback_ns``) and the prefix is decoded but
not emitted.
"""

from __future__ import annotations

import collections.abc
import itertools
import typing

from .decoder import (
    DecodedVideoFrame,
    decode_h264_stream,
)
from .h264 import is_keyframe

MessageRangeLoader = typing.Callable[[int, int], collections.abc.Iterable[tuple[int, bytes]]]
"""Loads a topic's ``(log_time, data)`` messages for a ``(start_time, end_time)`` range.

Both times are nanoseconds since Unix epoch; messages must come back in
ascending log-time order. Whether ``end_time`` is inclusive follows the
underlying reader — frame emission is bounded by log-time filtering, not by
the loader's boundary semantics.
"""

DEFAULT_KEYFRAME_LOOKBACK_NS: int = 10 * 1_000_000_000
"""How far before a requested range to search for the keyframe that makes the
range's leading delta frames decodable. Bounds the cost of the backward walk
on streams with pathological keyframe intervals."""


def decode_frames_in_range(
    load_messages: MessageRangeLoader,
    start_time: int,
    end_time: int,
    keyframe_lookback_ns: int = DEFAULT_KEYFRAME_LOOKBACK_NS,
) -> collections.abc.Generator[DecodedVideoFrame, None, None]:
    """Decode the H.264 video frames of a time range.

    Frames in the range that are undecodable — e.g. delta frames whose keyframe
    lies further back than ``keyframe_lookback_ns`` — are silently omitted; no
    player could render them either.

    Args:
        load_messages: Loads the topic's ``(log_time, data)`` messages for a
            time range; called once for the requested range and, when the range
            starts mid-GOP, once more for the keyframe lookback before it.
        start_time: Start of the range in nanoseconds since Unix epoch (inclusive).
        end_time: End of the range in nanoseconds since Unix epoch; passed
            through to ``load_messages``.
        keyframe_lookback_ns: Upper bound on how far before ``start_time`` to
            search for the keyframe that anchors the range's leading delta frames.

    Yields:
        One :py:class:`~roboto.experimental.video.DecodedVideoFrame` per
        decodable frame with ``log_time >= start_time``, in ascending log-time
        order.

    Raises:
        ImportError: If PyAV is not installed (``roboto[video]``).

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
    if not is_keyframe(first[1]):
        prefix = _load_gop_prefix(load_messages, before=first[0], keyframe_lookback_ns=keyframe_lookback_ns)

    for decoded in decode_h264_stream(itertools.chain(prefix, [first], messages)):
        if decoded.log_time >= start_time:
            yield decoded


def _load_gop_prefix(
    load_messages: MessageRangeLoader,
    before: int,
    keyframe_lookback_ns: int,
) -> list[tuple[int, bytes]]:
    """Load the frames from the nearest keyframe before ``before`` up to (excluding) ``before``.

    Empty when no keyframe exists within ``keyframe_lookback_ns`` — the caller's
    leading delta frames are then undecodable and get skipped by the decoder.
    """
    lookback_start = max(before - keyframe_lookback_ns, 0)
    if lookback_start >= before:
        return []

    candidates = [(log_time, data) for log_time, data in load_messages(lookback_start, before) if log_time < before]
    for i in range(len(candidates) - 1, -1, -1):
        if is_keyframe(candidates[i][1]):
            return candidates[i:]
    return []
