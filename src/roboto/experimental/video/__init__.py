# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Video APIs in active refinement; see :py:mod:`roboto.experimental` for the stability contract.

Decodes compressed-video topic data (one Annex B-framed H.264 frame per MCAP
message, as written by Roboto ingestion for ``foxglove.CompressedVideo`` and
compatible schemas) into still frames on demand. Decoding requires the
``roboto[video]`` extra; the bitstream-inspection helpers in
:py:mod:`roboto.experimental.video.h264` are dependency-free.
"""

from .decoder import (
    DecodedVideoFrame,
    decode_h264_stream,
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
    "DEFAULT_KEYFRAME_LOOKBACK_NS",
    "DecodedVideoFrame",
    "MessageRangeLoader",
    "NalUnit",
    "NalUnitType",
    "decode_frames_in_range",
    "decode_h264_stream",
    "find_nal_units",
    "is_keyframe",
]
