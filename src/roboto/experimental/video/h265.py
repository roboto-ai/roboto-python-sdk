# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import enum

from .annexb import NalUnit, nal_payload_bounds

__all__ = ["NalUnit", "NalUnitType", "find_nal_units", "is_keyframe"]

_NAL_UNIT_TYPE_SHIFT = 1
_NAL_UNIT_TYPE_MASK = 0x3F

# Inclusive range of the IRAP (intra random access point) NAL unit types, BLA_W_LP (16) through RSV_IRAP_VCL23 (23).
_IRAP_TYPE_MIN = 16
_IRAP_TYPE_MAX = 23


class NalUnitType(enum.IntEnum):
    """Type of an H.265 NAL (network abstraction layer) unit, with members for eight of the types.

    Values are those of table 7-1 of ITU-T H.265. A NAL unit header can carry any 6-bit type, so ``NalUnit.type``
    is an ``int``; compare it against these members.
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
    r"""Split H.265 data in Annex B framing into its NAL (network abstraction layer) units.

    In Annex B framing, a start code (``00 00 01`` or ``00 00 00 01``) precedes each unit. Bytes before the first start
    code are ignored.

    Args:
        data: Bytes in Annex B framing, such as one encoded frame.

    Returns:
        The NAL units in the order they appear, each holding a copy of its bytes: its 2-byte header and payload,
        without the start code.

    Examples:
        >>> from roboto.experimental.video.h265 import find_nal_units
        >>> frame = b"\x00\x00\x00\x01\x40\x01\x00\x00\x01\x26\x01\xaf"
        >>> [unit.type for unit in find_nal_units(frame)]
        [32, 19]
    """
    return [
        NalUnit(type=_nal_type(data[start]), data=bytes(data[start:end])) for start, end in nal_payload_bounds(data)
    ]


def is_keyframe(data: bytes) -> bool:
    """Return whether an H.265 frame in Annex B framing is a keyframe, a point decoding can start from.

    The frame is a keyframe when any of its NAL units has a type from 16 to 23: the IRAP (intra random access point)
    types, which mark BLA, IDR and CRA pictures, plus two reserved IRAP types.

    Args:
        data: Bytes of one encoded frame in Annex B framing, as ``find_nal_units`` takes.
    """
    return any(_IRAP_TYPE_MIN <= _nal_type(data[start]) <= _IRAP_TYPE_MAX for start, _ in nal_payload_bounds(data))
