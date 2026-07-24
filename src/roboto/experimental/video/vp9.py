# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Minimal VP9 bitstream inspection.

VP9 has no Annex B framing: a message payload is one raw frame (possibly a
superframe, whose index trails the payload — so byte 0 always starts the
first frame). This module parses only the fixed-position leading bits of the
uncompressed frame header (VP9 Bitstream Specification section 6.2) needed
for keyframe detection; the decoder reads everything else from the stream.
"""

from __future__ import annotations

_FRAME_MARKER = 0b10
_SYNC_CODE = bytes([0x49, 0x83, 0x42])

# The header bits read here span at most 9 bits, followed by the 24-bit sync
# code — under 5 bytes. Real frames are orders of magnitude larger; anything
# shorter cannot be a decodable frame.
_MIN_HEADER_BYTES = 5


def _read_bit(data: bytes, position: int) -> int:
    return (data[position // 8] >> (7 - position % 8)) & 0x01


def is_keyframe(data: bytes) -> bool:
    """Whether the VP9 frame is a keyframe (intra-only, clean decoder entry point).

    A keyframe has ``frame_type`` KEY_FRAME in its uncompressed header and is
    confirmed by the frame sync code. ``show_existing_frame`` payloads (which
    re-display an already decoded frame) are never keyframes.

    Args:
        data: One frame's raw VP9 bytes.

    Returns:
        True when the frame is a keyframe.
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
    profile = read(1) | (read(1) << 1)
    if profile == 3:
        read(1)  # reserved_zero
    if read(1) == 1:  # show_existing_frame: re-display, not a new frame
        return False
    if read(1) != 0:  # frame_type: 0 = KEY_FRAME
        return False
    read(2)  # show_frame, error_resilient_mode
    # frame_sync_code confirms this really is a keyframe header and not
    # arbitrary bytes that happened to match the flag bits.
    return read(24) == int.from_bytes(_SYNC_CODE, "big")
