# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Codec seam for the GOP-aware stream decoder.

Isolates the per-codec bitstream knowledge (keyframe detection) and the PyAV
decoder name behind one small value type, so :py:func:`.decoder.decode_stream`
stays codec-agnostic: it depends on a :py:class:`VideoCodec`, never on a
specific codec's bitstream format. H.264, H.265, VP9, and AV1 are registered;
a new codec adds a :py:class:`VideoCodec` here plus one :py:data:`_REGISTRY`
entry, with no change to the decoder.
"""

from __future__ import annotations

import collections.abc
import dataclasses

from .av1 import is_keyframe as _av1_is_keyframe
from .h264 import is_keyframe as _h264_is_keyframe
from .h265 import is_keyframe as _h265_is_keyframe
from .vp9 import is_keyframe as _vp9_is_keyframe


@dataclasses.dataclass(frozen=True)
class VideoCodec:
    """The per-codec hooks the generic stream decoder depends on.

    A codec is data plus one function: the PyAV decoder name and a predicate
    that recognizes an independently decodable keyframe from an encoded frame's
    bytes. Everything else about decoding (GOP skipping, log-time remapping,
    error recovery) is codec-agnostic and lives in the decoder.
    """

    name: str
    """Canonical codec name (matches the per-message ``format`` field, lowercase)."""

    formats: frozenset[str]
    """Per-message ``format`` tokens that resolve to this codec (compared lowercase)."""

    pyav_codec_name: str
    """Decoder name passed to PyAV's ``CodecContext.create``."""

    is_keyframe: collections.abc.Callable[[bytes], bool]
    """Whether an encoded frame is an independently decodable keyframe (clean entry point)."""

    decoder_thread_count: int | None = None
    """Fixed ``thread_count`` for the decoder context, or ``None`` for FFmpeg's default."""


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
    # dav1d is the software AV1 decoder bundled with PyAV's FFmpeg build;
    # FFmpeg's native "av1" decoder historically required hardware support.
    pyav_codec_name="libdav1d",
    is_keyframe=_av1_is_keyframe,
    # dav1d's worker-thread teardown deadlocks (process hangs at 0% CPU) when
    # threaded decoder contexts are repeatedly created and destroyed in one
    # process (observed with PyAV 18.0.0); a single-threaded context sidesteps
    # the race, and decode sessions here are short GOP walks where decoder
    # parallelism buys little.
    decoder_thread_count=1,
)


_REGISTRY: dict[str, VideoCodec] = {fmt: codec for codec in (H264, H265, VP9, AV1) for fmt in codec.formats}


def resolve_codec(format: str) -> VideoCodec | None:
    """Return the codec registered for a per-message ``format`` token.

    Args:
        format: The per-message ``format`` field of a compressed-video message
            (e.g. ``"h264"``); matched case-insensitively.

    Returns:
        The matching :py:class:`VideoCodec`, or ``None`` when no registered
        codec claims the token (the stream carries a codec with no decode path).
    """
    return _REGISTRY.get(format.lower())


def supported_formats() -> frozenset[str]:
    """The per-message ``format`` tokens that have a decode path, lowercase."""
    return frozenset(_REGISTRY)
