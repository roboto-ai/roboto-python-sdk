# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses

from .av1 import is_keyframe as _av1_is_keyframe
from .h264 import is_keyframe as _h264_is_keyframe
from .h265 import is_keyframe as _h265_is_keyframe
from .vp9 import is_keyframe as _vp9_is_keyframe


@dataclasses.dataclass(frozen=True)
class VideoCodec:
    """Codec of a compressed-video stream: the PyAV decoder for it, and how to find its keyframes from their bytes.

    ``decode_stream`` and ``decode_frames_in_range`` read nothing else about a codec, so a ``VideoCodec`` you build for
    another codec PyAV decodes works with them too. ``resolve_codec`` returns only ``H264``, ``H265``, ``VP9`` and
    ``AV1``.
    """

    name: str
    """Name of the codec in lowercase, such as ``"h265"``; warnings about frames that fail to decode name it."""

    formats: frozenset[str]
    """Values of a message's ``format`` field that ``resolve_codec`` resolves to this codec, in lowercase."""

    pyav_codec_name: str
    """Name of the PyAV decoder to decode with, as ``av.CodecContext.create`` takes it."""

    is_keyframe: collections.abc.Callable[[bytes], bool]
    """Function that takes an encoded frame's bytes, and returns whether it is a keyframe, which decodes on its own."""

    decoder_thread_count: int | None = None
    """Number of threads the decoder uses, or ``None`` to leave FFmpeg's default."""


H264 = VideoCodec(
    name="h264",
    formats=frozenset({"h264"}),
    pyav_codec_name="h264",
    is_keyframe=_h264_is_keyframe,
)

H265 = VideoCodec(
    name="h265",
    formats=frozenset({"h265", "hevc"}),
    pyav_codec_name="hevc",
    is_keyframe=_h265_is_keyframe,
)

VP9 = VideoCodec(
    name="vp9",
    formats=frozenset({"vp9"}),
    pyav_codec_name="vp9",
    is_keyframe=_vp9_is_keyframe,
)

AV1 = VideoCodec(
    name="av1",
    formats=frozenset({"av1"}),
    # libdav1d is the software AV1 decoder in PyAV's FFmpeg build; FFmpeg's own "av1" decoder needs hardware support.
    pyav_codec_name="libdav1d",
    is_keyframe=_av1_is_keyframe,
    # With PyAV 18.0.0, a process that creates and closes many multithreaded libdav1d decoders deadlocks while one
    # stops its threads, and hangs at 0% CPU. One thread avoids the deadlock and costs little, since each decoder
    # decodes only a short run of frames that starts at a keyframe.
    decoder_thread_count=1,
)


_REGISTRY: dict[str, VideoCodec] = {fmt: codec for codec in (H264, H265, VP9, AV1) for fmt in codec.formats}


def resolve_codec(format: str) -> VideoCodec | None:
    """Return the codec that decodes a compressed-video message's ``format`` value.

    Args:
        format: Value of the message's ``format`` field, such as ``"h264"``, matched case-insensitively.

    Returns:
        One of ``H264``, ``H265``, ``VP9`` and ``AV1``, or ``None`` when none of them decodes the format.
    """
    return _REGISTRY.get(format.lower())


def supported_formats() -> frozenset[str]:
    """Return every ``format`` value that ``resolve_codec`` resolves to a codec, in lowercase."""
    return frozenset(_REGISTRY)
