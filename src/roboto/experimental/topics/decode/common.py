# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import abc
import collections.abc
import dataclasses
import pathlib
import types
import typing

from ....domain.topics import RepresentationStorageFormat
from ....domain.topics.record import FieldPath
from ....storage import CachePolicy
from ..read_plan import (
    ReadPlanObjectRef,
    ReadPlanPartition,
    TimeWindow,
)

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

ObjectSignedUrlResolver = typing.Callable[[ReadPlanObjectRef], str]
"""Function that signs the version of a file that a read plan names, and returns a download URL for it.

It receives the whole ``ReadPlanObjectRef``, not only a file ID, so the URL is for the version the reference names,
or for the file's current version when the reference names none.
:py:class:`~roboto.domain.topics.mcap_topic_reader.SignedUrlResolver`, which ``McapTopicReader`` uses, instead takes a
file ID and signs the file's current version."""


@dataclasses.dataclass(frozen=True)
class SuppliedField:
    """Field one file supplies to the read: the field at ``path``, less the fields at ``excluded``.

    Other scan tasks supply the excluded fields, and they may read the same file.
    """

    path: FieldPath

    excluded: tuple[FieldPath, ...] = ()
    """Paths strictly inside ``path``, none inside another."""


@dataclasses.dataclass(frozen=True)
class ScanTaskGroup:
    """Group of a partition's scan tasks that read one file, with the fields they supply.

    Every scan task in the group agrees on the file's format, transformations and topic name.
    """

    format: RepresentationStorageFormat

    object: ReadPlanObjectRef
    """File the scan tasks read, and the version of it to read."""

    supplies: tuple[SuppliedField, ...]
    """Fields the file supplies, in the order of the projected paths they come from.

    Only projected paths with no other projected path inside them count, sorted by their components. For one path, the
    supplied field at the path itself comes before the subtrees inside it, which come in plan order. Empty when the
    file is read only for its row numbers and timestamps.
    """

    topic_name: typing.Optional[str]
    """Name of the topic the scan tasks read from the file, as ``ReadPlanScanTask.topic_name`` describes."""


@dataclasses.dataclass(frozen=True)
class FileDecodeParams:
    """Settings for decoding a file that the read plan does not give: how to reach the file and whether to cache it.

    Caching applies to Parquet files only; MCAP files are always read over HTTP.
    """

    cache_dir: pathlib.Path
    """Directory Parquet files are cached under."""

    cache_policy: CachePolicy
    """Whether each Parquet file is downloaded to ``cache_dir`` before it is read."""

    signed_url_resolver: ObjectSignedUrlResolver
    """Function that returns a signed download URL for each file the decoder reads."""


class FileDecoder(abc.ABC):
    """Decoder that reads the fields one file supplies to a partition as ``pyarrow.RecordBatch`` objects.

    Opening a decoder opens its file, so its fields are known before the first batch. Close it when done, or use it as
    a context manager.
    """

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(
        self,
        exc_type: typing.Optional[type[BaseException]],
        exc: typing.Optional[BaseException],
        traceback: typing.Optional[types.TracebackType],
    ) -> None:
        self.close()

    @property
    @abc.abstractmethod
    def value_fields(self) -> list["pyarrow.Field"]:
        """Value columns, one per top-level field the file supplies, sorted by name by Unicode code point.

        Each struct keeps the fields the file supplies, in the order the file stores them.
        """

    @abc.abstractmethod
    def batches(self) -> collections.abc.Iterator["pyarrow.RecordBatch"]:
        """Return an iterator over the window's rows, in batches and in the file's stored row order.

        Iterate the result only once. When the partition declares a ``data_range``, only the window's rows inside that
        slice of the file are returned.

        Each batch has the columns of ``roboto.experimental.topics.batch_transforms.topic_data_schema`` over
        ``value_fields``: the row number, the timestamp, then the value columns.

        - A row's number is its 0-based position among the file's rows of the topic, counting every stored row,
          including rows outside the window or the ``data_range`` and rows with a null timestamp, so a row has the
          same number in every file of its partition.
        - The timestamp is absolute: the stored value in nanoseconds plus the partition's ``time_offset_ns``.

        Where one batch ends and the next begins carries no meaning.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release the file. Calling it more than once is safe."""

    @abc.abstractmethod
    def struct_field_names(self, path: FieldPath) -> typing.Optional[list[str]]:
        """Return the names of the fields of the struct at ``path`` in the file, in the file's order.

        Args:
            path: Path of the struct within the topic's messages.

        Returns:
            The field names, or ``None`` when the file has no struct at ``path``.
        """


FileDecoderOpener = typing.Callable[[ScanTaskGroup, ReadPlanPartition, TimeWindow], FileDecoder]
"""Function that opens a decoder of a group's file for a partition and its window, and returns the ``FileDecoder``.

The window is in nanoseconds since the Unix epoch and includes both ends. The decoder keeps the rows whose timestamp,
once the partition's ``time_offset_ns`` is added, lies in it.
"""
