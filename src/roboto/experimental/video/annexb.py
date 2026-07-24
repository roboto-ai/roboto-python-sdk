# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Annex B framing shared by the NAL-based codecs (H.264 and H.265).

Annex B delimits NAL units with start codes; that framing is identical across
H.264 and H.265 — only the NAL header layout after each start code differs
(1-byte header with a 5-bit type vs. 2-byte header with a 6-bit type). This
module holds the codec-independent start-code scan; the per-codec modules
(:py:mod:`.h264`, :py:mod:`.h265`) interpret the headers.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class NalUnit:
    """One NAL unit split out of Annex B-framed data."""

    type: int
    """``nal_unit_type`` from the unit's header (codec-specific layout)."""

    data: bytes
    """The unit's bytes: header included, start code excluded."""


def nal_payload_bounds(data: bytes) -> list[tuple[int, int]]:
    """Locate every NAL unit payload as a ``(start, end)`` byte range.

    Handles both 3-byte (``00 00 01``) and 4-byte (``00 00 00 01``) start codes.
    Zero-length units are skipped.
    """
    length = len(data)
    payload_starts: list[int] = []
    boundary_starts: list[int] = []
    i = 0
    while i + 3 <= length:
        if data[i] != 0x00 or data[i + 1] != 0x00:
            i += 1
            continue
        if data[i + 2] == 0x01:
            boundary_starts.append(i)
            payload_starts.append(i + 3)
            i += 3
            continue
        if i + 4 <= length and data[i + 2] == 0x00 and data[i + 3] == 0x01:
            boundary_starts.append(i)
            payload_starts.append(i + 4)
            i += 4
            continue
        i += 1

    bounds: list[tuple[int, int]] = []
    for j, payload_start in enumerate(payload_starts):
        end = boundary_starts[j + 1] if j + 1 < len(boundary_starts) else length
        if end > payload_start:
            bounds.append((payload_start, end))
    return bounds
