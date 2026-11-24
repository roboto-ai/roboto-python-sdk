# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class NalUnit:
    """A network abstraction layer (NAL) unit: one unit of an H.264 or H.265 bitstream, led by a header naming its type.

    ``find_nal_units`` in ``roboto.experimental.video.h264`` and ``roboto.experimental.video.h265`` returns these,
    split out of data in Annex B framing, where a start code (``00 00 01`` or ``00 00 00 01``) precedes each unit.
    """

    type: int
    """Value of the ``nal_unit_type`` field in the unit's header.

    For H.264 it is the low 5 bits of the first header byte; for H.265, the 6 bits above that byte's lowest bit.
    """

    data: bytes
    """Bytes of the unit, header included and start code excluded."""


def nal_payload_bounds(data: bytes) -> list[tuple[int, int]]:
    """Return the byte range of each NAL unit in data in Annex B framing.

    To split data into NAL units with their types, use ``find_nal_units`` in ``roboto.experimental.video.h264`` or
    ``roboto.experimental.video.h265`` instead. The scan reads only start codes, so it serves both codecs.

    Annex B of ITU-T H.264 and of ITU-T H.265 defines this framing, in which a start code, ``00 00 01`` or
    ``00 00 00 01``, precedes each unit. A unit runs from the byte after its start code to the first byte
    of the next start code, or to the end of ``data``. Bytes before the first start code are ignored, and a start code
    followed directly by another, or by the end of ``data``, yields no range.

    Args:
        data: Bytes in Annex B framing, such as one encoded frame.

    Returns:
        ``(start, end)`` ranges in the order the units appear, ``start`` inclusive and ``end`` exclusive, so
        ``data[start:end]`` is one unit with its header and without its start code.
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
