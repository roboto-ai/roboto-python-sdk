# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Layouts: saved arrangements of visualizer panels and the signals each panel draws.

Signals are matched by topic name and message path, so a layout holds no data and applies to any file with those
topics. :py:class:`~roboto.domain.layouts.LayoutRecord` describes a layout, and
:py:class:`~roboto.domain.layouts.CreateLayoutRequest` and :py:class:`~roboto.domain.layouts.UpdateLayoutRequest` are
the request bodies for creating and updating one.
"""

from .operations import (
    CreateLayoutRequest,
    UpdateLayoutRequest,
)
from .record import (
    LayoutAccessibility,
    LayoutRecord,
)

__all__ = [
    "LayoutAccessibility",
    "LayoutRecord",
    "CreateLayoutRequest",
    "UpdateLayoutRequest",
]
