# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MCAP decoder factory for msgpack-encoded messages.

Exposes an :py:class:`mcap.decoder.DecoderFactory` that decodes ``msgpack``
messages (typically described by a ``jsonschema`` schema), for use by
:py:class:`~roboto.formats.mcap.reader.McapReader`. Decoding is delegated to the
shared Rust decoder (the ``mcap_codec`` extension built from
``roboto-mcap-codec``), which returns nested ``dict`` / ``list`` / scalar values.

Known limitation: msgpack-numpy ndarray fields — nested maps with *binary* keys
(``nd``/``type``/``shape``/``data``), used by compressed-video packet payloads —
are silently dropped by the codec: the field decodes to an empty ``{}`` and the
payload bytes are unrecoverable downstream. Every other field of such a message
decodes normally. Tracked in
https://github.com/roboto-ai/roboto-mcap-codec/issues/5; until that lands,
consumers must treat non-``bytes`` payload fields as undecodable rather than
assume frame data is present.
"""

from __future__ import annotations

import logging
import typing

from mcap.decoder import DecoderFactory as McapDecoderFactory
from mcap.exceptions import McapError
from mcap.records import Schema

from .ros_cdr_decoder_factory import UNDECODABLE_MESSAGE

_logger = logging.getLogger(__name__)

# mcap.well_known.MessageEncoding has no member for msgpack; this is the
# channel message-encoding string our recorders write.
_MSGPACK = "msgpack"


class MsgpackDecodeError(McapError):
    """Raised when a ``msgpack`` message cannot be decoded."""


class MsgpackDecoderFactory(McapDecoderFactory):
    """Decode msgpack-encoded MCAP messages via the shared Rust ``mcap_codec`` decoder.

    Supply an instance to :py:func:`mcap.reader.make_reader`. The schema is
    parsed once per schema id; the returned callable then decodes each message
    into nested ``dict`` / ``list`` / scalar values.
    """

    def __init__(self) -> None:
        self._decoders: dict[int, typing.Callable[[bytes], typing.Any]] = {}

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        if message_encoding != _MSGPACK or schema is None:
            return None
        decoder = self._decoders.get(schema.id)
        if decoder is None:
            decoder = self._build_decoder(schema)
            self._decoders[schema.id] = decoder
        return decoder

    def _build_decoder(self, schema: Schema) -> typing.Callable[[bytes], typing.Any]:
        """Build a per-schema msgpack decoder backed by the shared Rust ``mcap_codec`` decoder."""
        # Imported lazily (rather than at module top) so the Rust extension only loads when a
        # msgpack channel is actually decoded; see the equivalent note in the omgidl factory.
        from mcap_codec import RosCdrCodec, UnsupportedMessage

        try:
            codec = RosCdrCodec(schema.encoding, _MSGPACK, schema.data, schema.name)
        except Exception as exc:
            # mcap calls decoder_for the first time it sees a schema; letting a parse failure
            # propagate would abort iteration over the entire file, including every other channel
            # that decodes fine. Mirror the omgidl factory: log once and return a decoder that
            # skips every message on this (unparseable) schema.
            _logger.warning(
                "msgpack schema %r could not be parsed (%s); skipping every message on this channel",
                schema.name,
                exc,
            )

            def decode_unparseable(_data: bytes) -> typing.Any:
                return UNDECODABLE_MESSAGE

            return decode_unparseable

        # Log the first skip per schema (not per message) so a file full of undecodable
        # messages doesn't flood the logs.
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
    """Build a decoder factory for msgpack-encoded messages, backed by the shared
    Rust ``mcap_codec`` decoder."""
    return MsgpackDecoderFactory()
