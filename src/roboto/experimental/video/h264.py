# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Minimal H.264 Annex B bitstream inspection.

Implements only the byte-level parsing needed to drive a GOP-aware decoder:
splitting a frame's data into NAL units and detecting keyframes (IDR slices).
It neither decodes video nor parses variable-length (Exp-Golomb) fields —
the decoder reads everything else (dimensions, reference frame count, ...)
from the in-band parameter sets.

The start-code scan shared with H.265 lives in :py:mod:`.annexb`; this module
adds the H.264 specifics: a 1-byte NAL header carrying a 5-bit type.
"""

from __future__ import annotations

import enum

from .annexb import NalUnit, nal_payload_bounds

__all__ = ["NalUnit", "NalUnitType", "find_nal_units", "is_keyframe"]

_NAL_UNIT_TYPE_MASK = 0x1F


class NalUnitType(enum.IntEnum):
    """H.264 NAL unit types (ITU-T H.264 table 7-1) relevant to this module.

    NAL headers can carry any 5-bit type value, so :py:attr:`NalUnit.type` is a
    plain ``int``; compare against these members for the types that matter here.
    """

    NON_IDR_SLICE = 1
    IDR_SLICE = 5
    SEI = 6
    SEQUENCE_PARAMETER_SET = 7
    PICTURE_PARAMETER_SET = 8


def find_nal_units(data: bytes) -> list[NalUnit]:
    """Split Annex B-framed H.264 data into its NAL units.

    Args:
        data: One frame's Annex B-framed bytes, using 3-byte or 4-byte start codes.

    Returns:
        The frame's NAL units in bitstream order. Each unit's ``data`` is a copy
        of the unit's bytes (header included, start code excluded).

    Examples:
        >>> from roboto.experimental.video import NalUnitType, find_nal_units
        >>> units = find_nal_units(annex_b_frame_bytes)  # doctest: +SKIP
        >>> [unit.type for unit in units]  # doctest: +SKIP
        [7, 8, 5]
    """
    return [
        NalUnit(type=data[start] & _NAL_UNIT_TYPE_MASK, data=bytes(data[start:end]))
        for start, end in nal_payload_bounds(data)
    ]


def is_keyframe(data: bytes) -> bool:
    """Whether the Annex B-framed H.264 frame contains an IDR slice.

    An IDR slice is a clean decoder entry point: decoding may start at this
    frame without any earlier GOP state. Frames without one are delta frames,
    decodable only after the preceding keyframe has been fed to the decoder.

    Args:
        data: One frame's Annex B-framed bytes.

    Returns:
        True when the frame contains an IDR slice.
    """
    return any(data[start] & _NAL_UNIT_TYPE_MASK == NalUnitType.IDR_SLICE for start, _ in nal_payload_bounds(data))
