# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Decoding the files of a read plan's partitions into RecordBatches of topic data."""

from .common import (
    FileDecodeParams,
    FileDecoder,
    FileDecoderOpener,
    ScanTaskGroup,
    SuppliedField,
)
from .file_decoder import make_file_decoder_opener
from .parquet import CACHED_PARQUET_NAME_PATTERN

__all__ = [
    "CACHED_PARQUET_NAME_PATTERN",
    "FileDecodeParams",
    "FileDecoder",
    "FileDecoderOpener",
    "ScanTaskGroup",
    "SuppliedField",
    "make_file_decoder_opener",
]
