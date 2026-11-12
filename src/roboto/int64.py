# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bounds of the signed 64-bit integers that hold Roboto's nanosecond timestamps, timeline offsets, and row positions.

Roboto cannot store a nanosecond timestamp, timeline offset, or row position outside ``[INT64_MIN, INT64_MAX]``. Many
fields accept only part of this range; a file's timeline offset, for example, must not be negative.
"""

INT64_MIN = -(2**63)
"""The smallest value a signed 64-bit integer holds. As nanoseconds since the Unix epoch, it is the instant
1677-09-21 00:12:43.145224192 UTC."""

INT64_MAX = 2**63 - 1
"""The largest value a signed 64-bit integer holds. As nanoseconds since the Unix epoch, it is the instant
2262-04-11 23:47:16.854775807 UTC."""
