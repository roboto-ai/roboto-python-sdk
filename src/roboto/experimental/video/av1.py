# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Minimal AV1 low-overhead bitstream inspection.

AV1 has no Annex B framing: a message payload is one temporal unit — a
sequence of OBUs (open bitstream units), each with a 1-2 byte header and a
LEB128-coded size (AV1 Bitstream Specification section 5.2). This module
walks the OBUs and parses only the fixed leading bits of the frame header
needed for keyframe detection; the decoder reads everything else from the
in-band sequence header.
"""

from __future__ import annotations

import dataclasses
import enum


class ObuType(enum.IntEnum):
    """AV1 OBU types (AV1 Bitstream Specification section 5.3.2) relevant here.

    OBU headers can carry any 4-bit type value, so :py:attr:`Obu.type` is a
    plain ``int``; compare against these members for the types that matter.
    """

    SEQUENCE_HEADER = 1
    TEMPORAL_DELIMITER = 2
    FRAME_HEADER = 3
    FRAME = 6


@dataclasses.dataclass(frozen=True)
class Obu:
    """One OBU split out of a low-overhead AV1 temporal unit."""

    type: int
    """``obu_type`` from the OBU header."""

    payload: bytes
    """The OBU's payload bytes (header and size field excluded)."""


def _read_leb128(data: bytes, offset: int) -> tuple[int, int] | None:
    """Read a LEB128 value at ``offset``; returns ``(value, next_offset)`` or ``None`` when truncated."""
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
    """Split a low-overhead AV1 temporal unit into its OBUs.

    Walking stops (returning the OBUs found so far) at the first malformed
    header, truncated size field, or size that overruns the payload. An OBU
    without a size field extends to the end of the data, as the spec allows
    for the last OBU of a temporal unit.

    Args:
        data: One temporal unit's bytes in the low-overhead bitstream format.

    Returns:
        The unit's OBUs in bitstream order, payloads copied.
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
    """Whether the AV1 temporal unit contains a KEY_FRAME (clean decoder entry point).

    The first frame (or frame-header) OBU's leading bits are checked:
    ``show_existing_frame`` must be 0 and ``frame_type`` KEY_FRAME. When the
    unit's own sequence header declares ``reduced_still_picture_header``, the
    frame is a keyframe by definition (that mode only encodes intra frames).

    Args:
        data: One temporal unit's bytes in the low-overhead bitstream format.

    Returns:
        True when the unit contains a keyframe.
    """
    reduced_still_picture = False
    for obu in find_obus(data):
        if obu.type == ObuType.SEQUENCE_HEADER and len(obu.payload) >= 1:
            # seq_profile (3 bits), still_picture (1), reduced_still_picture_header (1)
            reduced_still_picture = bool(obu.payload[0] & 0x08)
        elif obu.type in (ObuType.FRAME, ObuType.FRAME_HEADER):
            if len(obu.payload) < 1:
                return False
            if reduced_still_picture:
                return True
            first_byte = obu.payload[0]
            if first_byte & 0x80:  # show_existing_frame: re-display, not a new frame
                return False
            frame_type = (first_byte >> 5) & 0x03
            return frame_type == 0  # KEY_FRAME
    return False
