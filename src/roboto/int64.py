# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

INT64_MIN = -(2**63)
"""Smallest signed 64-bit integer, and the lowest nanosecond timestamp, timeline offset, or row position Roboto stores.

As nanoseconds since the Unix epoch, it is the instant 1677-09-21 00:12:43.145224192 UTC. Many fields accept only part
of the range from ``INT64_MIN`` to ``INT64_MAX``; a file's timeline offset, for example, must not be negative.
"""

INT64_MAX = 2**63 - 1
"""Largest signed 64-bit integer, and the highest nanosecond timestamp, timeline offset, or row position Roboto stores.

As nanoseconds since the Unix epoch, it is the instant 2262-04-11 23:47:16.854775807 UTC.
"""
