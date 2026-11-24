# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from ....domain.topics import RepresentationStorageFormat
from ....exceptions import (
    ReadPlanExecutionErrorKind,
    RobotoReadPlanExecutionException,
)
from ..read_plan import ReadPlanPartition, TimeWindow
from .common import (
    FileDecodeParams,
    FileDecoder,
    FileDecoderOpener,
    ScanTaskGroup,
)
from .mcap import McapFileDecoder
from .parquet import ParquetFileDecoder


def make_file_decoder_opener(params: FileDecodeParams) -> FileDecoderOpener:
    """Build a ``FileDecoderOpener`` that reads files through ``params``.

    The opener picks the decoder by the format of the group's file: ``McapFileDecoder`` for MCAP and
    ``ParquetFileDecoder`` for Parquet.

    Raises:
        RobotoReadPlanExecutionException: With kind
            :py:attr:`~roboto.exceptions.ReadPlanExecutionErrorKind.UNSUPPORTED_FORMAT`, when the group's format is
            neither MCAP nor Parquet. Raised when the returned function is called, which also raises what the chosen
            decoder raises when it opens the file.
    """

    def open_file_decoder(group: ScanTaskGroup, partition: ReadPlanPartition, window: TimeWindow) -> FileDecoder:
        if group.format == RepresentationStorageFormat.MCAP:
            return McapFileDecoder(group, partition, window, params)
        if group.format == RepresentationStorageFormat.PARQUET:
            return ParquetFileDecoder(group, partition, window, params)
        # A scan task built by model_construct, which skips validation, can hold a format the enum lacks.
        raise RobotoReadPlanExecutionException(
            f"Topic partition {partition.topic_part_id} uses {group.format}. "
            "The topic data reader supports MCAP and Parquet only.",
            kind=ReadPlanExecutionErrorKind.UNSUPPORTED_FORMAT,
        )

    return open_file_decoder
