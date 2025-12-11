# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Action statistics functionality for retrieving invocation metrics."""

from __future__ import annotations

import datetime
from typing import Optional

import pydantic

from ...http import RobotoClient


class ActionStatsRecord(pydantic.BaseModel):
    """Statistical summary of action invocations for a specific action within a time period.

    This model represents aggregated invocation counts for a single action,
    broken down by completion status (completed, failed, queued).
    """

    action_name: str
    """Name of the action. Action names are unique within an organization."""

    action_org_id: str
    """Organization ID that owns the action."""

    completed_count: int
    """Number of invocations that completed successfully during the time period."""

    fail_count: int
    """Number of invocations that failed during the time period."""

    queued_count: int
    """Number of invocations that are currently queued or in progress during the time period."""


def get_action_stats(
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    roboto_client: Optional[RobotoClient] = None,
    org_id: Optional[str] = None,
) -> list[ActionStatsRecord]:
    """Retrieve action invocation statistics for all actions in an organization.

    Fetches aggregated statistics showing invocation counts by status for each action
    within the specified organization and time range. This provides a high-level view
    of action usage and success rates across the organization.

    Args:
        org_id: Organization ID to retrieve statistics for.
        start_time: Start of the time period (inclusive) for which to retrieve statistics.
        end_time: End of the time period (exclusive) for which to retrieve statistics.
        roboto_client: HTTP client for making API requests. If not provided, uses the
            default client configuration.

    Returns:
        List of ActionStatsRecord objects, one for each action that had invocations
        during the specified time period. Actions with no invocations are not included.

    Raises:
        RobotoUnauthorizedException: The caller is not authorized to access statistics
            for the specified organization.
        RobotoInvalidRequestException: Invalid time range or organization ID provided.

    Examples:
        Get statistics for the last 24 hours:

        >>> import datetime
        >>> from roboto.domain.actions.stats import get_action_stats
        >>> end_time = datetime.datetime.now()
        >>> start_time = end_time - datetime.timedelta(days=1)
        >>> stats = get_action_stats(start_time, end_time, org_id="og_1234567890abcdef")
        >>> for stat in stats:
        ...     print(f"{stat.action_name}: {stat.completed_count} completed, {stat.fail_count} failed")
    """
    roboto_client = RobotoClient.defaulted(roboto_client)

    query = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
    }

    return (
        roboto_client.get("/v1/actions/invocations/org-stats", query=query, caller_org_id=org_id)
        .to_paginated_list(ActionStatsRecord)
        .items
    )
