# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import collections
import collections.abc
import typing

from .record import MessagePathRecord

KNOWN_PATH_MAPPING: dict[str, dict[str, tuple[str, ...]]] = {
    "header.stamp.sec": {
        "sec": (
            # ROS1
            # https://github.com/foxglove/mcap/blob/main/python/mcap-ros1-support/mcap_ros1/_vendor/genpy/rostime.py#L54
            "secs",
            # ROS2: a mapping isn't needed
            # https://github.com/foxglove/mcap/blob/main/python/mcap-ros2-support/mcap_ros2/_dynamic.py#L131
        ),
    },
    "header.stamp.nsec": {
        "nsec": (
            # ROS1
            # https://github.com/foxglove/mcap/blob/main/python/mcap-ros1-support/mcap_ros1/_vendor/genpy/rostime.py#L54
            "nsecs",
            # ROS2
            # https://github.com/foxglove/mcap/blob/main/python/mcap-ros2-support/mcap_ros2/_dynamic.py#L131
            "nanosec",
        )
    },
}


class AttrGetter(abc.ABC):
    """Abstract base class for accessing attributes from decoded messages.

    Provides a unified interface for extracting attributes from different types of
    decoded message data, whether they are dictionaries (JSON) or dynamically
    created classes (ROS1/ROS2). Used by message decoders to handle various
    message encoding formats in a consistent way.
    """

    @staticmethod
    @abc.abstractmethod
    def get_attribute_names(value) -> collections.abc.Sequence[str]:
        """Get the names of all attributes available in the given value.

        Args:
            value: The decoded message value to inspect.

        Returns:
            Sequence of attribute names available in the value.
        """

    @staticmethod
    @abc.abstractmethod
    def get_attribute(value, attribute) -> typing.Any:
        """Get the value of a specific attribute from the given value.

        Args:
            value: The decoded message value to access.
            attribute: Name of the attribute to retrieve.

        Returns:
            The value of the specified attribute.
        """

    @staticmethod
    @abc.abstractmethod
    def has_sub_attributes(value) -> bool:
        """Check if the given value has nested attributes that can be accessed.

        Args:
            value: The decoded message value to inspect.

        Returns:
            True if the value has nested attributes, False otherwise.
        """


class ClassAttrGetter(AttrGetter):
    """Attribute getter for class-based decoded data.

    Handles access to attributes from decoded messages that are represented as
    dynamically created classes with __slots__ at runtime. This includes ROS1,
    ROS2, and other message formats that use class-based representations.
    """

    @staticmethod
    def get_attribute_names(value):
        return value.__slots__

    @staticmethod
    def get_attribute(value, attribute):
        return getattr(value, attribute)

    @staticmethod
    def has_sub_attributes(value):
        return hasattr(value, "__slots__")


class DictAttrGetter(AttrGetter):
    """Attribute getter for JSON decoded data.

    Handles access to attributes from JSON decoded messages, which are
    represented as standard Python dictionaries.
    """

    @staticmethod
    def get_attribute_names(value):
        return value.keys()

    @staticmethod
    def get_attribute(value, attribute):
        return value[attribute]

    @staticmethod
    def has_sub_attributes(value):
        return hasattr(value, "keys")


class DecodedMessage:
    """Facade for values returned from message decoders.

    Provides a unified interface for working with decoded messages regardless
    of their original encoding format or source. Handles the conversion of decoded
    message data into dictionary format suitable for analysis and processing.

    A decoded message may be one of several types:
    - A dictionary when the message data is encoded as JSON
    - A dynamically created class when the message data is encoded as ROS1, ROS2 (CDR), or other binary formats

    This class abstracts away the differences between these formats and provides
    consistent access to message data through a dictionary interface, filtering
    the output based on the specified message paths.
    """

    __message: typing.Union[dict, typing.Type]
    __message_paths: collections.abc.Sequence[MessagePathRecord]

    @staticmethod
    def is_path_match(attrib: str, message_path: str) -> bool:
        """Check if an attribute path matches or is a parent of a message path.

        Determines whether a given attribute path should be included when filtering
        message data based on the specified message paths.

        Args:
            attrib: Attribute path to check (e.g., "pose.position").
            message_path: Target message path (e.g., "pose.position.x").

        Returns:
            True if the attribute matches or is a parent of the message path.

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
        if attrib == message_path:
            return True

        attrib_parts = attrib.split(".")
        path_parts = message_path.split(".")

        if len(attrib_parts) >= len(path_parts):
            return False

        return attrib_parts == path_parts[: len(attrib_parts)]

    def __init__(
        self,
        msg: typing.Union[dict, typing.Type],
        message_paths: collections.abc.Sequence[MessagePathRecord],
    ):
        self.__message = msg
        self.__message_paths = message_paths

    def to_dict(self) -> dict:
        """Convert the decoded message to a dictionary format.

        Extracts and organizes message data into a dictionary structure, including
        only the attributes that match the specified message paths. Handles both
        flat and nested message structures.

        Returns:
            Dictionary containing the filtered message data with attribute names as keys.

        Examples:
            >>> # Assuming message_paths include "pose.position.x" and "velocity"
            >>> decoded_msg = DecodedMessage(ros_message, message_paths)
            >>> data_dict = decoded_msg.to_dict()
            >>> print(data_dict)
            {'pose': {'position': {'x': 1.5}}, 'velocity': 2.0}
        """
        accumulator: dict[str, typing.Any] = {}

        getter: AttrGetter = ClassAttrGetter()

        if isinstance(self.__message, dict):
            # Message data was encoded as JSON
            getter = DictAttrGetter()

        # Assume a 1:1 relation between slots and message fields
        # Ref:
        #   - https://github.com/foxglove/mcap/blob/main/python/mcap-ros1-support/mcap_ros1/_vendor/genpy/message.py#L334-L338  # noqa E501
        #   - https://github.com/foxglove/mcap/blob/main/python/mcap-ros2-support/mcap_ros2/_dynamic.py#L258
        for attribute in getter.get_attribute_names(self.__message):
            if any(
                DecodedMessage.is_path_match(attribute, record.message_path)
                for record in self.__message_paths
            ):
                self.__unpack(
                    accumulator=accumulator,
                    obj=self.__message,
                    attr=attribute,
                    attr_path=attribute,
                    getter=getter,
                )

        return accumulator

    def __unpack(
        self,
        accumulator: dict[str, typing.Any],
        obj: typing.Any,
        attr: str,
        attr_path: str,
        getter: AttrGetter,
    ):
        value = getter.get_attribute(obj, attr)
        if not getter.has_sub_attributes(value):
            accumulator[attr] = value
        else:
            accumulator[attr] = {}
            for slot in getter.get_attribute_names(value):
                next_attr_path = ".".join([attr_path, slot])
                if any(
                    DecodedMessage.is_path_match(next_attr_path, record.message_path)
                    for record in self.__message_paths
                ):
                    self.__unpack(
                        accumulator=accumulator[attr],
                        obj=value,
                        attr=slot,
                        attr_path=next_attr_path,
                        getter=getter,
                    )
