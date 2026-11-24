# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import dataclasses
import enum


class ObuType(enum.IntEnum):
    """Type of an AV1 OBU (open bitstream unit), with members for four of the types.

    An OBU header can carry any 4-bit type, so ``Obu.type`` is an ``int``; compare it against these members.
    """

    SEQUENCE_HEADER = 1
    TEMPORAL_DELIMITER = 2
    FRAME_HEADER = 3
    FRAME = 6


@dataclasses.dataclass(frozen=True)
class Obu:
    """One OBU (open bitstream unit) of an AV1 temporal unit, as ``find_obus`` splits it out."""

    type: int
    """Type of the OBU, the ``obu_type`` field of its header."""

    payload: bytes
    """Payload of the OBU, without its header or size field."""


def _read_leb128(data: bytes, offset: int) -> tuple[int, int] | None:
    """Read the LEB128-coded value at ``offset``, as ``(value, next_offset)``.

    Return ``None`` when the data ends before the value does, or when the value runs past 8 bytes.
    """
    value = 0
    for i in range(8):
        if offset + i >= len(data):
            return None
        byte = data[offset + i]
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return value, offset + i + 1
    return None


def find_obus(data: bytes) -> list[Obu]:
    """Split an AV1 temporal unit into its OBUs (open bitstream units).

    A compressed-video message holds one AV1 temporal unit in the low-overhead bitstream format: OBUs back to back,
    each a 1- or 2-byte header, a LEB128-coded size and a payload, with no start codes between them.

    Splitting stops at the first OBU whose forbidden bit is set, whose header or size field is cut off, or whose size
    runs past the end of the data, and returns the OBUs before it. An OBU without a size field is taken to run to the
    end of the data.

    Args:
        data: Bytes of one temporal unit in the low-overhead bitstream format.

    Returns:
        The OBUs in bitstream order, each holding a copy of its payload.
    """
    obus: list[Obu] = []
    offset = 0
    while offset < len(data):
        header = data[offset]
        if header & 0x80:  # obu_forbidden_bit must be 0
            break
        obu_type = (header >> 3) & 0x0F
        has_extension = bool(header & 0x04)
        has_size = bool(header & 0x02)
        offset += 1 + (1 if has_extension else 0)
        if offset > len(data):
            break
        if not has_size:
            obus.append(Obu(type=obu_type, payload=bytes(data[offset:])))
            break
        size_read = _read_leb128(data, offset)
        if size_read is None:
            break
        size, offset = size_read
        if offset + size > len(data):
            break
        obus.append(Obu(type=obu_type, payload=bytes(data[offset : offset + size])))
        offset += size
    return obus


def is_keyframe(data: bytes) -> bool:
    """Return whether the first frame in an AV1 temporal unit is a keyframe, a point decoding can start from.

    Only the first frame or frame-header OBU is read, and only the leading bits of its frame header: it is a keyframe
    when ``show_existing_frame`` is 0 and ``frame_type`` is ``KEY_FRAME``. When a sequence header earlier in the same
    unit sets ``reduced_still_picture_header``, every frame is a ``KEY_FRAME``, so those bits are not read. A unit with
    no frame OBU, or whose first frame OBU is empty, is not a keyframe.

    Args:
        data: Bytes of one temporal unit in the low-overhead bitstream format.
    """
    reduced_still_picture = False
    for obu in find_obus(data):
        if obu.type == ObuType.SEQUENCE_HEADER and len(obu.payload) >= 1:
            # Leading bits: seq_profile (3), still_picture (1), reduced_still_picture_header (1)
            reduced_still_picture = bool(obu.payload[0] & 0x08)
        elif obu.type in (ObuType.FRAME, ObuType.FRAME_HEADER):
            if len(obu.payload) < 1:
                return False
            if reduced_still_picture:
                return True
            first_byte = obu.payload[0]
            if first_byte & 0x80:  # show_existing_frame: shows a decoded frame again
                return False
            frame_type = (first_byte >> 5) & 0x03
            return frame_type == 0  # KEY_FRAME
    return False
