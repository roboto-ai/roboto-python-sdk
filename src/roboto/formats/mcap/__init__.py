# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fetching and decoding topic data stored in MCAP files.

Covers chunk-index-driven prefetching over HTTP range requests and decoding of
JSON-, ROS1-, and ROS2-encoded messages with field-path projection.
"""

from .accessor import (
    Accessor,
    Resolution,
    build_accessor,
    compile_accessors,
    getter_for,
    none_resolution,
    remap_time_fields,
    sequence_resolution,
    simple_resolution,
)
from .dialect import McapDialect, dialect_from_schema_encoding
from .fetch import open_for_window
from .reader import END_OF_STREAM, McapReader

__all__ = (
    "Accessor",
    "END_OF_STREAM",
    "McapDialect",
    "McapReader",
    "Resolution",
    "build_accessor",
    "compile_accessors",
    "dialect_from_schema_encoding",
    "getter_for",
    "none_resolution",
    "open_for_window",
    "remap_time_fields",
    "sequence_resolution",
    "simple_resolution",
)
