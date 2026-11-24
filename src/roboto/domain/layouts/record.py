# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum


class LayoutAccessibility(StrEnum):
    """Accessibility of a layout: who can view it."""

    Organization = "organization"
    """Every member of the organization that owns the layout can view it."""

    User = "user"
    """Only the user who created the layout and the organization's administrators can view it."""


class LayoutRecord(pydantic.BaseModel):
    """Data record of a layout, as ``GET /v1/layouts/id/{layout_id}`` returns it.

    ``POST /v1/layouts/create``, ``PUT /v1/layouts/id/{layout_id}``, ``GET /v1/layouts/name/{layout_name}`` and
    ``GET /v1/layouts/`` return it too.

    A layout is a saved arrangement of visualizer panels and the signals each panel draws. Signals are matched by
    topic name and message path, so a layout holds no data and applies to any file with those topics.
    """

    accessibility: LayoutAccessibility = LayoutAccessibility.User
    """Who can view the layout. Defaults to ``LayoutAccessibility.User``."""

    created: datetime.datetime
    """Time the layout was created."""

    created_by: str
    """ID of the user who created the layout.

    Only this user and the organization's administrators can update or delete the layout, and only this user can
    rename it.
    """

    folder: str | None = None
    """Name of the folder the layout is grouped under, or ``None`` if it is in no folder.

    A folder is a label shared by the layouts grouped under it, not a separate resource.
    """

    layout_definition: dict[str, typing.Any]
    """Panels of the layout and the signals each draws, as a JSON object in the format ``schema_version`` names."""

    layout_id: str
    """Unique ID of the layout, beginning with ``ly_``."""

    modified: datetime.datetime
    """Time the layout was last modified."""

    modified_by: str
    """ID of the user who last modified the layout."""

    name: str
    """Human-readable name of the layout.

    A layout with ``LayoutAccessibility.Organization`` accessibility has a name unique within its organization, and one
    with ``LayoutAccessibility.User`` accessibility a name unique among its creator's ``User`` layouts. Roboto also
    rejects a ``User`` layout with the name of an ``Organization`` layout.
    """

    org_id: str
    """ID of the organization that owns the layout."""

    revision: int = 0
    """Number of times the layout has been updated: ``0`` when it is created, and one more for every update.

    A rename counts as an update. Send the revision you loaded as
    :py:attr:`~roboto.domain.layouts.UpdateLayoutRequest.base_revision` to have Roboto refuse an update if someone
    changed the layout since.
    """

    schema_version: int
    """Version of the format that ``layout_definition`` follows."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the layout."""
