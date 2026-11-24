# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations


class SparseBuffer:
    """A read-only, seekable file-like object over a file of which only some regions are held in memory.

    :py:class:`~roboto.storage.HttpRangeReader` caches the byte ranges it fetches from a remote file through it, so
    most code never builds one; reading those bytes again needs no new request. Each run of consecutive bytes held is
    a region. Regions that overlap or touch merge into one, and a read returns only bytes that are in a region.

    Args:
        file_size: Size of the whole file, in bytes. Reads stop at it, and ``seek`` with ``whence=2`` counts from it.
    """

    def __init__(self, file_size: int):
        self.__size = file_size
        self.__pos = 0
        # (start offset, bytes) pairs, sorted by start offset; no two overlap or touch. Each holds a bytearray so
        # add_region can extend a region in place without copying the bytes it already holds.
        self.__regions: list[tuple[int, bytearray]] = []

    @property
    def regions(self) -> list[tuple[int, int]]:
        """Regions held, as ``(start, end)`` byte offsets with ``end`` exclusive, sorted by ``start``."""
        return [(start, start + len(data)) for start, data in self.__regions]

    @property
    def size(self) -> int:
        """Size of the whole file, in bytes."""
        return self.__size

    def add_region(self, offset: int, data: bytes) -> None:
        """Store bytes at an offset in the file, merging them with every region they overlap or touch.

        Where the new bytes overlap bytes already held, the new bytes replace them.

        Args:
            offset: Offset in the file of the first byte of ``data``.
            data: Bytes to store. Empty ``data`` stores nothing.
        """
        if not data:
            return

        end = offset + len(data)

        # When the data starts exactly where a region ends and stops short of the next region, extend that region
        # in place, which copies only the new bytes.
        for i, (region_start, region_data) in enumerate(self.__regions):
            if region_start + len(region_data) == offset:
                next_start = self.__regions[i + 1][0] if i + 1 < len(self.__regions) else None
                if next_start is None or end < next_start:
                    region_data += data
                    return
                break
            if region_start > end:
                break

        merged_start = offset
        merged_end = end
        regions_to_remove: list[int] = []

        for i, (region_start, region_data) in enumerate(self.__regions):
            region_end = region_start + len(region_data)
            # The equalities admit a region that touches the new bytes without overlapping them.
            if region_end >= offset and region_start <= end:
                regions_to_remove.append(i)
                merged_start = min(merged_start, region_start)
                merged_end = max(merged_end, region_end)

        if regions_to_remove:
            first_start, first_data = self.__regions[regions_to_remove[0]]
            if first_start == merged_start:
                # The first merged region starts the merged span, so grow it in place and copy the later regions
                # into it, rather than copying it, often the largest, into a new buffer.
                merged_data = first_data
                merged_data.extend(bytes(merged_end - merged_start - len(first_data)))
                for i in regions_to_remove[1:]:
                    region_start, region_data = self.__regions[i]
                    off = region_start - merged_start
                    merged_data[off : off + len(region_data)] = region_data
            else:
                # The new bytes start before every region they merge with, so copy those regions into a new buffer.
                merged_data = bytearray(merged_end - merged_start)
                for i in regions_to_remove:
                    region_start, region_data = self.__regions[i]
                    off = region_start - merged_start
                    merged_data[off : off + len(region_data)] = region_data
            # Copied last, so the new bytes replace the bytes held where they overlap.
            off = offset - merged_start
            merged_data[off : off + len(data)] = data

            # Delete from the highest index down so the indices still to delete stay valid.
            for i in reversed(regions_to_remove):
                del self.__regions[i]

            self.__regions.append((merged_start, merged_data))
        else:
            self.__regions.append((offset, bytearray(data)))

        self.__regions.sort(key=lambda r: r[0])

    def clear(self) -> None:
        """Remove every region."""
        self.__regions.clear()

    def find_region(self, start: int, size: int) -> bytes | None:
        """Return ``size`` bytes starting at offset ``start`` if a region holds all of them.

        Unlike ``read``, does not use or move the read position.

        Args:
            start: Offset in the file of the first byte.
            size: Number of bytes.

        Returns:
            The bytes, or ``None`` if any of them is outside every region.
        """
        for region_start, region_data in self.__regions:
            region_end = region_start + len(region_data)
            if region_start <= start and start + size <= region_end:
                offset = start - region_start
                return bytes(memoryview(region_data)[offset : offset + size])
        return None

    def read(self, size: int = -1) -> bytes:
        """Read up to ``size`` bytes from the read position, and advance the position past them.

        Reading stops at the end of the region that holds the read position, or at the end of the file, so the
        result can be shorter than ``size``. When no region holds the read position, or it is at or past the end of
        the file, this returns ``b""`` and leaves the position unchanged. A caller fetches more bytes when the result
        is shorter than it needs.

        Args:
            size: Maximum number of bytes to read. A negative value reads to the end of the file.
        """
        if self.__pos >= self.__size:
            return b""
        if size < 0:
            size = self.__size - self.__pos

        size = min(size, self.__size - self.__pos)

        for region_start, region_data in self.__regions:
            region_end = region_start + len(region_data)
            if region_start <= self.__pos < region_end:
                available = region_end - self.__pos
                read_size = min(size, available)
                region_offset = self.__pos - region_start
                result = bytes(memoryview(region_data)[region_offset : region_offset + read_size])
                self.__pos += len(result)
                return result

        return b""

    def readable(self) -> bool:
        """Return ``True``: the buffer can be read."""
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        """Move the read position and return it.

        The position is not checked against the bounds of the file. A ``whence`` other than ``0``, ``1`` or ``2``
        leaves it unchanged.

        Args:
            offset: Number of bytes to move from the point ``whence`` names.
            whence: Point to count from: ``0`` (the default) for the start of the file, ``1`` for the read position,
                ``2`` for the end of the file.

        Returns:
            The new read position, as an offset from the start of the file.
        """
        if whence == 0:
            self.__pos = offset
        elif whence == 1:
            self.__pos += offset
        elif whence == 2:
            self.__pos = self.__size + offset
        return self.__pos

    def seekable(self) -> bool:
        """Return ``True``: the buffer supports ``seek``."""
        return True

    def tell(self) -> int:
        """Return the current read position."""
        return self.__pos

    def writable(self) -> bool:
        """Return ``False``: the buffer is read-only."""
        return False
