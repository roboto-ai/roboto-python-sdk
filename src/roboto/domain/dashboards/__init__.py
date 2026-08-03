# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Saved metrics dashboards for visualizing an organization's data on the Roboto platform.

A dashboard is a named JSON document describing the sections, cards, and time
parameters the web UI renders, stored on the platform so it can be reopened and
shared. The platform stores that document verbatim and never interprets it: the
definition is self-describing, carrying its own schema version for whichever
client understands the schema. Ownership (``owner_principal_id``) is
the sole source of truth for visibility: a dashboard owned by the org principal is
shared with every member of the owning organization, while one owned by a user
principal is personal (visible only to that user). Create and update requests
express the choice via the ``accessibility`` knob, which the server folds into
ownership. Dashboard names must be unambiguous for each viewer within their
organization.
"""

from .operations import (
    CreateDashboardRequest,
    UpdateDashboardRequest,
)
from .record import (
    DashboardAccessibility,
    DashboardRecord,
)

__all__ = [
    "DashboardAccessibility",
    "DashboardRecord",
    "CreateDashboardRequest",
    "UpdateDashboardRequest",
]
