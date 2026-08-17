# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Describe a recording's contents and hand them to the platform in one call.

Callers state what their data is and which slices belong together; the platform composes the underlying writes.
"""

from .schema import Field, Schema

__all__ = (
    "Field",
    "Schema",
)
