# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import collections.abc
import typing

import mcap_ros1._vendor.genpy
import mcap_ros2._dynamic

from .message_path_accessor import (
    AccessorCache,
    compile_accessors,
)
from .record import MessagePathRecord


def is_ros1_time_value(val: typing.Any) -> bool:
    return isinstance(val, mcap_ros1._vendor.genpy.TVal)


def is_ros2_time_value(val: typing.Any) -> bool:
    """Structural type checking because Time and Duration classes are dynamically generated"""
    if not hasattr(val, "__slots__"):
        return False

    slots = getattr(val, "__slots__", [])
    for field in mcap_ros2._dynamic.TimeDefinition.fields:
        if field.name not in slots:
            return False

    return True


T = typing.TypeVar("T")


class defaultlist(list[T], typing.Generic[T]):
    """Like collections.defaultdict, but for list.

    Automatically supplies a default value when you access an index that hasn't been set or is out of bounds,
    without raising an IndexError.

    Examples:
        >>> dl = defaultlist[int](factory=lambda: 0)
        >>> dl[5] += 1  # Automatically extends list with 0s up to index 5
        >>> print(dl)  # [0, 0, 0, 0, 0, 1]
    """

    def __init__(self, factory: typing.Callable[[], T]):
        self.factory = factory
        super().__init__()

    @typing.overload
    def __getitem__(self, idx: typing.SupportsIndex) -> T: ...

    @typing.overload
    def __getitem__(self, idx: slice) -> list[T]: ...

    def __getitem__(self, idx: typing.Union[typing.SupportsIndex, slice]) -> typing.Union[T, list[T]]:
        if isinstance(idx, slice):
            return super().__getitem__(idx)
        # Convert SupportsIndex to int for comparison
        index = idx.__index__()
        while index >= len(self):
            self.append(self.factory())
        return super().__getitem__(idx)

    @typing.overload
    def __setitem__(self, idx: typing.SupportsIndex, value: T) -> None: ...

    @typing.overload
    def __setitem__(self, idx: slice, value: typing.Iterable[T]) -> None: ...

    def __setitem__(
        self,
        idx: typing.Union[typing.SupportsIndex, slice],
        value: typing.Union[T, typing.Iterable[T]],
    ) -> None:
        if isinstance(idx, slice):
            super().__setitem__(idx, typing.cast(typing.Iterable[T], value))
        else:
            # Convert SupportsIndex to int for comparison
            index = idx.__index__()
            while index >= len(self):
                self.append(self.factory())
            super().__setitem__(idx, typing.cast(T, value))


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
    def has_attribute(value, attribute: str) -> bool:
        """Check if the given value has a specific attribute.

        Args:
            value: The decoded message value to inspect.
            attribute: Name of the attribute to check for.

        Returns:
            True if the value has the specified attribute, False otherwise.
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
    def has_attribute(value, attribute: str) -> bool:
        return hasattr(value, attribute)

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
    def has_attribute(value, attribute: str) -> bool:
        return attribute in value

    @staticmethod
    def has_sub_attributes(value):
        return hasattr(value, "keys")


# Module-level singletons: the getters carry no per-instance state, so reusing
# one instance per shape avoids allocating a fresh getter on every `to_dict()`.
_CLASS_GETTER = ClassAttrGetter()
_DICT_GETTER = DictAttrGetter()


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

    __message: typing.Any
    __message_paths: collections.abc.Sequence[MessagePathRecord]
    __accessor_cache: typing.Optional[AccessorCache]

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
        msg: typing.Any,
        message_paths: collections.abc.Sequence[MessagePathRecord],
        accessor_cache: typing.Optional[AccessorCache] = None,
    ):
        """Wrap a decoded message for dictionary conversion.

        Args:
            msg: The decoded message, either a dict (JSON-encoded) or a dynamically
                created class with ``__slots__`` (ROS1/ROS2 binary encoding).
            message_paths: Paths to extract from the message.
            accessor_cache: Optional cache that lets repeated decodes from the same
                read pass skip per-message accessor compilation. The reader owns the
                cache and passes it in; one-off callers can leave it ``None``.
        """
        self.__message = msg
        self.__message_paths = message_paths
        self.__accessor_cache = accessor_cache

    def to_dict(self) -> dict:
        """Convert the decoded message to a dictionary format.

        Extracts and organizes message data into a dictionary structure,
        including only the attributes that match the specified message paths.

        Returns:
            Dictionary containing the filtered message data with attribute names as keys.

        Examples:
            >>> # Assuming message_paths include "pose.position.x" and "velocity"
            >>> decoded_msg = DecodedMessage(ros_message, message_paths)
            >>> data_dict = decoded_msg.to_dict()
            >>> print(data_dict)
            {'pose': {'position': {'x': 1.5}}, 'velocity': 2.0}
        """
        getter: AttrGetter = _DICT_GETTER if isinstance(self.__message, dict) else _CLASS_GETTER
        if self.__accessor_cache is not None:
            accessors = self.__accessor_cache.get_or_compile(self.__message_paths, self.__message, getter)
        else:
            accessors, _ = compile_accessors(self.__message_paths, self.__message, getter)
        accumulator: dict[str, typing.Any] = {}
        for accessor in accessors:
            accessor(self.__message, accumulator)
        return accumulator
