# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Decoding of OMG IDL (``omgidl`` / ``ros2idl``) CDR messages from MCAP files.

Robotics data recorded directly from DDS (e.g. RTI Connext) carries OMG IDL schemas and
CDR payloads that mix plain CDR with XCDR1- and XCDR2-mutable extensibility. This package
provides an :py:class:`mcap.decoder.DecoderFactory` that decodes all of those variants,
for use by :py:class:`~roboto.formats.mcap.reader.McapReader`.
"""

from .decoder_factory import (
    OmgidlDecodeError,
    OmgidlDecoderFactory,
    make_omgidl_decoder_factory,
)

__all__ = [
    "OmgidlDecodeError",
    "OmgidlDecoderFactory",
    "make_omgidl_decoder_factory",
]
