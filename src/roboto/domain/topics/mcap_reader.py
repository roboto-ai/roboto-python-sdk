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
import mcap_ros2.decoder

from .decoded_message import DecodedMessage
from .json_decoder_factory import (
    JsonDecoderFactory,
)
from .record import MessagePathRecord


class McapReader:
    """Reader for processing MCAP files with message path filtering.

    Provides an iterator interface for reading decoded messages from MCAP files,
    with support for temporal filtering and message path selection. Handles
    multiple encoding formats including JSON, ROS1, and ROS2.

    The reader automatically decodes messages using appropriate decoders and
    filters the output based on the specified message paths and time range.
    """

    __message_iterator: typing.Iterator[mcap.reader.DecodedMessageTuple]
    __message_paths: collections.abc.Sequence[MessagePathRecord]
    __next_unconsummed_decode_result: mcap.reader.DecodedMessageTuple | None = None

    def __init__(
        self,
        stream: typing.IO[bytes],
        message_paths: collections.abc.Sequence[MessagePathRecord],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
    ):
        """Initialize the MCAP reader with filtering parameters.

        Args:
            stream: Binary stream containing MCAP data to read.
            message_paths: Sequence of message path records to filter for.
            start_time: Optional start time in nanoseconds for temporal filtering.
            end_time: Optional end time in nanoseconds for temporal filtering.

        Examples:
            >>> with open("data.mcap", "rb") as f:
            ...     reader = McapReader(f, message_paths, start_time=1000, end_time=2000)
            ...     while reader.has_next:
            ...         message = reader.next()
            ...         if message:
            ...             print(message.to_dict())
        """
        json_decoder = JsonDecoderFactory()
        ros1_decoder = mcap_ros1.decoder.DecoderFactory()
        ros2_decoder = mcap_ros2.decoder.DecoderFactory()
        reader = mcap.reader.make_reader(
            stream, decoder_factories=[json_decoder, ros1_decoder, ros2_decoder]
        )
        self.__message_iterator = reader.iter_decoded_messages(
            start_time=start_time, end_time=end_time
        )
        self.__message_paths = message_paths
        self.__decode_next()

    @property
    def has_next(self) -> bool:
        """Check if there are more messages available to read.

        Returns:
            True if there are more messages to read, False otherwise.
        """
        return self.__next_unconsummed_decode_result is not None

    @property
    def message_paths(self) -> list[str]:
        """Get the list of message paths being filtered for.

        Returns the message path strings from the MessagePathRecord objects
        that were provided during initialization.

        Returns:
            List of message path strings in dot notation from the configured MessagePathRecord objects.
        """
        return [mp.message_path for mp in self.__message_paths]

    @property
    def next_timestamp(self) -> typing.Union[int, float]:
        """Get the timestamp of the next message to be read.

        Returns:
            Timestamp of the next message in nanoseconds, or math.inf if no more messages.
        """
        if self.__next_unconsummed_decode_result is None:
            return math.inf

        return self.__next_unconsummed_decode_result.message.log_time

    def next(self) -> DecodedMessage | None:
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
                next_decode_result.decoded_message, self.__message_paths
            )
        return None

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
        next_decode_result = next(self.__message_iterator, None)
        self.__next_unconsummed_decode_result = next_decode_result
