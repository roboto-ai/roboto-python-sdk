# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

JsonablePrimitive = typing.Union[int, str, float, bool]
"""Scalar value that encodes directly to JSON: an ``int``, ``str``, ``float`` or ``bool``."""

UserMetadata = dict[str, JsonablePrimitive]
"""Key-value metadata with string keys, each value a ``JsonablePrimitive``."""
