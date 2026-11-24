# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
import typing

import pydantic

from .action_record import (
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_record import (
    InvocationInput,
    InvocationUploadDestination,
)


class ScheduledTriggerRecord(pydantic.BaseModel):
    """Deprecated. Data record of a scheduled trigger, as the Roboto API returns it.

    The record belongs to the legacy trigger model; :py:class:`~roboto.domain.triggers.Trigger` reads and edits every
    trigger. A scheduled trigger invokes an action on a recurring schedule, such as hourly or daily.
    :py:class:`~roboto.domain.actions.ScheduledTrigger` wraps this record, and exposes it as
    :py:attr:`~roboto.domain.actions.ScheduledTrigger.record`.
    """

    action: ActionReference
    """Action the trigger invokes."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Overrides of the action's compute requirements for each invocation, or ``None`` to use the action's own."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Overrides of the action's container parameters for each invocation, or ``None`` to use the action's own."""

    created: datetime.datetime
    """Time the scheduled trigger was created."""

    created_by: str
    """ID of the user who created the scheduled trigger."""

    enabled: bool
    """Whether the trigger invokes the action on its schedule."""

    invocation_input: typing.Optional[InvocationInput] = None
    """Input each invocation receives, or ``None`` if invocations take no input."""

    invocation_upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Where each invocation uploads its output files, or ``None`` if the trigger sets no destination."""

    name: str
    """Human-readable name of the scheduled trigger, unique within its organization."""

    next_occurrence: typing.Optional[datetime.datetime] = None
    """Next time the trigger invokes the action, or ``None`` if the trigger is disabled.

    Roboto sets it from ``schedule``; no request does.
    """

    org_id: str
    """ID of the organization that owns the scheduled trigger."""

    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    """Values for the action's parameters, keyed by parameter name, or ``None`` if the trigger sets none."""

    schedule: str
    """Cron expression, in UTC, for when the trigger invokes the action, such as ``"0 * * * *"`` for every hour."""

    timeout: typing.Optional[int] = None
    """Timeout of each invocation, in minutes, or ``None`` to use the action's own."""

    trigger_id: str
    """Unique ID of the scheduled trigger."""

    modified: datetime.datetime
    """Time the scheduled trigger was last modified."""

    modified_by: str
    """ID of the user who last modified the scheduled trigger.

    Roboto's own system user when Roboto made the change.
    """

    def __eq__(self, other: typing.Any) -> bool:
        """Return whether ``other`` is a scheduled trigger record with the same configuration.

        ``next_occurrence``, ``modified`` and ``modified_by`` are left out of the comparison. ``next_occurrence``
        changes as the schedule advances; ``modified`` and ``modified_by`` record who last edited the trigger and
        when, not what it is configured to do.
        """
        if not isinstance(other, ScheduledTriggerRecord):
            return False

        return self.__selective_model_dump() == other.__selective_model_dump()

    def __selective_model_dump(self) -> dict[str, typing.Any]:
        return self.model_dump(exclude={"next_occurrence", "modified", "modified_by"}, mode="json")
