# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MCAP decoder factory for the whole ROS / CDR message family.

Exposes an :py:class:`mcap.decoder.DecoderFactory` that decodes every ROS-flavored
binary message Roboto reads -- ``ros1msg`` (the unaligned ROS1 wire) and the CDR
schema languages ``ros2msg`` / ``ros2idl`` / ``omgidl`` -- by delegating to the
shared Rust decoder (the ``mcap_codec`` extension built from ``roboto-mcap-codec``,
the same decoder the ingestion action uses). One factory backs them all because
``RosCdrCodec`` dispatches internally on the schema encoding, so a decode fix lands
once and benefits every encoding (and ingest stats) together.

The decoder parses the schema once per schema id and decodes each payload into nested
``dict`` / sequence / scalar values: numeric arrays and sequences -- including
octet/``uint8`` sequences -- come back as the compact :py:class:`array.array` (one C
buffer rather than a list of boxed Python objects); nested/heterogeneous sequences
(arrays of structs, arrays of sequences, the outer dimension of a multidimensional
array) are plain ``list``; enums are ``int``; unions are
``{"$discriminator", <active arm>}``; ``Time`` / ``Duration`` members surface with
their schema-verbatim names (ROS2 ``{"sec", "nanosec"}``, ROS1 ``{"sec", "nsec"}``); and
absent ``@optional`` members are omitted. This ``dict`` representation is what
:py:mod:`roboto.formats.mcap.accessor` walks, so the same projection machinery serves
every encoding. Callers that need JSON-serializable output (``array.array`` is not
JSON-native) should convert at the edge, e.g. via ``array.tolist()``.

JSON channels are not handled here.
They keep their own :py:class:`~roboto.formats.mcap.json_decoder_factory.JsonDecoderFactory`,
which preserves ``json.loads`` semantics (``None`` for null fields, plain lists, arbitrary-precision ints)
where this decoder's materialization is deliberately CDR-shaped.
"""

from __future__ import annotations

import logging
import typing

from mcap.decoder import DecoderFactory as McapDecoderFactory
from mcap.exceptions import McapError
from mcap.records import Schema
from mcap.well_known import MessageEncoding

_logger = logging.getLogger(__name__)

# CDR-framed schema encodings (message_encoding == "cdr"). "omgidl" is a real wire
# value DDS files carry even though the mcap well-known SchemaEncoding enum omits it.
_CDR_SCHEMA_ENCODINGS = frozenset({"omgidl", "ros2idl", "ros2msg"})
# The ROS1 wire (message_encoding == "ros1") carries a "ros1msg" schema.
_ROS1_SCHEMA_ENCODING = "ros1msg"


class _UndecodableMessage:
    """Sentinel returned (instead of raising) for a message that cannot be decoded but should not
    abort iteration over the rest of the file.

    Used when a message's type involves a field with no well-defined CDR encoding
    (implementation-dependent ``wstring`` / ``wchar``) or member ids the decoder cannot compute
    (HASH autoid). Returning this keeps mcap's decode generator alive so
    :py:class:`~roboto.formats.mcap.reader.McapReader` can skip the message and continue
    reading every other topic.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<ros_cdr_codec: undecodable message>"


UNDECODABLE_MESSAGE = _UndecodableMessage()


class RosCdrCodecDecodeError(McapError):
    """Raised when a ROS / CDR message cannot be decoded."""


class RosCdrCodecDecoderFactory(McapDecoderFactory):
    """Decode ROS / CDR messages (``ros1msg`` / ``ros2msg`` / ``ros2idl`` / ``omgidl``).

    Supply an instance to :py:func:`mcap.reader.make_reader`. The schema is parsed once per
    schema id (by the shared Rust ``mcap_codec`` decoder); the returned callable then decodes
    each message into nested ``dict`` / sequence / scalar values -- numeric arrays/sequences
    (including octet/``uint8``) as :py:class:`array.array`, and nested/heterogeneous sequences as
    ``list`` (see the module docstring).
    """

    def __init__(self) -> None:
        self._decoders: dict[int, typing.Callable[[bytes], typing.Any]] = {}

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        if schema is None or not self._handles(message_encoding, schema.encoding):
            return None
        decoder = self._decoders.get(schema.id)
        if decoder is None:
            decoder = self._build_decoder(message_encoding, schema)
            self._decoders[schema.id] = decoder
        return decoder

    @staticmethod
    def _handles(message_encoding: str, schema_encoding: str) -> bool:
        """Whether this factory owns the given ``(message_encoding, schema_encoding)`` pair.

        CDR framing (``cdr``) carries ``omgidl`` / ``ros2idl`` / ``ros2msg``; the ROS1 wire
        (``ros1``) carries ``ros1msg``. The two are paired so an unexpected combination (e.g. a
        ``ros1msg`` schema on a ``cdr`` channel) is declined here and falls through to another
        factory rather than being mis-decoded.
        """
        if message_encoding == MessageEncoding.CDR:
            return schema_encoding in _CDR_SCHEMA_ENCODINGS
        if message_encoding == MessageEncoding.ROS1:
            return schema_encoding == _ROS1_SCHEMA_ENCODING
        return False

    def _build_decoder(self, message_encoding: str, schema: Schema) -> typing.Callable[[bytes], typing.Any]:
        """Build a per-schema decoder backed by the shared Rust ``mcap_codec`` decoder.

        ``message_encoding`` (the channel's wire framing, ``cdr`` or ``ros1``) selects how the
        codec reads the payload bytes; it pairs with ``schema.encoding`` and cannot be inferred
        from the schema alone (the same CDR framing carries several schema languages).

        ``mcap_codec`` performs its own ``ros2idl`` framing strip and ``/``->``::`` name
        normalization, so the raw schema bytes/name/encoding pass through unchanged. Its output
        is nested ``dict`` / sequence / scalars: numeric arrays/sequences (including
        octet/``uint8``) as ``array.array``, nested/heterogeneous sequences as ``list``, enums as
        ints, unions as ``{"$discriminator", <active arm>}``, ``Time`` / ``Duration`` with their
        schema-verbatim member names (ROS2 ``nanosec``, ROS1 ``nsec``), absent ``@optional``
        members omitted.
        """
        # Imported lazily (rather than at module top) so the Rust extension only loads when a
        # ROS/CDR schema is actually decoded. roboto-mcap-codec is a hard dependency, so on any
        # platform where `import roboto` succeeds this import does too; a bare ImportError here
        # means a broken install, which its own message describes better than we could.
        from mcap_codec import RosCdrCodec, UnsupportedMessage

        try:
            codec = RosCdrCodec(schema.encoding, message_encoding, schema.data, schema.name)
        except Exception as exc:
            # mcap calls decoder_for the first time it sees a schema; letting a parse failure
            # propagate would abort iteration over the entire file, including every other channel
            # that decodes fine. Instead, mirror the per-message UNDECODABLE_MESSAGE behavior: log
            # once and return a decoder that skips every message on this (unparseable) schema.
            _logger.warning(
                "%s schema %r could not be parsed (%s); skipping every message on this channel",
                schema.encoding,
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
                # The message has a field with no well-defined CDR encoding (e.g. wstring) or
                # member ids the decoder cannot compute (HASH autoid): skip this message, keep
                # reading the file.
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
    """Build a decoder factory for the ROS / CDR family, backed by the shared Rust ``mcap_codec`` decoder.

    Handles ``ros1msg`` / ``ros2msg`` / ``ros2idl`` / ``omgidl`` schemas; see
    :py:class:`RosCdrCodecDecoderFactory`.
    """
    return RosCdrCodecDecoderFactory()
