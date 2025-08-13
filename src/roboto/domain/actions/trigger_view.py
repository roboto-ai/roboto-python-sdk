# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

from ...query import ConditionType
from .action_record import (
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_record import (
    InvocationInput,
    InvocationUploadDestination,
)
from .scheduled_trigger_record import (
    ScheduledTriggerRecord,
)
from .trigger_record import (
    TriggerEvaluationCause,
    TriggerForEachPrimitive,
    TriggerRecord,
)


class TriggerType(str, enum.Enum):
    """Types of triggers supported by the Roboto platform."""

    EventDriven = "event_driven"
    """A trigger that invokes its target action in response to an event.

    See :py:class:`~roboto.domain.actions.TriggerEvaluationCause` for the
    currently supported causes for event-driven triggers to be evaluated.
    """

    Scheduled = "scheduled"
    """A trigger that invokes its target action on a recurring schedule."""


class TriggerOnEvent(pydantic.BaseModel):
    """Properties specific to event-driven triggers."""

    causes: list[TriggerEvaluationCause]
    """One or more events that cause the trigger to be evaluated."""

    for_each: TriggerForEachPrimitive
    """Granularity of trigger execution."""

    required_inputs: list[str]
    """File patterns that must be present for trigger to fire."""

    additional_inputs: typing.Optional[list[str]] = None
    """Optional additional file patterns to include."""

    condition: typing.Optional[ConditionType] = None
    """Optional condition that must be met for trigger to fire."""


class TriggerOnSchedule(pydantic.BaseModel):
    """Properties specific to scheduled triggers."""

    schedule: str
    """Recurring invocation schedule."""

    invocation_input: typing.Optional[InvocationInput] = None
    """Input specification for each scheduled invocation."""

    next_occurrence: typing.Optional[datetime.datetime] = None
    """Next scheduled invocation time."""


class TriggerView(pydantic.BaseModel):
    """Unified data model for all Roboto trigger types."""

    trigger_id: str
    """Unique trigger ID."""

    trigger_type: TriggerType
    """Trigger type."""

    name: str
    """Trigger name. Unique within an organization and trigger type."""

    on_event: typing.Optional[TriggerOnEvent] = None
    """Properties of triggers that fire on events (``TriggerType.EventDriven``)."""

    on_schedule: typing.Optional[TriggerOnSchedule] = None
    """Properties of triggers that fire on a recurring schedule (``TriggerType.Scheduled``)."""

    enabled: bool
    """True if the trigger is enabled."""

    action: ActionReference
    """Reference to the trigger's target action."""

    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    """Optional action parameter values."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Optional compute requirement overrides."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Optional container parameter overrides."""

    timeout: typing.Optional[int] = None
    """Optional invocation timeout, in minutes."""

    invocation_upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Optional default upload destination for action invocations."""

    service_user_id: str
    """Service user ID for authentication."""

    org_id: str
    """Organization ID which owns the scheduled trigger."""

    created: datetime.datetime
    """Creation time for the scheduled trigger."""

    created_by: str
    """User who created the scheduled trigger."""

    modified: datetime.datetime
    """Latest modification time for the scheduled trigger."""

    modified_by: str
    """User who last modified this scheduled trigger."""

    def to_event_trigger_record(self) -> typing.Optional[TriggerRecord]:
        """Convert this trigger view into a :py:class:`~roboto.domain.actions.TriggerRecord` if possible.

        Returns:
            A ``TriggerRecord`` instance if ``self.trigger_type`` is ``TriggerType.EventDriven``,
            otherwise None.
        """

        if self.trigger_type is not TriggerType.EventDriven:
            return None

        assert self.on_event is not None
        return TriggerRecord(
            trigger_id=self.trigger_id,
            name=self.name,
            action=self.action.model_copy(deep=True),
            enabled=self.enabled,
            required_inputs=self.on_event.required_inputs,
            additional_inputs=(
                self.on_event.additional_inputs[:]
                if self.on_event.additional_inputs
                else None
            ),
            for_each=self.on_event.for_each,
            condition=self.on_event.condition,
            causes=self.on_event.causes[:],
            created=self.created,
            created_by=self.created_by,
            modified=self.modified,
            modified_by=self.modified_by,
            org_id=self.org_id,
            service_user_id=self.service_user_id,
            compute_requirement_overrides=(
                self.compute_requirement_overrides.model_copy(deep=True)
                if self.compute_requirement_overrides
                else None
            ),
            container_parameter_overrides=(
                self.container_parameter_overrides.model_copy(deep=True)
                if self.container_parameter_overrides
                else None
            ),
            timeout=self.timeout,
            parameter_values=(
                dict(self.parameter_values) if self.parameter_values else dict()
            ),
        )

    def to_scheduled_trigger_record(self) -> typing.Optional[ScheduledTriggerRecord]:
        """Convert this trigger view into a :py:class:`~roboto.domain.actions.ScheduledTriggerRecord` if possible.

        Returns:
            A ``ScheduledTriggerRecord`` instance if ``self.trigger_type`` is ``TriggerType.Scheduled``,
            otherwise None.
        """

        if self.trigger_type is not TriggerType.Scheduled:
            return None

        assert self.on_schedule is not None
        return ScheduledTriggerRecord(
            trigger_id=self.trigger_id,
            name=self.name,
            action=self.action.model_copy(deep=True),
            schedule=self.on_schedule.schedule,
            enabled=self.enabled,
            invocation_input=(
                self.on_schedule.invocation_input.model_copy(deep=True)
                if self.on_schedule.invocation_input
                else None
            ),
            invocation_upload_destination=(
                self.invocation_upload_destination.model_copy(deep=True)
                if self.invocation_upload_destination
                else None
            ),
            next_occurrence=self.on_schedule.next_occurrence,
            created=self.created,
            created_by=self.created_by,
            modified=self.modified,
            modified_by=self.modified_by,
            org_id=self.org_id,
            compute_requirement_overrides=(
                self.compute_requirement_overrides.model_copy(deep=True)
                if self.compute_requirement_overrides
                else None
            ),
            container_parameter_overrides=(
                self.container_parameter_overrides.model_copy(deep=True)
                if self.container_parameter_overrides
                else None
            ),
            timeout=self.timeout,
            parameter_values=(
                dict(self.parameter_values) if self.parameter_values else None
            ),
        )
