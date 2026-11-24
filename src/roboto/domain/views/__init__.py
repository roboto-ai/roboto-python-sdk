# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Views: named, shareable searches over one resource type, saved with their author's columns, sort, and page size.

:py:class:`~roboto.domain.views.ViewRecord` holds a View as Roboto returns it,
:py:class:`~roboto.domain.views.ViewDefinition` holds its saved search and display settings, and
:py:class:`~roboto.domain.views.CreateViewRequest` and :py:class:`~roboto.domain.views.UpdateViewRequest` are the
request bodies for creating and updating one. The SDK has no methods for Views; these classes describe what the
``/v1/views`` endpoints accept and return.
"""

from .operations import (
    MAX_VIEW_NAME_LENGTH,
    CreateViewRequest,
    UpdateViewRequest,
)
from .record import (
    ROBOQL_VIEW_TARGETS,
    VIEW_SCHEMA_VERSION_V1,
    VIEW_SCHEMA_VERSION_V2,
    VIEW_SCHEME_V1,
    VIEW_SCHEME_V2,
    ColumnSort,
    DefaultSort,
    NoSort,
    ViewDefinition,
    ViewDisplay,
    ViewRecord,
    ViewSort,
    ViewVisibility,
    ensure_definition_renders_for,
)

__all__ = [
    "MAX_VIEW_NAME_LENGTH",
    "ROBOQL_VIEW_TARGETS",
    "VIEW_SCHEMA_VERSION_V1",
    "VIEW_SCHEMA_VERSION_V2",
    "VIEW_SCHEME_V1",
    "VIEW_SCHEME_V2",
    "ColumnSort",
    "CreateViewRequest",
    "DefaultSort",
    "NoSort",
    "UpdateViewRequest",
    "ViewDefinition",
    "ViewDisplay",
    "ViewRecord",
    "ViewSort",
    "ViewVisibility",
    "ensure_definition_renders_for",
]
