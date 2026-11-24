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
    """Return the ``orjson`` module and its ``JSONDecodeError``, or ``(None, None)`` when it is not installed.

    ``orjson`` ships in the ``analytics`` extra. It is looked up on the first decode rather than at import, so importing
    this module never imports ``orjson``, and the result is cached so later decodes skip the lookup.
    """
    module = import_optional_dependency("orjson", "analytics", errors="ignore")
    decode_error = module.JSONDecodeError if module is not None else None
    return module, decode_error


# Magnitude at or above which a float from orjson may be a widened integer. orjson decodes integers in
# [-2**63, 2**64 - 1] exactly and silently widens any outside that range to float, while json.loads keeps every
# integer exact. Every widened integer has a magnitude of at least 2**63, so a float below this magnitude matches what
# json.loads returns, and the payload of one at or above it is reparsed with json.loads.
_WIDE_INT_FLOAT_MAGNITUDE = float(2**63)


def _has_widened_float(value: typing.Any) -> bool:
    """Return whether any float in ``value`` is large enough to be an integer ``orjson`` widened.

    Only floats are checked, since they are the only parsed values where ``orjson`` and ``json.loads`` can differ. A
    float literal at or above the threshold also returns ``True``; reparsing it with ``json.loads`` yields the same
    float.
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
    """Decoder factory that decodes JSON-encoded MCAP messages to the Python objects ``json.loads`` returns.

    The SDK's own code uses it; to read messages from an MCAP file, use :py:class:`~roboto.formats.mcap.McapReader`
    instead. Decoding uses ``orjson`` when the ``analytics`` extra installs it, and the standard library ``json`` module
    otherwise. The result is the same either way, including for the non-standard ``NaN``, ``Infinity``, and
    ``-Infinity`` tokens and for integers of any size.
    """

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        """Build a function that decodes one JSON-encoded message, or return ``None`` for any other encoding.

        The ``mcap`` library's reader calls this to get a decoder for a channel's messages.

        Args:
            message_encoding: Message encoding of the channel. Only ``json`` gets a decoder.
            schema: Ignored. JSON messages decode without a schema.

        Raises:
            json.JSONDecodeError: A message is not valid JSON. Raised when the returned function is called.
            UnicodeDecodeError: A message is not valid UTF-8. Raised when the returned function is called.
        """
        if message_encoding != MessageEncoding.JSON:
            return None

        def decode(data: bytes) -> typing.Any:
            """Parse one message payload, returning what ``json.loads`` returns for it.

            ``orjson``, when installed, parses the bytes directly. Two cases fall back to ``json.loads`` on the
            decoded string:

            - ``orjson`` rejects the payload, as it rejects the ``NaN``, ``Infinity``, and ``-Infinity`` tokens that
              ``json.loads`` accepts.
            - The result holds a float large enough to be an integer outside ``[-2**63, 2**64 - 1]``, which ``orjson``
              widens to a float and ``json.loads`` keeps exact.
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
