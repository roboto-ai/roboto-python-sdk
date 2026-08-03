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


class CreateDashboardRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/metrics/dashboards/create``."""

    accessibility: DashboardAccessibility = DashboardAccessibility.User
    """Whether the dashboard is org-wide or personal. The server derives
    ``owner_principal_id`` from this — the org principal for ``organization``, the
    creator's user principal for ``user`` — and ownership is the stored source of
    truth; this field is not persisted separately."""

    dashboard_definition: dict[str, Any]
    """The dashboard definition as a JSON object. Stored verbatim and never interpreted
    by the platform; it carries its own schema version for the clients that read it."""

    name: str = pydantic.Field(max_length=120)
    """The name of the dashboard."""


class UpdateDashboardRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/metrics/dashboards/id/<dashboard_id>``."""

    accessibility: Union[DashboardAccessibility, NotSetType] = NotSet
    """Whether the dashboard should become org-wide or personal. The server re-derives
    ``owner_principal_id`` from this — to the org principal for ``organization``, back
    to the creator's user principal for ``user``; ownership is the stored source of
    truth."""

    base_revision: Union[int, NotSetType] = pydantic.Field(default=NotSet, ge=0)
    """The revision you loaded — not the revision you want.

    Required when ``dashboard_definition`` is present, and rejected otherwise. The server
    compares it against the stored revision and rejects the write if the definition has
    been replaced in the meantime, so a save built on a stale copy cannot silently erase
    someone else's edit. A rename or accessibility change carries no base revision: neither
    touches the definition, so neither can clobber it."""

    dashboard_definition: Union[dict[str, Any], NotSetType] = NotSet
    """The dashboard definition as a JSON object. Replaces the stored definition wholesale;
    it carries its own schema version, so no separate version field accompanies it."""

    name: Union[str, NotSetType] = pydantic.Field(default=NotSet, max_length=120)
    """The name of the dashboard."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.model_validator(mode="after")
    def validate_base_revision_with_definition(self) -> "UpdateDashboardRequest":
        """Require a base revision for definition writes, and only for definition writes.

        The presence checks use :py:class:`~roboto.sentinels.NotSetType` rather than
        truthiness: ``base_revision=0`` is the commonest real value — a dashboard whose
        definition has never been rewritten — and a falsy test would reject exactly that.
        """
        definition_set = not isinstance(self.dashboard_definition, NotSetType)
        base_revision_set = not isinstance(self.base_revision, NotSetType)

        if definition_set and not base_revision_set:
            raise ValueError("base_revision must be provided when updating dashboard_definition")
        if base_revision_set and not definition_set:
            # Silently ignoring it would hand the caller a concurrency guarantee that is
            # never checked; only a definition write is guarded.
            raise ValueError("base_revision is only meaningful when updating dashboard_definition")
        return self
