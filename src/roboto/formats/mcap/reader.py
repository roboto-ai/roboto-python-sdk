# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import math
import typing

import mcap.reader

from ...exceptions import RobotoInternalException
from ..fields import FieldSelection
from .accessor import AccessorCache
from .decoded_message import DecodedMessage
from .json_decoder_factory import (
    JsonDecoderFactory,
)
from .msgpack_decoder_factory import make_msgpack_decoder_factory
from .ros_cdr_decoder_factory import (
    UNDECODABLE_MESSAGE,
    make_ros_cdr_codec_decoder_factory,
)


class _EndOfStream:
    """Type of ``END_OF_STREAM``: one instance, compared with ``is``, with a readable ``repr`` in test output."""

    _instance: typing.Optional["_EndOfStream"] = None

    def __new__(cls) -> "_EndOfStream":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "END_OF_STREAM"


END_OF_STREAM = _EndOfStream()
"""Value ``McapReader.next_decoded`` returns in place of a message once the reader has no more messages.

A message can decode to ``None``, such as a JSON ``null`` payload, so ``None`` cannot mark the end.
"""


class McapEnvelopeTimestamp(typing.NamedTuple):
    """Log time and publish time of an MCAP message, as ``McapReader.next_envelope_timestamp`` returns them."""

    log_time: typing.Union[int, float]
    """Time the message was recorded, in nanoseconds."""

    publish_time: typing.Union[int, float]
    """Time the message's producer published it, in nanoseconds."""


class McapReader:
    """Reader that decodes the messages of an MCAP stream and keeps only selected fields.

    Reads the messages whose log time falls in a time range and, optionally, that are on one topic. Decodes messages
    encoded as JSON, msgpack, ROS 1, or CDR (ROS 2 and OMG IDL schemas), and skips a ROS 1 or CDR message it cannot
    decode.

    Args:
        stream: Binary stream of the MCAP data to read.
        fields: Fields to keep in each message ``next`` returns.
        start_time: Inclusive start of the log-time range, in nanoseconds. ``None`` starts at the first message.
        end_time: Exclusive end of the log-time range, in nanoseconds. ``None`` reads to the last message.
        log_time_order: Whether to return messages in log-time order. ``False`` returns them in the order the file
            stores them, which avoids sorting messages across chunks, and still applies the time range. Pass ``False``
            only when message order does not matter; code that merges readers by log time needs ``True``.
        topic_name: Topic to read the messages of. ``None`` reads every topic. Messages on every MCAP channel of the
            topic are read.

    Raises:
        RobotoInternalException: ``topic_name`` is given and the file's summary section lists no channel on that
            topic. A stream that cannot seek, or a file with no summary section, is not checked.
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
        topic_name: typing.Optional[str] = None,
    ):
        # JSON channels use their own decoder, so messages decode as json.loads decodes them: None for a null field,
        # lists for arrays, and integers of any size.
        json_decoder = JsonDecoderFactory()
        msgpack_decoder = make_msgpack_decoder_factory()
        ros_cdr_codec_decoder = make_ros_cdr_codec_decoder_factory()
        reader = mcap.reader.make_reader(
            stream,
            decoder_factories=[json_decoder, msgpack_decoder, ros_cdr_codec_decoder],
        )
        if topic_name is not None:
            _raise_if_summary_lists_no_channel_on_topic(reader, topic_name)
        self.__message_iterator = reader.iter_decoded_messages(
            topics=[topic_name] if topic_name is not None else None,
            start_time=start_time,
            end_time=end_time,
            log_time_order=log_time_order,
        )
        self.__fields = fields
        self.__accessor_cache = AccessorCache()
        self.__decode_next()

    @property
    def has_next(self) -> bool:
        """Whether the reader has another message to return."""
        return self.__next_unconsummed_decode_result is not None

    @property
    def field_paths(self) -> list[tuple[str, ...]]:
        """Path through the schema of each selected field, in the order of ``fields``.

        Each path is the field's :py:attr:`~roboto.formats.FieldSelection.path_in_schema`.
        """
        return [field.path_in_schema for field in self.__fields]

    @property
    def next_envelope_timestamp(self) -> McapEnvelopeTimestamp:
        """Log time and publish time of the next message, both ``math.inf`` once the reader has no more messages.

        Since ``math.inf`` is greater than every timestamp, code that merges readers by taking the smallest next log
        time never picks an exhausted reader.
        """
        if self.__next_unconsummed_decode_result is None:
            return McapEnvelopeTimestamp(log_time=math.inf, publish_time=math.inf)

        message = self.__next_unconsummed_decode_result.message
        return McapEnvelopeTimestamp(log_time=message.log_time, publish_time=message.publish_time)

    def next(self) -> typing.Union[DecodedMessage, None]:
        """Return the next message, keeping only the selected fields, and advance the reader.

        Returns:
            The next message, or ``None`` once the reader has no more messages.

        Examples:
            >>> from roboto.formats import FieldSelection
            >>> from roboto.formats.mcap import McapReader
            >>> with open("data.mcap", "rb") as f:
            ...     reader = McapReader(f, [FieldSelection(("position", "x"))], topic_name="/pose")
            ...     while reader.has_next:
            ...         message = reader.next()
            ...         print(message.to_dict())
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
        """Return the next message as its decoder produced it, with every field, and advance the reader.

        The value is nested dictionaries, sequences, and scalars. To keep only the selected fields, use ``next`` and
        :py:meth:`~roboto.formats.mcap.decoded_message.DecodedMessage.to_dict` instead.

        Returns:
            The decoded message, or ``END_OF_STREAM`` once the reader has no more messages. A message can decode to
            ``None``, so test ``result is END_OF_STREAM``, not ``result is None``, to detect the end.
        """
        next_decode_result = self.__next_unconsummed_decode_result
        self.__decode_next()
        if next_decode_result is None:
            return END_OF_STREAM
        return next_decode_result.decoded_message

    def next_message_is_time_aligned(self, timestamp: typing.Union[int, float]) -> bool:
        """Return whether the next message's log time equals ``timestamp``.

        Code that merges several readers by log time uses it to find the readers whose next message has the earliest
        log time. Returns ``False`` once the reader has no more messages.

        Args:
            timestamp: Log time to compare with, in nanoseconds.
        """
        next_decode_result = self.__next_unconsummed_decode_result
        if next_decode_result is None:
            return False

        return next_decode_result.message.log_time == timestamp

    def __decode_next(self) -> None:
        # The ROS 1 and CDR decoder returns UNDECODABLE_MESSAGE, instead of raising, for a message it cannot decode, so
        # that one such message does not end the read. Skip each one.
        while True:
            next_decode_result = next(self.__message_iterator, None)
            if next_decode_result is not None and next_decode_result.decoded_message is UNDECODABLE_MESSAGE:
                continue
            self.__next_unconsummed_decode_result = next_decode_result
            return


def _raise_if_summary_lists_no_channel_on_topic(reader: mcap.reader.McapReader, topic_name: str) -> None:
    """Reject ``topic_name`` when the file's summary section lists no MCAP channel on it.

    Checks only a seekable reader, because reading a non-seekable reader's summary consumes the stream. A file with no
    summary section is not checked, because its channels are known only by reading it to the end.

    Raises:
        RobotoInternalException: The summary lists no channel on ``topic_name``.
    """
    if not isinstance(reader, mcap.reader.SeekingReader):
        return
    summary = reader.get_summary()
    if summary is None:
        return
    if any(channel.topic == topic_name for channel in summary.channels.values()):
        return
    raise RobotoInternalException(f"MCAP file has no channel on topic {topic_name!r}")
