# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The message dialect of an MCAP file, resolved from its schema encoding.

Two decode decisions depend on which robotics framework wrote a file: the names a
ROS time struct's subfields carry (``secs``/``nsecs`` for ROS1, ``sec``/``nanosec``
for ROS2) and the signedness of the deprecated ``byte``/``char`` scalar aliases
(ROS1 ``byte``=int8/``char``=uint8; ROS2 reverses both).
"""

from __future__ import annotations

import enum
import typing

import mcap.well_known


class McapDialect(enum.Enum):
    """The robotics framework dialect of an MCAP file's messages.

    ``OTHER`` covers every non-ROS encoding (JSON, omgidl, protobuf, flatbuffer,
    self-describing) and any absent or unknown encoding.
    """

    ROS1 = "ros1"
    ROS2 = "ros2"
    OTHER = "other"


def dialect_from_schema_encoding(encoding: typing.Optional[str]) -> McapDialect:
    """The :py:class:`McapDialect` named by an MCAP Schema record's ``encoding``.

    ``ros1msg`` -> ROS1; ``ros2msg``/``ros2idl`` -> ROS2; every other encoding
    (including ``None``, an unknown string, or a non-ROS well-known encoding) ->
    OTHER. Literals are taken from :py:class:`mcap.well_known.SchemaEncoding`.

    Examples:
        >>> dialect_from_schema_encoding("ros1msg")
        <McapDialect.ROS1: 'ros1'>
        >>> dialect_from_schema_encoding("ros2idl")
        <McapDialect.ROS2: 'ros2'>
        >>> dialect_from_schema_encoding(None)
        <McapDialect.OTHER: 'other'>
    """
    if encoding == mcap.well_known.SchemaEncoding.ROS1:
        return McapDialect.ROS1
    if encoding in (mcap.well_known.SchemaEncoding.ROS2, mcap.well_known.SchemaEncoding.ROS2IDL):
        return McapDialect.ROS2
    return McapDialect.OTHER
