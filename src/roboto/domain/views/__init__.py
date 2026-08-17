# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Wire types for Views: named, shareable searches over a single resource type.

A View saves the filters, sort, page size, and column layout a user arrived at, so they can
return to it later or hand it to a teammate rather than rebuilding it.
"""

from .operations import (
    MAX_VIEW_NAME_LENGTH,
    CreateViewRequest,
    UpdateViewRequest,
)
from .record import (
    VIEW_SCHEMA_VERSION_V1,
    VIEW_SCHEME_V1,
    ViewDefinition,
    ViewDisplay,
    ViewRecord,
)

__all__ = [
    "MAX_VIEW_NAME_LENGTH",
    "VIEW_SCHEMA_VERSION_V1",
    "VIEW_SCHEME_V1",
    "CreateViewRequest",
    "UpdateViewRequest",
    "ViewDefinition",
    "ViewDisplay",
    "ViewRecord",
]
