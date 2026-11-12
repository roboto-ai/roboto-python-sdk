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
    """
    Controls who can view a layout.
    """

    Organization = "organization"
    """All members of the organization owning the layout can view the layout."""

    User = "user"
    """Just the user who created the layout can view it."""


class LayoutRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a layout"""

    accessibility: LayoutAccessibility = LayoutAccessibility.User
    created: datetime.datetime
    created_by: str

    # Folder this layout is grouped under; ``None`` means ungrouped, shown at the root of its accessibility scope.
    folder: str | None = None
    layout_definition: dict[str, typing.Any]
    layout_id: str
    modified: datetime.datetime
    modified_by: str
    name: str
    org_id: str

    revision: int = 0
    """How many times the layout has been updated, starting at 0 when it is created.

    Every successful update advances it by one, a rename included. Send the revision you loaded as
    :py:attr:`~roboto.domain.layouts.operations.UpdateLayoutRequest.base_revision` to have an update refused if
    someone changed the layout since.
    """

    # Layout definition schema version
    schema_version: int
    tags: list[str] = pydantic.Field(default_factory=list)
