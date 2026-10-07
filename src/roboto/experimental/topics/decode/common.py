# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What reading one file of a read plan's partition takes and gives."""

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

SignedUrlResolver = typing.Callable[[str], str]
"""Resolves a file id (``fs_node_id``) to a signed download URL."""


@dataclasses.dataclass(frozen=True)
class SuppliedField:
    """The field at ``path``, which one file supplies to the read,
    less the fields at ``excluded``, which other scan tasks supply (they may read the same file)."""

    path: FieldPath

    excluded: tuple[FieldPath, ...] = ()
    """Paths strictly inside ``path``, none inside another."""


@dataclasses.dataclass(frozen=True)
class ScanTaskGroup:
    """The scan tasks of a partition that read one file, and the fields they supply.

    Every scan task in the group agrees on the file's format, transformations and topic name.
    """

    format: RepresentationStorageFormat

    object: ReadPlanObjectRef

    supplies: tuple[SuppliedField, ...]
    """In the order of the leaf-most paths they come from.

    For one path, the supplied field at the path itself comes before the subtrees inside it, which come in plan order.
    Empty when the file is read only for its row numbers and timestamps.
    """

    topic_name: typing.Optional[str]
    """The topic the scan tasks read from the file;
    see :py:attr:`~roboto.experimental.topics.ReadPlanScanTask.topic_name`."""


@dataclasses.dataclass(frozen=True)
class FileDecodeParams:
    """What decoding a file takes beyond the read plan: how to reach the file and whether to cache it.

    Caching applies to Parquet files only; MCAP files always stream.
    """

    cache_dir: pathlib.Path
    """Directory Parquet files are cached under."""

    cache_policy: CachePolicy
    """Whether fetched Parquet files are cached to local disk."""

    signed_url_resolver: SignedUrlResolver
    """Mints a signed download URL for a file."""


class FileDecoder(abc.ABC):
    """Decodes the fields one file supplies to a partition into RecordBatches.

    Opening a decoder opens its file, so its fields are known before the first batch.
    Close it when done, or use it as a context manager.
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
        """The value columns, one per top-level field the file supplies, sorted by name, comparing Unicode code points.

        Each struct keeps the fields the file supplies, in the order the file stores them.
        """

    @abc.abstractmethod
    def batches(self) -> collections.abc.Iterator["pyarrow.RecordBatch"]:
        """The window's rows, in the file's stored row order; iterate it once.

        A partition that declares a ``data_range`` gets only the window's rows inside that slice of the file.
        Each batch has the columns of :py:func:`~roboto.experimental.topics.batch_transforms.topic_data_schema` over
        :py:attr:`value_fields`: the row number, the timestamp, then the value columns.
        A row's number is its 0-based position among the file's rows of the topic, counting every stored row,
        including rows outside the window or the ``data_range`` and rows with a null timestamp, so a row has the same
        number in every file of its partition.
        The timestamp is absolute: the stored value in nanoseconds plus the partition's ``time_offset_ns``.
        Batch boundaries carry no meaning.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release the file. Safe to call more than once."""

    @abc.abstractmethod
    def struct_field_names(self, path: FieldPath) -> typing.Optional[list[str]]:
        """The names of the fields of the struct at ``path`` in the file, in the file's order.

        ``None`` when the file has no struct at ``path``.
        """


FileDecoderOpener = typing.Callable[[ScanTaskGroup, ReadPlanPartition, TimeWindow], FileDecoder]
"""Opens a :py:class:`FileDecoder` of a group's file for its partition and the partition's window.

The window is absolute and includes both ends. A decoder keeps the rows whose absolute timestamp lies in it.
"""
