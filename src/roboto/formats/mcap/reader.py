# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import math
import typing

import mcap.reader
import mcap_ros1.decoder

from ..fields import FieldSelection
from .accessor import AccessorCache
from .decoded_message import DecodedMessage
from .json_decoder_factory import (
    JsonDecoderFactory,
)
from .omgidl import make_omgidl_decoder_factory
from .omgidl.decoder_factory import UNDECODABLE_MESSAGE
from .ros2_decoder import make_ros2_decoder_factory


class _EndOfStream:
    """Singleton type for the :data:`END_OF_STREAM` sentinel.

    A dedicated type makes the sentinel both ``is``-comparable and unambiguous
    in a type signature, and gives it a readable ``repr`` in test output.
    """

    _instance: typing.Optional["_EndOfStream"] = None

    def __new__(cls) -> "_EndOfStream":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "END_OF_STREAM"


END_OF_STREAM = _EndOfStream()
"""Sentinel returned by :py:meth:`McapReader.next_decoded` when the stream is exhausted.

A decoded message value can legitimately be ``None`` (a JSON ``null`` payload),
so exhaustion cannot be signaled with ``None`` without making a real null-valued
message indistinguishable from end-of-stream. Callers test ``result is
END_OF_STREAM`` to detect exhaustion and treat every other value -- ``None``
included -- as a delivered message.
"""


class McapEnvelopeTimestamp(typing.NamedTuple):
    """The pair of timestamps an MCAP message envelope carries.

    Every MCAP message records two times in nanoseconds:
    1. ``log_time``, when the message was written to the file, and
    2. ``publish_time``, when its producer published it.


    Both fields are ``math.inf`` when the reader is exhausted.
    """

    log_time: typing.Union[int, float]
    publish_time: typing.Union[int, float]


