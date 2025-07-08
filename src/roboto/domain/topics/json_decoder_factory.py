# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import typing

from mcap.decoder import (
    DecoderFactory as McapDecoderFactory,
)
from mcap.records import Schema
from mcap.well_known import MessageEncoding


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

        def decoder(data: bytes):
            deserialized = data.decode()
            return json.loads(deserialized)

        return decoder
