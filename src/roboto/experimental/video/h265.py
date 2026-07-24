# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Minimal H.265 (HEVC) Annex B bitstream inspection.

Implements only the byte-level parsing needed to drive a GOP-aware decoder:
splitting a frame's data into NAL units and detecting keyframes (IRAP
pictures). It neither decodes video nor parses variable-length fields — the
decoder reads everything else from the in-band parameter sets.

The start-code scan shared with H.264 lives in :py:mod:`.annexb`; this module
adds the H.265 specifics: a 2-byte NAL header whose first byte carries a
6-bit type in bits 6..1 (ITU-T H.265 section 7.3.1.2).
"""

from __future__ import annotations

import enum

from .annexb import NalUnit, nal_payload_bounds

__all__ = ["NalUnit", "NalUnitType", "find_nal_units", "is_keyframe"]

_NAL_UNIT_TYPE_SHIFT = 1
_NAL_UNIT_TYPE_MASK = 0x3F

# IRAP (intra random access point) NAL unit types span BLA_W_LP (16) through
# RSV_IRAP_VCL23 (23) — ITU-T H.265 table 7-1. Any VCL NAL in this range makes
# the frame a clean decoder entry point.
_IRAP_TYPE_MIN = 16
_IRAP_TYPE_MAX = 23


class NalUnitType(enum.IntEnum):
    """H.265 NAL unit types (ITU-T H.265 table 7-1) relevant to this module.

    NAL headers can carry any 6-bit type value, so :py:attr:`NalUnit.type` is a
    plain ``int``; compare against these members for the types that matter here.
    """

    TRAIL_R = 1
    BLA_W_LP = 16
    IDR_W_RADL = 19
    IDR_N_LP = 20
    CRA_NUT = 21
    VIDEO_PARAMETER_SET = 32
    SEQUENCE_PARAMETER_SET = 33
    PICTURE_PARAMETER_SET = 34


def _nal_type(header_byte: int) -> int:
    return (header_byte >> _NAL_UNIT_TYPE_SHIFT) & _NAL_UNIT_TYPE_MASK


def find_nal_units(data: bytes) -> list[NalUnit]:
    """Split Annex B-framed H.265 data into its NAL units.

    Args:
        data: One frame's Annex B-framed bytes, using 3-byte or 4-byte start codes.

    Returns:
        The frame's NAL units in bitstream order. Each unit's ``data`` is a copy
        of the unit's bytes (header included, start code excluded).

    Examples:
        >>> from roboto.experimental.video.h265 import NalUnitType, find_nal_units
        >>> units = find_nal_units(annex_b_frame_bytes)  # doctest: +SKIP
        >>> [unit.type for unit in units]  # doctest: +SKIP
        [32, 33, 34, 19]
    """
    return [
        NalUnit(type=_nal_type(data[start]), data=bytes(data[start:end])) for start, end in nal_payload_bounds(data)
    ]


def is_keyframe(data: bytes) -> bool:
    """Whether the Annex B-framed H.265 frame contains an IRAP picture.

    An IRAP picture (IDR, CRA, or BLA) is a clean decoder entry point: decoding
    may start at this frame without any earlier GOP state. Frames without one
    are delta frames, decodable only after the preceding keyframe has been fed
    to the decoder.

    Args:
        data: One frame's Annex B-framed bytes.

    Returns:
        True when the frame contains an IRAP picture.
    """
    return any(_IRAP_TYPE_MIN <= _nal_type(data[start]) <= _IRAP_TYPE_MAX for start, _ in nal_payload_bounds(data))
