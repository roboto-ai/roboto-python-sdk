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
    """Return a :py:data:`~roboto.experimental.topics.decode.FileDecoderOpener` that reads files through ``params``.

    The opener picks the decoder by the group's format:
    :py:class:`~roboto.experimental.topics.decode.mcap.McapFileDecoder` or
    :py:class:`~roboto.experimental.topics.decode.parquet.ParquetFileDecoder`.

    Args:
        params: How to reach each file and whether to cache it.

    Returns:
        An opener of file decoders. The opener raises :py:class:`~roboto.exceptions.RobotoReadPlanExecutionException`
        with kind ``unsupported-format`` for a format other than MCAP or Parquet, and passes on what opening the
        decoder raises.
    """

    def open_file_decoder(group: ScanTaskGroup, partition: ReadPlanPartition, window: TimeWindow) -> FileDecoder:
        if group.format == RepresentationStorageFormat.MCAP:
            return McapFileDecoder(group, partition, window, params)
        if group.format == RepresentationStorageFormat.PARQUET:
            return ParquetFileDecoder(group, partition, window, params)
        # A plan built without validation can hold a format name the enum lacks.
        raise RobotoReadPlanExecutionException(
            f"Topic partition {partition.topic_part_id} uses {group.format}. "
            "The topic data reader supports MCAP and Parquet only.",
            kind=ReadPlanExecutionErrorKind.UNSUPPORTED_FORMAT,
        )

    return open_file_decoder
