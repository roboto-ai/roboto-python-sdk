# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...warnings import experimental


@experimental
class DashboardAccessibility(StrEnum):
    """Accessibility of a dashboard: who can view it.

    Create and update requests set it, and Roboto records it as the dashboard's owner,
    ``DashboardRecord.owner_principal_id``. ``DashboardRecord.accessibility`` is derived from that owner.
    """

    Organization = "organization"
    """Every member of the organization that owns the dashboard can view it."""

    User = "user"
    """Only the user who created the dashboard and the organization's administrators can view it."""


@experimental
class DashboardRecord(pydantic.BaseModel):
    """Data record of a dashboard, as ``GET /v1/metrics/dashboards/id/{dashboard_id}`` returns it.

    ``POST /v1/metrics/dashboards/create`` and ``PUT /v1/metrics/dashboards/id/{dashboard_id}`` return it too, and
    ``GET /v1/metrics/dashboards/`` returns a page of them.

    A dashboard is a saved page of metrics in the Roboto web app: a name and a JSON definition of what the page
    shows, owned either by its organization or by the user who created it.
    """

    created: datetime.datetime
    """Time the dashboard was created."""

    created_by: str
    """ID of the user who created the dashboard.

    Changing the dashboard's accessibility to ``DashboardAccessibility.User`` makes this user its owner again,
    whoever makes the change.
    """

    dashboard_definition: dict[str, typing.Any]
    """Content of the dashboard, as a JSON object that carries its own schema version.

    Roboto stores and returns it unchanged and never reads it.
    """

    dashboard_id: str
    """Unique ID of the dashboard, beginning with ``dsbd_``."""

    modified: datetime.datetime
    """Time the dashboard was last modified."""

    modified_by: str
    """ID of the user who last modified the dashboard."""

    name: str
    """Human-readable name of the dashboard, unique among the dashboards of one owner in its organization.

    An organization-wide dashboard and a personal one, or the personal dashboards of two users, may share a name.
    """

    org_id: str
    """ID of the organization that owns the dashboard."""

    owner_principal_id: str
    """Principal that owns the dashboard, as ``<type>:<id>``.

    ``org:<org_id>`` for an organization-wide dashboard, ``user:<user_id>`` for a personal one. Roboto sets it from
    the ``accessibility`` of create and update requests; no request sets it directly. The owner decides who may
    change the dashboard:

    - Any member of the organization may update an organization-wide dashboard. Only the organization's
      administrators may make it personal or delete it.
    - Only the owner and the organization's administrators may update or delete a personal dashboard.

    :py:class:`~roboto.principal.RobotoPrincipal` parses the string form.
    """

    revision: int = 0
    """Number of times the dashboard's definition has been replaced, starting at ``0``.

    Each update that sets ``dashboard_definition`` adds one; a rename or an accessibility change does not. Roboto
    sets it; no request does. An update that replaces the definition sends the revision you loaded as
    ``UpdateDashboardRequest.base_revision``, and Roboto refuses it with
    ``roboto.exceptions.RobotoDashboardRevisionConflictException`` if someone replaced the definition since.
    """

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def accessibility(self) -> DashboardAccessibility:
        """Accessibility of the dashboard, derived from ``owner_principal_id``.

        ``DashboardAccessibility.Organization`` when the organization owns the dashboard, ``User`` otherwise. Included
        in the record's JSON form.
        """
        if self.owner_principal_id.startswith("org:"):
            return DashboardAccessibility.Organization
        return DashboardAccessibility.User
