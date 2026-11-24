# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Decoding of compressed-video topic data into still frames, where each message holds one encoded frame.

A frame other than a keyframe decodes only after the frames back to the keyframe before it. Use
``decode_frames_in_range`` to decode a time range of a topic, which also loads and decodes those earlier frames, up to
``keyframe_lookback_ns`` (10 seconds by default) before the range, without yielding them. Use ``decode_stream`` to
decode frames you already hold in log-time order; it skips the frames before the first keyframe. Pass either one the
``VideoCodec`` that ``resolve_codec`` returns for a message's ``format`` field, which is ``None`` when no codec decodes
that format; ``supported_formats`` returns every format it accepts. The modules ``roboto.experimental.video.h264``,
``h265``, ``vp9`` and ``av1`` tell whether an encoded frame is a keyframe from its bytes alone, and need no extra.
Decoding requires the ``roboto[video]`` extra: ``pip install roboto[video]``.
"""

from .codec import (
    AV1,
    H264,
    H265,
    VP9,
    VideoCodec,
    resolve_codec,
    supported_formats,
)
from .decoder import (
    DecodedVideoFrame,
    decode_h264_stream,
    decode_stream,
)
from .frames import (
    DEFAULT_KEYFRAME_LOOKBACK_NS,
    MessageRangeLoader,
    decode_frames_in_range,
)
from .h264 import (
    NalUnit,
    NalUnitType,
    find_nal_units,
    is_keyframe,
)

__all__ = [
    "AV1",
    "DEFAULT_KEYFRAME_LOOKBACK_NS",
    "H264",
    "H265",
    "VP9",
    "DecodedVideoFrame",
    "MessageRangeLoader",
    "NalUnit",
    "NalUnitType",
    "VideoCodec",
    "decode_frames_in_range",
    "decode_h264_stream",
    "decode_stream",
    "find_nal_units",
    "is_keyframe",
    "resolve_codec",
    "supported_formats",
]
