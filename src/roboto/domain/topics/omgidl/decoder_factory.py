# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MCAP decoder factory for ``omgidl`` and ``ros2idl`` schemas.

Exposes an :py:class:`mcap.decoder.DecoderFactory` that decodes CDR messages whose
schema is OMG IDL (``omgidl`` / ``ros2idl``), for use by
:py:class:`~roboto.domain.topics.mcap_reader.McapReader`. Decoding is delegated to
the shared Rust decoder (the ``mcap_codec`` extension built from ``roboto-mcap-codec``
-- the same decoder the ingestion action uses), which parses the schema and decodes
every CDR framing (plain XCDR1/XCDR2 and the parameter-list ``PL_CDR``/``PL_CDR2``
families) into nested ``dict`` / sequence / scalar values. Numeric arrays and sequences
come back as the compact :py:class:`array.array` (one C buffer rather than a list of
boxed Python objects) and octet sequences as ``bytes``; nested/heterogeneous sequences
(arrays of structs, arrays of sequences, the outer dimension of a multidimensional array)
are plain ``list``. This mirrors the ROS2 decoder, which likewise returns ``bytes`` for
``uint8``/octet arrays. Callers that need JSON-serializable output (``array.array`` and
``bytes`` are not JSON-native) should convert at the edge, e.g. via ``array.tolist()``.
"""

from __future__ import annotations

import logging
import typing

from mcap.decoder import DecoderFactory as McapDecoderFactory
from mcap.exceptions import McapError
from mcap.records import Schema
from mcap.well_known import MessageEncoding

_logger = logging.getLogger(__name__)

_OMGIDL = "omgidl"
_ROS2IDL = "ros2idl"


class _UndecodableMessage:
    """Sentinel returned (instead of raising) for a message that cannot be decoded but should not
    abort iteration over the rest of the file.

    Used when a message's type involves a field with no well-defined CDR encoding
    (implementation-dependent ``wstring`` / ``wchar``) or member ids the decoder cannot compute
    (HASH autoid). Returning this keeps mcap's decode generator alive so
    :py:class:`~roboto.domain.topics.mcap_reader.McapReader` can skip the message and continue
    reading every other topic.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<omgidl: undecodable message>"


UNDECODABLE_MESSAGE = _UndecodableMessage()


class OmgidlDecodeError(McapError):
    """Raised when an ``omgidl`` / ``ros2idl`` message cannot be decoded."""


class OmgidlDecoderFactory(McapDecoderFactory):
    """Decode CDR messages described by ``omgidl`` or ``ros2idl`` schemas.

    Supply an instance to :py:func:`mcap.reader.make_reader`. The schema is parsed once per
    schema id (by the shared Rust ``mcap_codec`` decoder); the returned callable then decodes
    each message into nested ``dict`` / sequence / scalar values -- numeric arrays/sequences as
    :py:class:`array.array`, octet sequences as ``bytes``, and nested/heterogeneous sequences as
    ``list`` (see the module docstring).
    """

    def __init__(self) -> None:
        self._decoders: dict[int, typing.Callable[[bytes], typing.Any]] = {}

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        if message_encoding != MessageEncoding.CDR or schema is None or schema.encoding not in (_OMGIDL, _ROS2IDL):
            return None
        decoder = self._decoders.get(schema.id)
        if decoder is None:
            decoder = self._build_decoder(schema)
            self._decoders[schema.id] = decoder
        return decoder

    def _build_decoder(self, schema: Schema) -> typing.Callable[[bytes], typing.Any]:
        """Build a per-schema decoder backed by the shared Rust ``mcap_codec`` decoder.

        ``mcap_codec`` performs its own ``ros2idl`` framing strip and ``/``→``::`` name
        normalization, so the raw schema bytes/name/encoding pass through unchanged. Its output
        is nested ``dict`` / sequence / scalars: numeric arrays/sequences as ``array.array``,
        octet sequences as ``bytes``, nested/heterogeneous sequences as ``list``, enums as ints,
        unions as ``{"discriminator", <active arm>}``, ``Time`` as ``{"sec", "nanosec"}``, absent
        ``@optional`` members omitted.
        """
        # Imported lazily (rather than at module top) so the Rust extension only loads when an
        # omgidl/ros2idl schema is actually decoded. roboto-mcap-codec is a hard dependency, so on
        # any platform where `import roboto` succeeds this import does too; a bare ImportError here
        # means a broken install, which its own message describes better than we could.
        from mcap_codec import CdrCodec, UnsupportedMessage

        try:
            codec = CdrCodec(schema.encoding, schema.data, schema.name)
        except Exception as exc:
            # mcap calls decoder_for the first time it sees a schema; letting a parse failure
            # propagate would abort iteration over the entire file, including every other channel
            # that decodes fine. Instead, mirror the per-message UNDECODABLE_MESSAGE behavior: log
            # once and return a decoder that skips every message on this (unparseable) schema.
            _logger.warning(
                "omgidl schema %r could not be parsed (%s); skipping every message on this channel",
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
                        "omgidl schema %r has a field whose CDR encoding is not well-defined (%s); "
                        "skipping the affected messages",
                        schema.name,
                        exc,
                    )
                return UNDECODABLE_MESSAGE
            except Exception as exc:
                raise OmgidlDecodeError(f"failed to decode message on schema {schema.name!r}: {exc}") from exc

        return decode


def make_omgidl_decoder_factory() -> OmgidlDecoderFactory:
    """Build a decoder factory for ``omgidl`` / ``ros2idl`` CDR messages, backed by the shared
    Rust ``mcap_codec`` decoder."""
    return OmgidlDecoderFactory()
