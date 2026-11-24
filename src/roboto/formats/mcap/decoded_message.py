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
    """Message decoded from an MCAP file, which ``to_dict`` reduces to the fields a caller selected.

    :py:meth:`~roboto.formats.mcap.McapReader.next` returns one for each message it reads. Import it from
    ``roboto.formats.mcap.decoded_message``.

    Args:
        msg: Decoded message, as nested dictionaries, sequences, and scalars. JSON, msgpack, ROS 1, ROS 2, and IDL
            messages all decode to this form.
        fields: Fields ``to_dict`` returns.
        accessor_cache: Cache that lets the messages of one read reuse the functions compiled to read each field,
            instead of compiling them for every message. :py:class:`~roboto.formats.mcap.McapReader` passes one.
            ``None`` compiles them for this message alone.
    """

    __message: typing.Any
    __fields: collections.abc.Sequence[FieldSelection]
    __accessor_cache: typing.Optional[AccessorCache]

    @staticmethod
    def is_path_match(attrib: str, field_path: str) -> bool:
        """Return whether ``attrib`` is the same message path as ``field_path`` or one of its ancestors.

        Both paths are dot-delimited, and they are compared component by component, so ``"pose.pos"`` is no ancestor
        of ``"pose.position.x"``. A component that itself contains a dot cannot be told apart from two nested
        components.

        Args:
            attrib: Message path to test, such as ``"pose.position"``.
            field_path: Message path of the selected field, such as ``"pose.position.x"``.

        Examples:
            >>> DecodedMessage.is_path_match("pose", "pose.position.x")
            True
            >>> DecodedMessage.is_path_match("pose.position", "pose.position.x")
            True
            >>> DecodedMessage.is_path_match("pose.position.x", "pose.position.x")
            True
            >>> DecodedMessage.is_path_match("pose.pos", "pose.position.x")
            False
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
        self.__message = msg
        self.__fields = fields
        self.__accessor_cache = accessor_cache

    def to_dict(self) -> dict:
        """Return the message's selected fields as a dictionary nested the way the message is.

        The dictionary holds only the fields given at construction:

        - A field inside a sequence becomes a list holding one dictionary per element.
        - A field the message lacks is left out, though dictionaries that enclose it may appear, empty.
        - A path ending in ``nsec`` that reaches a ROS 2 ``Time`` or ``Duration`` value reads that value's
          ``nanosec`` key, and returns it under ``nanosec``.

        Examples:
            >>> from roboto.formats import FieldSelection
            >>> fields = [
            ...     FieldSelection(path_in_schema=("pose", "position", "x")),
            ...     FieldSelection(path_in_schema=("velocity",)),
            ... ]
            >>> message = {"pose": {"position": {"x": 1.5, "y": 0.2}}, "velocity": 2.0, "status": "ok"}
            >>> DecodedMessage(message, fields).to_dict()
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
