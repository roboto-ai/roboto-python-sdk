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
    """Wire-transmissible representation of a scheduled trigger.

    Contains all the configuration and metadata for a scheduled trigger, including
    the target action, invocation schedule, input specification and execution settings.

    This is the underlying data structure used by the :py:class:`~roboto.domain.actions.ScheduledTrigger`
    domain class to store and transmit trigger information.
    """

    action: ActionReference
    """Reference to the action this trigger invokes."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Optional compute requirement overrides."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Optional container parameter overrides."""

    created: datetime.datetime
    """Creation time for the scheduled trigger."""

    created_by: str
    """User who created the scheduled trigger."""

    enabled: bool
    """True if the scheduled trigger is enabled."""

    invocation_input: typing.Optional[InvocationInput] = None
    """Optional invocation input for action invocations."""

    invocation_upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Optional upload destination for action invocation outputs."""

    name: str
    """Scheduled trigger name. Unique within an organization."""

    next_occurrence: typing.Optional[datetime.datetime] = None
    """Next scheduled invocation time, or None if the trigger is disabled.

    This is computed and updated by the Roboto system.
    """

    org_id: str
    """Organization ID which owns the scheduled trigger."""

    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    """Optional action parameter values."""

    schedule: str
    """Invocation schedule for the target action."""

    timeout: typing.Optional[int] = None
    """Optional invocation timeout, in minutes."""

    trigger_id: str
    """Unique ID of the scheduled trigger."""

    modified: datetime.datetime
    """Last modification time for the scheduled trigger."""

    modified_by: str
    """User who last modified this scheduled trigger."""

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ScheduledTriggerRecord):
            return False

        return self.__selective_model_dump() == other.__selective_model_dump()

    def __selective_model_dump(self) -> dict[str, typing.Any]:
        # Exclude next_occurrence and related fields from equality checks and hashing,
        # since they get updated on the trigger's schedule
        return self.model_dump(
            exclude={"next_occurrence", "modified", "modified_by"}, mode="json"
        )
