# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum


class DashboardAccessibility(StrEnum):
    """
    Controls who can view a dashboard.

    On create/update requests this is a knob that the server folds into
    :py:attr:`DashboardRecord.owner_principal_id`.  On
    :py:class:`DashboardRecord` it is a derived computed field — always in sync
    with the owner principal so API consumers never need to parse the principal
    string themselves.
    """

    Organization = "organization"
    """All members of the organization owning the dashboard can view it."""

    User = "user"
    """Just the user who created the dashboard can view it."""


class DashboardRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a dashboard"""

    created: datetime.datetime
    """Timestamp when the dashboard was created."""

    created_by: str
    """User ID of the dashboard's creator. Audit metadata only; ownership is carried by
    :py:attr:`owner_principal_id`."""

    dashboard_definition: dict[str, typing.Any]
    """The dashboard definition as a JSON object.

    Opaque to the platform, which stores and returns it verbatim. The definition is
    self-describing: it carries its own schema version, and the client that understands
    the schema is the one that reads it."""

    dashboard_id: str
    """Unique identifier for the dashboard."""

    modified: datetime.datetime
    """Timestamp when the dashboard was last modified."""

    modified_by: str
    """User ID of the last user to modify the dashboard."""

    name: str
    """Human-readable name for the dashboard. Unique per owner within an organization;
    dashboards with different owners may share a name, so by-name lookups can match more
    than one dashboard."""

    org_id: str
    """Organization ID that owns the dashboard."""

    owner_principal_id: str
    """Principal that owns the dashboard, serialized in the
    :py:class:`~roboto.principal.RobotoPrincipal` ``ptype:id`` format.

    ``org:<org_id>`` for organization-wide dashboards, ``user:<user_id>`` for personal
    dashboards. This is the sole source of truth for org-wide vs personal — a dashboard
    is org-wide exactly when its owner is the org principal. Ownership anchors
    authorization — a personal dashboard is editable by its owner or an org admin, an
    org-wide dashboard by any org member — and scopes name uniqueness: dashboard names
    are unique per owner within an organization.
    """

    revision: int = 0
    """How many times the dashboard definition has been written, starting at 0.

    A definition-generation counter, not a row version: it advances only when
    :py:attr:`dashboard_definition` is replaced, and is deliberately untouched by a rename
    or an accessibility change. Clients never set it — the server owns it — but they must
    echo the value they loaded back as ``base_revision`` when writing a new definition, so
    a write built on a stale copy can be rejected rather than silently erasing someone
    else's edit.
    """

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def accessibility(self) -> DashboardAccessibility:
        """Derived from :py:attr:`owner_principal_id`: organization when owned by
        the org principal, user otherwise."""
        if self.owner_principal_id.startswith("org:"):
            return DashboardAccessibility.Organization
        return DashboardAccessibility.User
