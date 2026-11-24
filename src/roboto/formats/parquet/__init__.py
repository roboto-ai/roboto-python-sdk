# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fetching and decoding of topic data stored in Parquet files.

:py:func:`~roboto.formats.parquet.parquet_file_from_url` opens a Parquet file from a signed URL, such as one
:py:meth:`~roboto.domain.files.File.get_signed_url` returns, and reads it over HTTP without writing it to disk.
:py:func:`~roboto.formats.parquet.open_parquet_file` follows a :py:class:`~roboto.storage.CachePolicy` instead: it
reads a copy already in the local cache, downloads the file to the cache, or reads it over HTTP. The other functions
skip row groups outside a time range, read only the selected fields, and extract each row's timestamp.
:py:class:`~roboto.formats.parquet.ParquetParser` reads a local Parquet file's schema and timestamp column, from which
:py:func:`~roboto.formats.parquet.generate_message_path_requests` builds a new topic's message paths. Methods such as
:py:meth:`~roboto.domain.topics.Topic.get_data` and :py:meth:`~roboto.domain.topics.MessagePath.get_data` read Parquet
files through this package, and :py:meth:`~roboto.domain.topics.Topic.create_from_df` stores a DataFrame through it,
so most code never calls it. Requires the ``roboto[analytics]`` extra: ``pip install roboto[analytics]``.
"""

from .arrow_to_roboto import generate_message_path_requests
from .fetch import open_parquet_file, parquet_file_from_url
from .parquet_parser import ParquetParser
from .table_transforms import (
    compute_time_filter_mask,
    extract_timestamp_field,
    extract_timestamps,
    narrow_list_nested_fields,
    resolve_columns,
    select_fields,
    should_narrow_list_nested_fields,
    should_read_row_group,
    timestamp_statistics,
)
from .timestamp import Timestamp

__all__ = (
    "ParquetParser",
    "Timestamp",
    "compute_time_filter_mask",
    "extract_timestamp_field",
    "extract_timestamps",
    "generate_message_path_requests",
    "narrow_list_nested_fields",
    "open_parquet_file",
    "parquet_file_from_url",
    "resolve_columns",
    "select_fields",
    "should_narrow_list_nested_fields",
    "should_read_row_group",
    "timestamp_statistics",
)
