# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import enum

from .annexb import NalUnit, nal_payload_bounds

__all__ = ["NalUnit", "NalUnitType", "find_nal_units", "is_keyframe"]

_NAL_UNIT_TYPE_MASK = 0x1F


class NalUnitType(enum.IntEnum):
    """Type of an H.264 NAL (network abstraction layer) unit, with members for five of the types.

    A NAL unit header can carry any 5-bit type, so ``NalUnit.type`` is an ``int``; compare it against these members.
    The values are those of table 7-1 of ITU-T H.264.
    """

    NON_IDR_SLICE = 1
    IDR_SLICE = 5
    SEI = 6
    SEQUENCE_PARAMETER_SET = 7
    PICTURE_PARAMETER_SET = 8


def find_nal_units(data: bytes) -> list[NalUnit]:
    """Split H.264 data in Annex B framing into its NAL (network abstraction layer) units.

    In Annex B framing, a start code (``00 00 01`` or ``00 00 00 01``) precedes each unit. A unit's type is the low 5
    bits of its first byte.

    Args:
        data: Bytes in Annex B framing, such as one encoded frame.

    Returns:
        The units in the order they appear, each holding a copy of its bytes, header included and start code excluded.

    Examples:
        A sequence parameter set, a picture parameter set and an IDR slice, each one header byte long:

        >>> from roboto.experimental.video import find_nal_units
        >>> data = bytes.fromhex("00 00 00 01 67 00 00 01 68 00 00 01 65")
        >>> [unit.type for unit in find_nal_units(data)]
        [7, 8, 5]
    """
    return [
        NalUnit(type=data[start] & _NAL_UNIT_TYPE_MASK, data=bytes(data[start:end]))
        for start, end in nal_payload_bounds(data)
    ]


def is_keyframe(data: bytes) -> bool:
    """Return whether an H.264 frame contains an IDR slice, which makes it a keyframe, a point decoding can start from.

    An IDR (instantaneous decoder refresh) slice is a NAL unit of type ``NalUnitType.IDR_SLICE``. A frame with one
    decodes without any earlier frame; a frame without one decodes only after the frames back to the keyframe before it.

    Args:
        data: Bytes of one encoded frame in Annex B framing.
    """
    return any(data[start] & _NAL_UNIT_TYPE_MASK == NalUnitType.IDR_SLICE for start, _ in nal_payload_bounds(data))
