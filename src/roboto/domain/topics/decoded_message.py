# Copyright (c) 2024 Roboto Technologies, Inc.
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
    """Abstract collection of utilities used to interact with values returned from MCAP decoders"""

    @staticmethod
    @abc.abstractmethod
    def get_attribute_names(value) -> collections.abc.Sequence[str]: ...

    @staticmethod
    @abc.abstractmethod
    def get_attribute(value, attribute) -> typing.Any: ...

    @staticmethod
    @abc.abstractmethod
    def has_sub_attributes(value) -> bool: ...


class ClassAttrGetter(AttrGetter):
    """Getter for ROS decoded data, which are yielded as dynamically created classes at runtime"""

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
    """Getter for JSON decoded data, which are yielded as dictionaries at runtime"""

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
    """
    Facade for value returned from an MCAP Message decoder.

    A decoded message may be one a few different types:
      - A dictionary in the case the message data is encoded as JSON
      - A dynamically created, custom object type in the case the message data is encoded as ROS1 or ROS2 (CDR).
    """

    __message: typing.Union[dict, typing.Type]
    __message_paths: collections.abc.Sequence[MessagePathRecord]

    def __init__(
        self,
        msg: typing.Union[dict, typing.Type],
        message_paths: collections.abc.Sequence[MessagePathRecord],
    ):
        self.__message = msg
        self.__message_paths = message_paths

    def to_dict(self) -> dict:
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
                record.message_path.startswith(attribute)
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
                    record.message_path.startswith(next_attr_path)
                    for record in self.__message_paths
                ):
                    self.__unpack(
                        accumulator=accumulator[attr],
                        obj=value,
                        attr=slot,
                        attr_path=next_attr_path,
                        getter=getter,
                    )
