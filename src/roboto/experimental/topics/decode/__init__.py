# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Decoders that read the MCAP and Parquet files holding a topic's data into ``pyarrow.RecordBatch`` objects.

``roboto.experimental.topics.Topic.get_data_as_record_batches``, and ``Topic.get_data`` and ``Topic.get_data_as_df``,
built on it, read topic data through this package, so most code never calls it. ``make_file_decoder_opener`` builds
the function that opens a ``FileDecoder`` on each file, choosing the MCAP or Parquet decoder by the file's format;
``cached_parquet_name`` names the local copy of a cached Parquet file. Requires the ``roboto[analytics]`` extra:
``pip install roboto[analytics]``.
"""

from .common import (
    FileDecodeParams,
    FileDecoder,
    FileDecoderOpener,
    ScanTaskGroup,
    SuppliedField,
)
from .file_decoder import make_file_decoder_opener
from .parquet import cached_parquet_name

__all__ = [
    "FileDecodeParams",
    "FileDecoder",
    "FileDecoderOpener",
    "ScanTaskGroup",
    "SuppliedField",
    "cached_parquet_name",
    "make_file_decoder_opener",
]
