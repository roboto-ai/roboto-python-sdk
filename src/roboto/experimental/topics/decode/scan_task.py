# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing

from ....domain.topics import RepresentationStorageFormat
from ....domain.topics.record import FieldPath
from ..read_plan import (
    ReadPlanPartition,
    ReadPlanScanTask,
    TimeWindow,
)
from .common import DecodedScanTask, ScanTaskDecodeParams
from .mcap import decode_mcap_batches
from .parquet import decode_parquet_batches

ScanTaskDecoder = typing.Callable[
    [
        ReadPlanScanTask,
        ReadPlanPartition,
        TimeWindow,
        collections.abc.Sequence[FieldPath],
    ],
    DecodedScanTask,
]
"""Decodes one scan task into a stream of native-order RecordBatches.

Called with the scan task, its partition (for the timestamp designation), the
window translated into the partition's stored-time domain, the projection
restricted to the scan task's subtree. Produced timestamps are in the
stored-time domain; the executor applies the partition's ``time_offset_ns``.
"""


def make_scan_task_decoder(
    params: ScanTaskDecodeParams,
) -> ScanTaskDecoder:
    """Bind execution inputs into a :py:data:`ScanTaskDecoder`.

    The returned decoder decodes one scan task (one file, one format), filtered and projected,
    dispatching on the scan task's server-declared ``format``.

    Timestamps are keyed off the partition's timestamp designation and produced in the stored-time domain;
    the caller applies the partition's ``time_offset_ns``.
    Rows are filtered to the decoder's ``window`` (inclusive on both ends) and projected to its ``projection_paths``.

    MCAP scan tasks decode through the Rust ``mcap_codec`` batch decoder, which reads each column's
    Arrow type from the file's own embedded schema -- no ingestion-declared schema tree is needed.
    Parquet decodes column-wise from its own file footer.

    Args:
        params: Execution inputs (URL resolution and cache policy).

    Returns:
        A decoder that, given a scan task, its plan partition, an inclusive time window, and the projected
        field paths the scan task covers, returns the decoded scan task; consume its batches once.

    Raises:
        The returned decoder raises:

        NotImplementedError: The scan task's storage format has no decoder, or
            a Parquet scan task is designated an envelope-derived timestamp.
    """

    def decode(
        scan_task: ReadPlanScanTask,
        partition: ReadPlanPartition,
        window: TimeWindow,
        projection_paths: collections.abc.Sequence[FieldPath],
    ) -> DecodedScanTask:
        if scan_task.format == RepresentationStorageFormat.MCAP:
            return DecodedScanTask(
                batches_factory=lambda: decode_mcap_batches(
                    scan_task, partition.timestamp, window, projection_paths, params
                ),
            )

        if scan_task.format == RepresentationStorageFormat.PARQUET:
            return DecodedScanTask(
                batches_factory=lambda: decode_parquet_batches(
                    scan_task, partition.timestamp, window, projection_paths, params
                ),
            )

        raise NotImplementedError(
            f"No decoder for topic data stored as {scan_task.format.value!r}. "
            "Make sure you're using the most recent Roboto SDK version. "
            "If this problem persists, please reach out to Roboto support."
        )

    return decode
