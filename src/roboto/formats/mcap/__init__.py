# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fetching and decoding topic data stored in MCAP files.

Covers chunk-index-driven prefetching over HTTP range requests and decoding of
JSON-, ROS1-, and ROS2-encoded messages with field-path projection.
"""

from .accessor import Accessor, compile_accessors, path_crosses_no_sequence
from .decoded_message import getter_for
from .fetch import open_for_window
from .reader import END_OF_STREAM, McapReader

__all__ = (
    "Accessor",
    "END_OF_STREAM",
    "McapReader",
    "compile_accessors",
    "getter_for",
    "open_for_window",
    "path_crosses_no_sequence",
)
