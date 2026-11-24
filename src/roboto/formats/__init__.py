# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Decoding of topic data stored in MCAP and Parquet files, reading only the fields a caller selects.

:py:class:`~roboto.formats.FieldSelection` names a field to read by its path through a file's schema. To read the
selected fields from MCAP files, use :py:mod:`~roboto.formats.mcap`; to read them from Parquet files, use
:py:mod:`~roboto.formats.parquet`. Methods such as :py:meth:`~roboto.domain.topics.Topic.get_data` and
:py:meth:`~roboto.domain.topics.MessagePath.get_data` read topic data through this package, so most code never calls
it.
"""

from .fields import FieldSelection

__all__ = ("FieldSelection",)
