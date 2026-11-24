# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fetching and decoding of topic data stored in MCAP files.

:py:func:`~roboto.formats.mcap.open_for_window` opens an MCAP file at a URL and downloads in advance only the chunks,
MCAP's blocks of stored messages, that hold messages in a time range and, optionally, on one topic.
:py:class:`~roboto.formats.mcap.McapReader` reads messages from that file or any other MCAP stream, decodes messages
encoded as JSON, msgpack, ROS 1, or CDR (ROS 2 and OMG IDL schemas), and keeps only the selected fields. Methods such
as :py:meth:`~roboto.domain.topics.Topic.get_data` and :py:meth:`~roboto.domain.topics.MessagePath.get_data` read MCAP
files through this package, so most code never calls it.
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
from .fetch import open_for_window
from .reader import END_OF_STREAM, McapReader

__all__ = (
    "Accessor",
    "END_OF_STREAM",
    "McapReader",
    "Resolution",
    "build_accessor",
    "compile_accessors",
    "getter_for",
    "none_resolution",
    "open_for_window",
    "remap_time_fields",
    "sequence_resolution",
    "simple_resolution",
)
