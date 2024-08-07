# Copyright (c) 2024 Roboto Technologies, Inc.
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
    """Provides functionality to an mcap.reader.McapReader to decode Json messages."""

    def decoder_for(
        self, message_encoding: str, schema: typing.Optional[Schema]
    ) -> typing.Optional[typing.Callable[[bytes], typing.Any]]:
        if message_encoding != MessageEncoding.JSON:
            return None

        def decoder(data: bytes):
            deserialized = data.decode()
            return json.loads(deserialized)

        return decoder
