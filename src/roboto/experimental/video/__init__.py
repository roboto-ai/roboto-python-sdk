# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Video APIs in active refinement; see :py:mod:`roboto.experimental` for the stability contract.

Decodes compressed-video topic data (one encoded frame per MCAP message, as
written by Roboto ingestion for ``CompressedVideo`` and compatible
schemas) into still frames on demand. Supported codecs are enumerated by
:py:func:`supported_formats` (H.264, H.265, VP9, and AV1 today). Decoding
requires the ``roboto[video]`` extra; the per-codec bitstream-inspection
helpers (:py:mod:`~roboto.experimental.video.h264`,
:py:mod:`~roboto.experimental.video.h265`,
:py:mod:`~roboto.experimental.video.vp9`,
:py:mod:`~roboto.experimental.video.av1`) are dependency-free.
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
