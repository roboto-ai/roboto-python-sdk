# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Union

import pydantic

from roboto.domain.dashboards.record import (
    DashboardAccessibility,
)
from roboto.sentinels import NotSet, NotSetType

from ...warnings import experimental


@experimental
class CreateDashboardRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/metrics/dashboards/create``.

    A ``name`` longer than 120 characters raises ``pydantic.ValidationError``.
    """

    accessibility: DashboardAccessibility = DashboardAccessibility.User
    """Who can view the dashboard: every member of the organization, or only the user who creates it.

    Roboto stores the choice only as the dashboard's owner, ``DashboardRecord.owner_principal_id``: the organization
    for ``DashboardAccessibility.Organization``, and the creating user for ``User``.
    """

    dashboard_definition: dict[str, Any]
    """Dashboard definition as a JSON object.

    Roboto stores it verbatim, as ``DashboardRecord.dashboard_definition`` describes.
    """

    name: str = pydantic.Field(max_length=120)
    """Human-readable name of the dashboard, at most 120 characters, unique among one owner's dashboards.

    A name the owner already uses raises ``RobotoConflictException``.
    """


@experimental
class UpdateDashboardRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/metrics/dashboards/id/{dashboard_id}``.

    A field left unset (``NotSet``) is unchanged. Any member of the organization may update an organization-wide
    dashboard, but only an organization administrator may make it personal. Only its owner or an organization
    administrator may update a personal dashboard. Any other caller's update raises ``RobotoUnauthorizedException``.

    Building it raises ``pydantic.ValidationError`` when:

    - ``name`` is longer than 120 characters.
    - ``base_revision`` is negative.
    - ``dashboard_definition`` is set without ``base_revision``, or ``base_revision`` without
      ``dashboard_definition``.
    """

    accessibility: Union[DashboardAccessibility, NotSetType] = NotSet
    """Who can view the dashboard: every member of the organization, or only the user who created it.

    Roboto sets the dashboard's owner from it: the organization for ``DashboardAccessibility.Organization``, and the
    user who created the dashboard for ``User``, whoever sends the update. A change that leaves the new owner with two
    dashboards of one name raises ``RobotoConflictException``.
    """

    base_revision: Union[int, NotSetType] = pydantic.Field(default=NotSet, ge=0)
    """Revision of the dashboard the caller loaded (``DashboardRecord.revision``), not the revision to write.

    Required when ``dashboard_definition`` is set, and rejected otherwise. When it no longer matches the dashboard's
    revision, because someone replaced the definition after the caller loaded it, the update raises
    ``RobotoDashboardRevisionConflictException`` and changes nothing. A rename or accessibility change needs no base
    revision, because neither replaces the definition.
    """

    dashboard_definition: Union[dict[str, Any], NotSetType] = NotSet
    """Dashboard definition as a JSON object, which replaces the stored one in full.

    Writing it advances ``DashboardRecord.revision`` by one.
    """

    name: Union[str, NotSetType] = pydantic.Field(default=NotSet, max_length=120)
    """Human-readable name of the dashboard, at most 120 characters, unique among one owner's dashboards.

    A name the owner already uses raises ``RobotoConflictException``.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.model_validator(mode="after")
    def validate_base_revision_with_definition(self) -> "UpdateDashboardRequest":
        """Reject a definition write without ``base_revision``, and a ``base_revision`` without a definition write."""
        # isinstance rather than truthiness, so base_revision=0, the revision of a definition never replaced, counts
        # as set.
        definition_set = not isinstance(self.dashboard_definition, NotSetType)
        base_revision_set = not isinstance(self.base_revision, NotSetType)

        if definition_set and not base_revision_set:
            raise ValueError("base_revision must be provided when updating dashboard_definition")
        if base_revision_set and not definition_set:
            # Roboto checks the revision only on a definition write; accepting it here would let the caller believe a
            # rename or accessibility change was checked against it.
            raise ValueError("base_revision is only meaningful when updating dashboard_definition")
        return self
