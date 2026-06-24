# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Format-specific decoding of topic data files into rows.

This package decodes MCAP and Parquet topic data into Roboto's nested row /
Arrow representation: per-format parsing and read planning, field projection,
and timestamp extraction. The byte-transport it builds on (HTTP range reads,
local disk caching, sparse buffering) lives in ``roboto.storage``; this package
depends on the topic record and message-path types in ``roboto.domain.topics``
without depending back on the topic readers, so the readers in both
``roboto.domain.topics`` and ``roboto.experimental.topics`` build on it.
"""

from .fields import FieldSelection

__all__ = ("FieldSelection",)