class McapReader:
    """Reader for processing MCAP files with field projection.

    Provides an iterator interface for reading decoded messages from MCAP files,
    with support for temporal filtering and field selection. Handles
    multiple encoding formats including JSON, ROS1, and ROS2.

    The reader automatically decodes messages using appropriate decoders and
    filters the output based on the specified fields and time range.
    """

    __message_iterator: typing.Iterator[mcap.reader.DecodedMessageTuple]
    __fields: collections.abc.Sequence[FieldSelection]
    __next_unconsummed_decode_result: typing.Union[mcap.reader.DecodedMessageTuple, None] = None
    __accessor_cache: AccessorCache

    def __init__(
        self,
        stream: typing.IO[bytes],
        fields: collections.abc.Sequence[FieldSelection],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        log_time_order: bool = True,
    ):
        """Initialize the MCAP reader with filtering parameters.

        Args:
            stream: Binary stream containing MCAP data to read.
            fields: Fields to project decoded messages to.
            start_time: Optional start time in nanoseconds for temporal filtering.
            end_time: Optional end time in nanoseconds for temporal filtering.
            log_time_order: Whether messages are yielded in log-time order (the
                default) or in file order, which skips the underlying reader's
                cross-chunk ordering heap. Temporal filtering applies either way.
                Only consumers for which message order carries no meaning may opt
                out; any caller that merges readers by timestamp must keep the
                default.

        Examples:
            >>> with open("data.mcap", "rb") as f:
            ...     reader = McapReader(f, fields, start_time=1000, end_time=2000)
            ...     while reader.has_next:
            ...         message = reader.next()
            ...         if message:
            ...             print(message.to_dict())
        """
        json_decoder = JsonDecoderFactory()
        ros1_decoder = mcap_ros1.decoder.DecoderFactory()
        ros2_decoder = make_ros2_decoder_factory()
        omgidl_decoder = make_omgidl_decoder_factory()
        reader = mcap.reader.make_reader(
            stream,
            decoder_factories=[json_decoder, ros1_decoder, ros2_decoder, omgidl_decoder],
        )
        self.__message_iterator = reader.iter_decoded_messages(
            start_time=start_time, end_time=end_time, log_time_order=log_time_order
        )
        self.__fields = fields
        self.__accessor_cache = AccessorCache()
        self.__decode_next()

    @property
    def has_next(self) -> bool:
        """Check if there are more messages available to read.

        Returns:
            True if there are more messages to read, False otherwise.
        """
        return self.__next_unconsummed_decode_result is not None

    @property
    def field_paths(self) -> list[str]:
        """Get the list of fields being projected, as dot-delimited paths.

        Returns the dot-delimited names of the fields provided during initialization.

        Returns:
            List of field names in dot notation.
        """
        return [field.source_path for field in self.__fields]

    @property
    def next_envelope_timestamp(self) -> McapEnvelopeTimestamp:
        """Get the envelope timestamps of the next message to be read.

        Returns:
            The next message's ``log_time`` and ``publish_time`` in nanoseconds,
            or both ``math.inf`` if no more messages.
        """
        if self.__next_unconsummed_decode_result is None:
            return McapEnvelopeTimestamp(log_time=math.inf, publish_time=math.inf)

        message = self.__next_unconsummed_decode_result.message
        return McapEnvelopeTimestamp(log_time=message.log_time, publish_time=message.publish_time)

    def next(self) -> typing.Union[DecodedMessage, None]:
        """Read and return the next decoded message.

        Advances the reader to the next message and returns it as a DecodedMessage
        object, or None if no more messages are available.

        Returns:
            DecodedMessage containing the next message data, or None if no more messages.

        Examples:
            >>> while reader.has_next:
            ...     message = reader.next()
            ...     if message:
            ...         data = message.to_dict()
            ...         print(f"Message at {data.get('log_time')}: {data}")
        """
        next_decode_result = self.__next_unconsummed_decode_result
        self.__decode_next()

        if next_decode_result is not None:
            return DecodedMessage(
                next_decode_result.decoded_message,
                self.__fields,
                accessor_cache=self.__accessor_cache,
            )
        return None

    def next_decoded(self) -> typing.Any:
        """Read and return the next message's raw decoded value, advancing the reader.

        The raw value is what the format decoder produced -- a dict for
        JSON-encoded messages, a dynamically created class instance for
        ROS1/ROS2 -- with no projection applied. Callers that want projected
        dictionary output use :py:meth:`next` and
        :py:meth:`DecodedMessage.to_dict` instead.

        A decoded value of ``None`` is a real message (a JSON ``null`` payload)
        and is delivered as such. Exhaustion is signaled with the dedicated
        :data:`END_OF_STREAM` sentinel instead, so callers must test ``result is
        END_OF_STREAM`` rather than ``result is None`` to detect the end.

        Returns:
            The decoded message value, or :data:`END_OF_STREAM` if no more
            messages are available.
        """
        next_decode_result = self.__next_unconsummed_decode_result
        self.__decode_next()
        if next_decode_result is None:
            return END_OF_STREAM
        return next_decode_result.decoded_message

    def next_message_is_time_aligned(self, timestamp: typing.Union[int, float]) -> bool:
        """Check if the next message has the specified timestamp.

        Used for time-aligned reading when merging data from multiple readers.

        Args:
            timestamp: Timestamp to check against in nanoseconds.

        Returns:
            True if the next message has the specified timestamp, False otherwise.
        """
        next_decode_result = self.__next_unconsummed_decode_result
        if next_decode_result is None:
            return False

        return next_decode_result.message.log_time == timestamp

    def __decode_next(self) -> None:
        # The omgidl decoder returns UNDECODABLE_MESSAGE for a message it cannot decode (an
        # unsupported wstring/wchar in a non-recoverable position) rather than raising, so a single
        # such message does not abort iteration over the rest of the file. Skip past those.
        while True:
            next_decode_result = next(self.__message_iterator, None)
            if next_decode_result is not None and next_decode_result.decoded_message is UNDECODABLE_MESSAGE:
                continue
            self.__next_unconsummed_decode_result = next_decode_result
            return
