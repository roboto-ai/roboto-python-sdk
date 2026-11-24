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

from .ros_cdr_decoder_factory import UNDECODABLE_MESSAGE

_logger = logging.getLogger(__name__)

# Channel message encoding of msgpack messages. mcap.well_known.MessageEncoding has no member for it.
_MSGPACK = "msgpack"


class MsgpackDecodeError(McapError):
    """A msgpack-encoded MCAP message could not be decoded.

    The function that ``MsgpackDecoderFactory.decoder_for`` returns raises it, so it surfaces while
    :py:class:`~roboto.formats.mcap.McapReader` reads a msgpack channel. A message with a field the decoder does not
    support is skipped instead, and does not raise it.
    """


class MsgpackDecoderFactory(McapDecoderFactory):
    """Decoder factory that decodes msgpack-encoded MCAP messages into nested dictionaries, lists, and scalar values.

    :py:class:`~roboto.formats.mcap.McapReader` decodes msgpack channels with it; to decode them with the ``mcap``
    library directly, pass an instance to ``mcap.reader.make_reader``. It decodes with the ``roboto-mcap-codec``
    package, and parses each schema once, then reuses the result for every message on that schema.

    It skips messages it cannot decode rather than stop the rest of the file being read: for each one, its decoder
    returns :py:const:`~roboto.formats.mcap.ros_cdr_decoder_factory.UNDECODABLE_MESSAGE`, which
    :py:class:`~roboto.formats.mcap.McapReader` passes over. It skips:

    - Every message on a schema it cannot parse.
    - Each message with a field the decoder does not support.

    In both cases it logs one warning per schema.

    Note:
        A field that msgpack-numpy encoded, a map with binary keys (``nd``, ``type``, ``shape``, ``data``) such as
        the payload of a compressed-video packet, decodes to an empty dictionary and its bytes are lost. The
        message's other fields decode normally. Treat a payload field that is not ``bytes`` as undecodable rather
        than assume it holds frame data.
    """

    def __init__(self) -> None:
        self._decoders: dict[int, typing.Callable[[bytes], typing.Any]] = {}

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        """Return a function that decodes messages on a msgpack channel with this schema.

        The ``mcap`` library's reader calls this when it decodes the first message on a channel.

        Args:
            message_encoding: Message encoding of the channel.
            schema: Schema of the channel, or ``None`` when the channel has none.

        Returns:
            Function that decodes one message's bytes, or ``None`` when ``message_encoding`` is not ``msgpack`` or
            ``schema`` is ``None``, so the ``mcap`` reader tries its other decoder factories.

        Raises:
            MsgpackDecodeError: A message cannot be decoded, for a reason other than a field the decoder does not
                support. Raised when the returned function is called.
        """
        if message_encoding != _MSGPACK or schema is None:
            return None
        decoder = self._decoders.get(schema.id)
        if decoder is None:
            decoder = self._build_decoder(schema)
            self._decoders[schema.id] = decoder
        return decoder

    def _build_decoder(self, schema: Schema) -> typing.Callable[[bytes], typing.Any]:
        # Imported here rather than at module top so the Rust extension loads only when a msgpack channel is decoded.
        from mcap_codec import RosCdrCodec, UnsupportedMessage

        try:
            codec = RosCdrCodec(schema.encoding, _MSGPACK, schema.data, schema.name)
        except Exception as exc:
            # mcap calls decoder_for when it decodes the first message on a channel, so any exception from parsing
            # the schema would stop the whole file being read, every other channel included. Catch it, log it, and
            # skip every message on this schema instead.
            _logger.warning(
                "msgpack schema %r could not be parsed (%s); skipping every message on this channel",
                schema.name,
                exc,
            )

            def decode_unparseable(_data: bytes) -> typing.Any:
                return UNDECODABLE_MESSAGE

            return decode_unparseable

        # Warn on the first skipped message of the schema only, so a file of undecodable messages logs one warning.
        skip_logged = [False]

        def decode(data: bytes) -> typing.Any:
            try:
                return codec.decode(data)
            except UnsupportedMessage as exc:
                if not skip_logged[0]:
                    skip_logged[0] = True
                    _logger.warning(
                        "msgpack schema %r has a field the decoder does not support (%s); "
                        "skipping the affected messages",
                        schema.name,
                        exc,
                    )
                return UNDECODABLE_MESSAGE
            except Exception as exc:
                raise MsgpackDecodeError(f"failed to decode message on schema {schema.name!r}: {exc}") from exc

        return decode


def make_msgpack_decoder_factory() -> MsgpackDecoderFactory:
    """Build a decoder factory for msgpack-encoded MCAP messages.

    :py:class:`~roboto.formats.mcap.McapReader` decodes msgpack channels through it, so most code never calls it.
    ``MsgpackDecoderFactory()`` builds the same factory.
    """
    return MsgpackDecoderFactory()
