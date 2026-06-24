# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import functools
import json
import types
import typing

from mcap.decoder import (
    DecoderFactory as McapDecoderFactory,
)
from mcap.records import Schema
from mcap.well_known import MessageEncoding

from ...compat import import_optional_dependency


@functools.lru_cache(maxsize=1)
def _resolve_orjson() -> tuple[typing.Optional[types.ModuleType], typing.Optional[type[Exception]]]:
    """Resolve the optional ``orjson`` accelerator and its decode-error type, once.

    orjson ships in the ``analytics`` extra. It is resolved lazily on the first
    decode — like the other optional dependencies on this read path — so that
    importing this module never imports orjson; only an actual decode does. The
    import is best-effort (``errors="ignore"`` returns ``None`` when the extra is
    absent rather than the mandatory ``errors="raise"`` used where pandas/pyarrow
    are hard requirements), and callers fall back to the standard library ``json``
    module when it is ``None``. The result is memoized, keeping repeated
    resolution off the per-message decode hot path.

    Returns:
        A tuple of the ``orjson`` module and its ``JSONDecodeError`` type, or
        ``(None, None)`` when orjson is not installed.
    """
    module = import_optional_dependency("orjson", "analytics", errors="ignore")
    decode_error = module.JSONDecodeError if module is not None else None
    return module, decode_error


# The magnitude at or above which a JSON number that orjson decoded as a float
# may be a widened integer. orjson keeps integers in [-2**63, 2**64 - 1] exact
# and silently widens anything beyond that to float, whereas json.loads preserves
# arbitrary precision. Every widened integer has magnitude at least 2**63, so any
# float orjson returns below this magnitude is faithful and any at or above it is
# reparsed with json.loads to recover the exact value.
_WIDE_INT_FLOAT_MAGNITUDE = float(2**63)


def _has_widened_float(value: typing.Any) -> bool:
    """Report whether any float in ``value`` is large enough to be a widened integer.

    Walks the parsed structure iteratively, inspecting only floats — the sole
    type orjson can produce where it diverges from json.loads. The threshold is
    rarely met, so this is a cheap pass over already-parsed data rather than a
    scan of the raw payload bytes. A genuine float literal at or above the
    threshold is reparsed too, where json.loads yields the same float, so the
    only cost is a rarely taken slow path.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        kind = type(item)
        if kind is float:
            if item >= _WIDE_INT_FLOAT_MAGNITUDE or item <= -_WIDE_INT_FLOAT_MAGNITUDE:
                return True
        elif kind is dict:
            stack.extend(item.values())
        elif kind is list:
            stack.extend(item)
    return False


class JsonDecoderFactory(McapDecoderFactory):
    """Factory for creating JSON message decoders for MCAP readers.

    Provides functionality to decode JSON-encoded messages within MCAP files.
    This decoder factory is used by the MCAP reader to handle messages that
    were originally encoded in JSON format.
    """

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        """Create a decoder function for JSON-encoded messages.

        Returns a decoder function if the message encoding is JSON, otherwise returns None
        to indicate this factory cannot handle the encoding.

        Args:
            message_encoding: The encoding format of the message.
            schema: Optional schema information for the message.

        Returns:
            A decoder function for JSON messages, or None if the encoding is not JSON.

        Examples:
            >>> factory = JsonDecoderFactory()
            >>> decoder = factory.decoder_for(MessageEncoding.JSON, None)
            >>> if decoder:
            ...     decoded = decoder(b'{"x": 1.5, "y": 2.0}')
            ...     print(decoded)
            {'x': 1.5, 'y': 2.0}
        """
        if message_encoding != MessageEncoding.JSON:
            return None

        def decode(data: bytes) -> typing.Any:
            """Parse one JSON-encoded MCAP message payload into a Python object.

            Uses ``orjson`` when it is installed and falls back to the standard library
            ``json`` module otherwise. The two parsers produce identical Python objects
            for the standard JSON these payloads carry, with two divergences handled
            here so the result is never observably different from ``json.loads``:

            - ``orjson`` rejects the non-standard ``NaN``, ``Infinity``, and
              ``-Infinity`` tokens that ``json.loads`` accepts; on any ``orjson`` parse
              error the payload is reparsed with ``json.loads``.
            - ``orjson`` decodes integers outside ``[-2**63, 2**64 - 1]`` as floats,
              losing the precision ``json.loads`` keeps. When the parsed result carries a
              float large enough to be such a widened integer, the payload is reparsed
              with ``json.loads`` to recover the exact value.

            ``orjson`` parses the raw ``bytes`` directly, which is its fastest input
            form. The fallback decodes the same bytes to ``str`` before parsing.
            """
            orjson, orjson_decode_error = _resolve_orjson()
            if orjson is not None:
                try:
                    parsed = orjson.loads(data)
                except orjson_decode_error:  # type: ignore[misc]
                    return json.loads(data.decode())
                if not _has_widened_float(parsed):
                    return parsed
            return json.loads(data.decode())

        return decode
