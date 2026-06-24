# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fetching and decoding topic data stored in Parquet files.

Covers cache-policy-driven opening of remote Parquet files (local cache reuse,
atomic download, or HTTP streaming), row-group time filtering, column
projection from schema field paths, and timestamp extraction.
"""

from .arrow_to_roboto import generate_message_path_requests
from .fetch import open_parquet_file, parquet_file_from_url
from .parquet_parser import ParquetParser
from .table_transforms import (
    compute_time_filter_mask,
    extract_timestamp_field,
    extract_timestamps,
    resolve_columns,
    should_read_row_group,
)
from .timestamp import Timestamp

__all__ = (
    "ParquetParser",
    "Timestamp",
    "compute_time_filter_mask",
    "extract_timestamp_field",
    "extract_timestamps",
    "generate_message_path_requests",
    "open_parquet_file",
    "parquet_file_from_url",
    "resolve_columns",
    "should_read_row_group",
)
