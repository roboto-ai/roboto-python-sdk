# Copyright (c) 2024 Roboto Technologies, Inc.
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
        return self.__next_unconsummed_decode_result is not None

    @property
    def next_timestamp(self) -> typing.Union[int, float]:
        if self.__next_unconsummed_decode_result is None:
            return math.inf

        return self.__next_unconsummed_decode_result.message.log_time

    def next(self) -> DecodedMessage | None:
        next_decode_result = self.__next_unconsummed_decode_result
        self.__decode_next()

        if next_decode_result is not None:
            return DecodedMessage(
                next_decode_result.decoded_message, self.__message_paths
            )
        return None

    def next_message_is_time_aligned(self, timestamp: typing.Union[int, float]) -> bool:
        next_decode_result = self.__next_unconsummed_decode_result
        if next_decode_result is None:
            return False

        return next_decode_result.message.log_time == timestamp

    def __decode_next(self) -> None:
        next_decode_result = next(self.__message_iterator, None)
        self.__next_unconsummed_decode_result = next_decode_result
