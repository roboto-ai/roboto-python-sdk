# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
from typing import Optional

import pydantic

from ...http import RobotoClient


class ActionStatsRecord(pydantic.BaseModel):
    """Data record of one action's invocation counts over a time range, as the Roboto API returns it.

    ``get_action_stats`` returns one per action. Each count is the number of times an invocation of the action entered
    a status during the time range, so a failed invocation that Roboto retries counts once per attempt.
    """

    action_name: str
    """Name of the action, unique within the organization that owns it."""

    action_org_id: str
    """ID of the organization that owns the action."""

    completed_count: int
    """Number of times an invocation of the action completed during the time range."""

    fail_count: int
    """Number of times an invocation of the action failed during the time range."""

    queued_count: int
    """Number of times an invocation of the action was queued during the time range."""


def get_action_stats(
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    roboto_client: Optional[RobotoClient] = None,
    org_id: Optional[str] = None,
) -> list[ActionStatsRecord]:
    """Fetch invocation counts by status for each action an organization invoked during a time range.

    Counts the invocations that run in the organization, including those of actions another organization owns.

    Args:
        start_time: Exclusive start of the time range.
        end_time: Exclusive end of the time range.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        org_id: Organization to count invocations in. Required when the caller belongs to more than one organization;
            otherwise the caller's only organization.

    Returns:
        One ``ActionStatsRecord`` per action with an invocation that was queued, completed or failed during the time
        range, highest ``queued_count`` first, up to 1,000 actions.

    Examples:
        Print each action's counts for the last 24 hours:

        >>> import datetime
        >>> from roboto.domain.actions.stats import get_action_stats
        >>> end_time = datetime.datetime.now(datetime.timezone.utc)
        >>> start_time = end_time - datetime.timedelta(days=1)
        >>> for stat in get_action_stats(start_time, end_time, org_id="og_12345"):
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
