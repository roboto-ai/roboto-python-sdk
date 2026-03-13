# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Seekable read-only buffer backed by sparse in-memory byte regions.

Provides a file-like interface (IO[bytes]) over non-contiguous byte data,
allowing efficient representation of partially-fetched remote files.
Only the regions that have been explicitly loaded are stored in memory.
"""

from __future__ import annotations


class SparseBuffer:
    """A seekable, read-only file-like object backed by sparse in-memory byte regions.

    Stores fetched byte regions and provides a standard IO[bytes] interface for
    reading from them. Regions are automatically merged when they overlap or are
    adjacent, keeping the internal representation compact.

    This is intended to be used as:
    1. The cache backend for HttpRangeReader (sparse storage with smart fetching)
    2. The stream for mcap.reader.SeekingReader after bulk-fetching byte ranges

    Example:
        >>> buf = SparseBuffer(file_size=1000)
        >>> buf.add_region(0, b"MCAP_MAGIC")  # header
        >>> buf.add_region(900, b"footer_data")  # footer
        >>> buf.seek(0)
        0
        >>> buf.read(10)
        b'MCAP_MAGIC'
    """

    def __init__(self, file_size: int):
        """Initialize the buffer.

        Args:
            file_size: Total size of the virtual file in bytes.
                Used for seek(offset, SEEK_END) calculations.
        """
        self.__size = file_size
        self.__pos = 0
        # Sparse cache: list of (start_offset, data) tuples, kept sorted by start_offset
        self.__regions: list[tuple[int, bytes]] = []

    @property
    def regions(self) -> list[tuple[int, int]]:
        """List of (start, end) byte ranges currently cached.

        End is exclusive. Useful for fetch planning and debugging.
        """
        return [(start, start + len(data)) for start, data in self.__regions]

    @property
    def size(self) -> int:
        """Total size of the virtual file."""
        return self.__size

    def add_region(self, offset: int, data: bytes) -> None:
        """Store a byte region at the given file offset.

        Merges with any overlapping or adjacent existing regions.

        Args:
            offset: Byte offset within the virtual file.
            data: Raw bytes to store at that offset.
        """
        if not data:
            return

        end = offset + len(data)

        # Find regions that overlap or are adjacent
        merged_start = offset
        merged_end = end
        regions_to_remove: list[int] = []

        for i, (region_start, region_data) in enumerate(self.__regions):
            region_end = region_start + len(region_data)
            # Check if regions overlap or are adjacent
            if region_end >= offset and region_start <= end:
                regions_to_remove.append(i)
                merged_start = min(merged_start, region_start)
                merged_end = max(merged_end, region_end)

        if regions_to_remove:
            # Build merged data
            merged_data = bytearray(merged_end - merged_start)
            # First, copy existing regions
            for i in regions_to_remove:
                region_start, region_data = self.__regions[i]
                off = region_start - merged_start
                merged_data[off : off + len(region_data)] = region_data
            # Then overlay new data (takes precedence)
            off = offset - merged_start
            merged_data[off : off + len(data)] = data

            # Remove old regions in reverse order to preserve indices
            for i in reversed(regions_to_remove):
                del self.__regions[i]

            self.__regions.append((merged_start, bytes(merged_data)))
        else:
            self.__regions.append((offset, data))

        # Keep sorted by start offset for efficient lookup
        self.__regions.sort(key=lambda r: r[0])

    def clear(self) -> None:
        """Remove all cached regions."""
        self.__regions.clear()

    def find_region(self, start: int, size: int) -> bytes | None:
        """Check if [start, start+size) is fully contained in a cached region.

        Args:
            start: Start byte offset.
            size: Number of bytes.

        Returns:
            The requested bytes if fully cached, None otherwise.
        """
        for region_start, region_data in self.__regions:
            region_end = region_start + len(region_data)
            if region_start <= start and start + size <= region_end:
                offset = start - region_start
                return region_data[offset : offset + size]
        return None

    def read(self, size: int = -1) -> bytes:
        """Read up to size bytes from the current position.

        If the current position is within a cached region, returns available bytes
        (may be fewer than requested if the region ends before size bytes).
        If the current position is not in any cached region (a gap), returns b"".

        This allows callers to detect partial hits and fetch missing data:
        - len(result) == size: fully satisfied
        - 0 < len(result) < size: partial hit, more data may be needed
        - len(result) == 0: gap at current position, caller should fetch

        Args:
            size: Maximum number of bytes to read. -1 means read to end of file.

        Returns:
            Bytes read from cached regions, or b"" if at a gap or past EOF.
        """
        if self.__pos >= self.__size:
            return b""
        if size < 0:
            size = self.__size - self.__pos

        # Clamp to file size
        size = min(size, self.__size - self.__pos)

        # Find region containing current position
        for region_start, region_data in self.__regions:
            region_end = region_start + len(region_data)
            if region_start <= self.__pos < region_end:
                available = region_end - self.__pos
                read_size = min(size, available)
                region_offset = self.__pos - region_start
                result = region_data[region_offset : region_offset + read_size]
                self.__pos += len(result)
                return result

        # Position is not in any cached region (gap) - return empty bytes
        # Caller can check len(result) == 0 to detect this and fetch data
        return b""

    def readable(self) -> bool:
        """Return True - this buffer supports reading."""
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        """Move the read position.

        Args:
            offset: Byte offset relative to the position indicated by whence.
            whence: 0=SEEK_SET (start), 1=SEEK_CUR (current), 2=SEEK_END (end).

        Returns:
            The new absolute position.
        """
        if whence == 0:
            self.__pos = offset
        elif whence == 1:
            self.__pos += offset
        elif whence == 2:
            self.__pos = self.__size + offset
        return self.__pos

    def seekable(self) -> bool:
        """Return True - this buffer supports seeking."""
        return True

    def tell(self) -> int:
        """Return the current read position."""
        return self.__pos

    def writable(self) -> bool:
        """Return False - this buffer is read-only."""
        return False
