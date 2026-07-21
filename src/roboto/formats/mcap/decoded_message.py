# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ..fields import FieldSelection
from .accessor import (
    AccessorCache,
    compile_accessors,
    getter_for,
)


class DecodedMessage:
    """Facade for values returned from message decoders.

    Provides a unified interface for working with decoded messages regardless
    of their original encoding format or source. Handles the conversion of decoded
    message data into dictionary format suitable for analysis and processing.

    A decoded message is a nested ``dict`` / sequence / scalar value: JSON channels and the
    shared ``mcap_codec`` decoder (which handles the ROS1, ROS2/CDR, and IDL encodings) both
    materialize to ``dict``, so one dictionary interface serves every encoding.

    This class filters that decoded value down to the specified fields and presents it
    through a consistent dictionary interface.
    """

    __message: typing.Any
    __fields: collections.abc.Sequence[FieldSelection]
    __accessor_cache: typing.Optional[AccessorCache]

    @staticmethod
    def is_path_match(attrib: str, field_path: str) -> bool:
        """Check if an attribute path matches or is a parent of a field path.

        Determines whether a given attribute path should be included when filtering
        message data based on the specified fields.

        Args:
            attrib: Attribute path to check (e.g., "pose.position").
            field_path: Target field path (e.g., "pose.position.x").

        Returns:
            True if the attribute matches or is a parent of the field path.

        Examples:
            >>> DecodedMessage.is_path_match("pose", "pose.position.x")
            True
            >>> DecodedMessage.is_path_match("pose.position", "pose.position.x")
            True
            >>> DecodedMessage.is_path_match("pose.position.x", "pose.position.x")
            True
            >>> DecodedMessage.is_path_match("velocity", "pose.position.x")
            False
        """
        if attrib == field_path:
            return True

        attrib_parts = attrib.split(".")
        path_parts = field_path.split(".")

        if len(attrib_parts) >= len(path_parts):
            return False

        return attrib_parts == path_parts[: len(attrib_parts)]

    def __init__(
        self,
        msg: typing.Any,
        fields: collections.abc.Sequence[FieldSelection],
        accessor_cache: typing.Optional[AccessorCache] = None,
    ):
        """Wrap a decoded message for dictionary conversion.

        Args:
            msg: The decoded message -- a nested ``dict`` / sequence / scalar value. JSON
                channels and the shared ``mcap_codec`` decoder (ROS1, ROS2/CDR, IDL) both
                materialize to ``dict``.
            fields: Fields to extract from the message.
            accessor_cache: Optional cache that lets repeated decodes from the same
                read pass skip per-message accessor compilation. The reader owns the
                cache and passes it in; one-off callers can leave it ``None``.
        """
        self.__message = msg
        self.__fields = fields
        self.__accessor_cache = accessor_cache

    def to_dict(self) -> dict:
        """Convert the decoded message to a dictionary format.

        Extracts and organizes message data into a dictionary structure,
        including only the attributes that match the specified fields.

        Returns:
            Dictionary containing the filtered message data with attribute names as keys.

        Examples:
            >>> # Assuming fields include "pose.position.x" and "velocity"
            >>> decoded_msg = DecodedMessage(ros_message, fields)
            >>> data_dict = decoded_msg.to_dict()
            >>> print(data_dict)
            {'pose': {'position': {'x': 1.5}}, 'velocity': 2.0}
        """
        getter = getter_for(self.__message)
        if self.__accessor_cache is not None:
            accessors = self.__accessor_cache.get_or_compile(self.__fields, self.__message, getter)
        else:
            accessors, _ = compile_accessors(self.__fields, self.__message, getter)
        accumulator: dict[str, typing.Any] = {}
        for accessor in accessors:
            accessor(self.__message, accumulator)
        return accumulator
