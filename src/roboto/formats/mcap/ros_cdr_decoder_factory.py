# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
import typing

from mcap.decoder import DecoderFactory as McapDecoderFactory
from mcap.exceptions import McapError
from mcap.records import Schema
from mcap.well_known import MessageEncoding

_logger = logging.getLogger(__name__)

# Schema encodings carried on channels whose message encoding is "cdr". DDS recordings carry "omgidl", although
# the mcap package's well-known SchemaEncoding enum has no member for it.
_CDR_SCHEMA_ENCODINGS = frozenset({"omgidl", "ros2idl", "ros2msg"})
# Schema encoding carried on channels whose message encoding is "ros1".
_ROS1_SCHEMA_ENCODING = "ros1msg"


class _UndecodableMessage:
    """Type of ``UNDECODABLE_MESSAGE``, whose one instance no decoded message can equal."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<ros_cdr_codec: undecodable message>"


UNDECODABLE_MESSAGE = _UndecodableMessage()
"""Value a decoder returns in place of a message it cannot decode, so that reading continues with the next message.

:py:class:`~roboto.formats.mcap.McapReader` skips every message that decodes to it. The ROS 1, CDR, and msgpack
decoders return it for a message whose schema has a field they do not support, and for every message on a channel
whose schema they cannot parse.
"""


class RosCdrCodecDecodeError(McapError):
    """A ROS 1 or CDR message could not be decoded.

    Raised by the decoders that ``RosCdrCodecDecoderFactory.decoder_for`` returns, for any failure other than a field
    the decoder does not support, which skips the message instead. It surfaces from
    :py:class:`~roboto.formats.mcap.McapReader` when the reader reaches the message.
    """


class RosCdrCodecDecoderFactory(McapDecoderFactory):
    """Decoder factory that decodes ROS 1 and CDR messages in MCAP files.

    It decodes channels whose message encoding is ``cdr`` and whose schema encoding is ``ros2msg``, ``ros2idl``, or
    ``omgidl``, and channels whose message encoding is ``ros1`` and whose schema encoding is ``ros1msg``. Pass an
    instance to ``mcap.reader.make_reader`` in its ``decoder_factories``. Decoding runs in the Rust ``mcap_codec``
    extension, from the ``roboto-mcap-codec`` package, which parses each schema once.

    Each message decodes to a ``dict`` keyed by member name, with values shaped as follows:

    - Numeric arrays and sequences, ``uint8`` and octet sequences included: ``array.array``.
    - Sequences of structs or of sequences, and the outer dimension of a multidimensional array: ``list``.
    - Enums: ``int``.
    - Unions: ``{"$discriminator": <discriminator>, <active member>: <value>}``.
    - ``Time`` and ``Duration``: a ``dict`` with the schema's own member names, ``sec`` and ``nanosec`` in ROS 2 and
      ``sec`` and ``nsec`` in ROS 1.
    - An absent ``@optional`` member: left out of the ``dict``.

    ``array.array`` is not JSON-serializable; convert one with its ``tolist()`` method before serializing. JSON
    channels decode through :py:class:`~roboto.formats.mcap.json_decoder_factory.JsonDecoderFactory` instead, which
    returns what ``json.loads`` does: ``None`` for null fields, plain lists, and integers of any size.

    A message the decoder cannot decode because of its schema, such as a ``wstring`` member in a plain CDR struct or
    a struct marked ``@autoid(HASH)``, decodes to ``UNDECODABLE_MESSAGE``, as does every message on a channel whose
    schema cannot be parsed.
    """

    def __init__(self) -> None:
        self._decoders: dict[int, typing.Callable[[bytes], typing.Any]] = {}

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        """Return the decoder for a channel's messages, or ``None`` if this factory does not decode them.

        The ``mcap`` reader calls this for each channel it reads. A channel whose pair of message and schema encodings
        this class does not decode returns ``None``, so that another factory can decode it. The decoder is built on
        the first call for a schema ID and reused afterward.

        Args:
            message_encoding: Message encoding of the channel, such as ``cdr`` or ``ros1``.
            schema: Schema of the channel. ``None`` returns ``None``.

        Returns:
            Function that decodes one message's bytes, and returns the decoded ``dict`` or ``UNDECODABLE_MESSAGE``.

        Raises:
            RosCdrCodecDecodeError: The message cannot be decoded for a reason other than a field the decoder does not
                support. Raised when the returned function is called.
        """
        if schema is None or not self._handles(message_encoding, schema.encoding):
            return None
        decoder = self._decoders.get(schema.id)
        if decoder is None:
            decoder = self._build_decoder(message_encoding, schema)
            self._decoders[schema.id] = decoder
        return decoder

    @staticmethod
    def _handles(message_encoding: str, schema_encoding: str) -> bool:
        """Return whether this factory decodes channels with this pair of message and schema encodings.

        Checking the pair, not either encoding alone, leaves a mismatched channel, such as a ``ros1msg`` schema on a
        ``cdr`` channel, to another factory instead of decoding it wrongly.
        """
        if message_encoding == MessageEncoding.CDR:
            return schema_encoding in _CDR_SCHEMA_ENCODINGS
        if message_encoding == MessageEncoding.ROS1:
            return schema_encoding == _ROS1_SCHEMA_ENCODING
        return False

    def _build_decoder(self, message_encoding: str, schema: Schema) -> typing.Callable[[bytes], typing.Any]:
        """Build the decoder for one schema.

        The codec needs ``message_encoding`` as well as the schema, because a ``cdr`` channel can carry any of three
        schema encodings. The codec strips ``ros2idl`` framing and converts ``/`` to ``::`` in type names itself, so
        the schema passes to it unchanged.
        """
        # Imported here so the Rust extension loads only when a ROS 1 or CDR schema is decoded. roboto-mcap-codec is a
        # required dependency of the SDK, so this import fails only on a broken install, and the ImportError says why.
        from mcap_codec import RosCdrCodec, UnsupportedMessage

        try:
            codec = RosCdrCodec(schema.encoding, message_encoding, schema.data, schema.name)
        except Exception as exc:
            # Catches every exception from parsing the schema. The mcap reader calls decoder_for as it reaches each
            # schema, so a parse failure raised here would end the read of the whole file, every other channel
            # included. Log once instead, and decode every message on this channel to UNDECODABLE_MESSAGE.
            _logger.warning(
                "%s schema %r could not be parsed (%s); skipping every message on this channel",
                schema.encoding,
                schema.name,
                exc,
            )

            def decode_unparseable(_data: bytes) -> typing.Any:
                return UNDECODABLE_MESSAGE

            return decode_unparseable

        # Log only the first skipped message per schema, so a file full of them does not flood the log.
        skip_logged = [False]

        def decode(data: bytes) -> typing.Any:
            try:
                return codec.decode(data)
            except UnsupportedMessage as exc:
                # The message has a field with no well-defined CDR encoding (wstring, wchar) that the codec cannot
                # skip, or member IDs hashed from member names (@autoid(HASH)). Skip the message and keep reading.
                if not skip_logged[0]:
                    skip_logged[0] = True
                    _logger.warning(
                        "%s schema %r has a field whose CDR encoding is not well-defined (%s); "
                        "skipping the affected messages",
                        schema.encoding,
                        schema.name,
                        exc,
                    )
                return UNDECODABLE_MESSAGE
            except Exception as exc:
                raise RosCdrCodecDecodeError(f"failed to decode message on schema {schema.name!r}: {exc}") from exc

        return decode


def make_ros_cdr_codec_decoder_factory() -> RosCdrCodecDecoderFactory:
    """Build a decoder factory for ROS 1 and CDR messages, as ``RosCdrCodecDecoderFactory`` describes.

    :py:class:`~roboto.formats.mcap.McapReader` decodes ROS 1 and CDR channels through it, so most code never calls it.
    """
    return RosCdrCodecDecoderFactory()
