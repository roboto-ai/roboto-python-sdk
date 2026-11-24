# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Dashboards: saved pages of metrics in the Roboto web app.

Each dashboard is a name and a JSON definition of what the page shows, owned either by its organization or by the
user who created it. ``DashboardRecord`` holds a dashboard, ``CreateDashboardRequest`` and ``UpdateDashboardRequest``
create and update one, and ``DashboardAccessibility`` sets who can view it. Every class here is experimental, and may
change or be removed without notice. Send the models to the routes under ``/v1/metrics/dashboards`` with
:py:class:`~roboto.http.RobotoClient`. No SDK method sends or returns these models.
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
