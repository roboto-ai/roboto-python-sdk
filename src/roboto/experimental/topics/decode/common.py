# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
import typing

from ....domain.topics.record import FieldPath
from ....storage import CachePolicy
from ..batch_transforms import TIMESTAMP_FIELD_NAME

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

SignedUrlResolver = typing.Callable[[str], str]
"""Resolves a file id (``fs_node_id``) to a signed download URL."""


def disambiguated_timestamp_name(taken: collections.abc.Iterable[str]) -> str:
    """The emitted timestamp column name, suffixed with ``_`` until it collides with no output column.

    ``taken`` is the set of output-column names the timestamp must not shadow —
    the MCAP path passes the projected schema fields' names; the Parquet path
    passes the file's own Arrow column names.
    """
    names = set(taken)
    ts_name = TIMESTAMP_FIELD_NAME

    while ts_name in names:
        ts_name += "_"

    return ts_name


def leaf_most(paths: collections.abc.Sequence[FieldPath]) -> list[FieldPath]:
    """Drop every path that has a strict descendant in the set.

    A projection enumerates registered fields at every level (a struct parent
    and its children both appear). Decoding the parent would read its whole
    subtree, defeating an exclusion of one child — so decoders read only the
    leaf-most projected paths, which together cover exactly the projected set.
    """
    # Lexicographic order on path components places a parent immediately
    # before its first descendant, so one neighbor check finds every ancestor.
    ordered = sorted(set(paths))
    leaves: list[FieldPath] = []
    for index, current in enumerate(ordered):
        has_descendant = index + 1 < len(ordered) and ordered[index + 1][: len(current)] == current
        if not has_descendant:
            leaves.append(current)
    return leaves


@dataclasses.dataclass(frozen=True)
class ScanTaskDecodeParams:
    """Execution inputs a scan-task decode needs beyond the read plan.

    The plan says what to read; these supply how to reach and cache it:
    a resolver that mints download URLs, plus the local-disk cache policy and directory.
    Caching applies to Parquet scan tasks only — MCAP always streams.
    """

    signed_url_resolver: SignedUrlResolver
    """Mints a signed download URL for a scan task's backing file."""

    cache_policy: CachePolicy
    """Whether fetched Parquet files are cached to local disk."""

    cache_dir: pathlib.Path
    """Directory Parquet files are cached under."""


class DecodedScanTask:
    """One scan task decoded into RecordBatches.

    Decoding (including the network fetch) starts when the iterator returned by :py:meth:`batches` is first advanced;
    consume it once.
    """

    def __init__(
        self,
        *,
        batches_factory: typing.Callable[[], collections.abc.Iterator["pyarrow.RecordBatch"]],
    ) -> None:
        self.__batches_factory = batches_factory

    def batches(self) -> collections.abc.Iterator["pyarrow.RecordBatch"]:
        """Decode into RecordBatches, each prefixed with a metadata-marked stored-time column.

        Rows come out in the scan task's persisted order.
        For MCAP, that's the reader's native chunk order, which is itself the persisted order.
        For Parquet, that's the file's row order.
        Every representation of a partition must share one persisted row order.

        Batch boundaries themselves carry no meaning.
        """
        return self.__batches_factory()
