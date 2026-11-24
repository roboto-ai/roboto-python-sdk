# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

_FRAME_MARKER = 0b10
_SYNC_CODE = bytes([0x49, 0x83, 0x42])

# At most 9 header bits come before the 24-bit sync code, so 5 bytes hold a keyframe header's 33 bits.
_MIN_HEADER_BYTES = 5


def _read_bit(data: bytes, position: int) -> int:
    """Return bit ``position`` of ``data``, counting from the most significant bit of byte 0."""
    return (data[position // 8] >> (7 - position % 8)) & 0x01


def is_keyframe(data: bytes) -> bool:
    """Return whether a VP9 frame is a keyframe, a point decoding can start from.

    A compressed-video message holds one VP9 frame with no framing around it. When it holds a superframe, several
    frames followed by an index of their sizes, the first frame still starts at byte 0, and it is the frame read.
    Only the leading bits of its uncompressed header (section 6.2 of the VP9 Bitstream Specification) are read: the
    frame is a keyframe when its frame marker is ``0b10``, ``show_existing_frame`` is 0, ``frame_type`` is
    ``KEY_FRAME``, and the frame sync code follows. Data shorter than 5 bytes is not a keyframe.

    Args:
        data: Bytes of one VP9 frame or superframe.
    """
    if len(data) < _MIN_HEADER_BYTES:
        return False

    position = 0

    def read(count: int) -> int:
        nonlocal position
        value = 0
        for _ in range(count):
            value = (value << 1) | _read_bit(data, position)
            position += 1
        return value

    if read(2) != _FRAME_MARKER:
        return False
    profile = read(1) | (read(1) << 1)  # profile_low_bit, then profile_high_bit
    if profile == 3:
        read(1)  # reserved_zero
    if read(1) == 1:  # show_existing_frame: shows a decoded frame again
        return False
    if read(1) != 0:  # frame_type: 0 = KEY_FRAME
        return False
    read(2)  # show_frame, error_resilient_mode
    # frame_sync_code rejects data whose leading bits match a keyframe header by chance.
    return read(24) == int.from_bytes(_SYNC_CODE, "big")
