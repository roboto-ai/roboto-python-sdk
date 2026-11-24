# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
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


class TriggerType(StrEnum):
    """Kind of trigger: event-driven or scheduled."""

    EventDriven = "event_driven"
    """Trigger that invokes its action in response to platform events, such as an upload of files.

    :py:class:`~roboto.domain.actions.TriggerEvaluationCause` lists the platform events it can respond to.
    """

    Scheduled = "scheduled"
    """Trigger that invokes its action on a recurring schedule."""


class TriggerOnEvent(pydantic.BaseModel):
    """Settings of an event-driven trigger: the platform events it responds to and the files it passes to its action.

    Carried in ``TriggerView.on_event``.
    """

    causes: list[TriggerEvaluationCause]
    """Platform events that cause Roboto to evaluate the trigger."""

    for_each: TriggerForEachPrimitive
    """Whether the trigger invokes its action once per dataset or once per file."""

    required_inputs: list[str]
    """Gitignore-style patterns for the files the trigger requires, and passes to the action as its input data."""

    additional_inputs: typing.Optional[list[str]] = None
    """Gitignore-style patterns for more files to pass to the action as input data, or ``None`` to add none.

    Unlike ``required_inputs``, no file has to match them for the trigger to invoke its action.
    """

    condition: typing.Optional[ConditionType] = None
    """Condition the data must meet for the trigger to invoke its action, or ``None`` if the trigger has none."""


class TriggerOnSchedule(pydantic.BaseModel):
    """Settings of a scheduled trigger: its schedule and the input each invocation receives.

    Carried in ``TriggerView.on_schedule``.
    """

    schedule: str
    """Cron expression, in UTC, for when the trigger invokes the action, such as ``"0 * * * *"`` for every hour."""

    invocation_input: typing.Optional[InvocationInput] = None
    """Input each invocation receives, or ``None`` if invocations take no input."""

    next_occurrence: typing.Optional[datetime.datetime] = None
    """Next time the trigger invokes the action, or ``None`` if the trigger is disabled.

    Roboto sets it from ``schedule``; no request does.
    """


class TriggerView(pydantic.BaseModel):
    """Data record of a trigger, as an item of the response body of ``POST /v1/triggers/aggregated/query``.

    Event-driven and scheduled triggers share this one shape: ``trigger_type`` says which kind the trigger is, and so
    which of ``on_event`` and ``on_schedule`` is set. The record belongs to the legacy trigger model and covers only the
    triggers that model can express; :py:class:`~roboto.domain.triggers.Trigger` reads and edits every trigger.
    """

    trigger_id: str
    """Unique ID of the trigger."""

    trigger_type: TriggerType
    """Whether the trigger is event-driven or scheduled."""

    name: str
    """Human-readable name of the trigger, unique within its organization."""

    on_event: typing.Optional[TriggerOnEvent] = None
    """Settings of an event-driven trigger, or ``None`` if the trigger is scheduled."""

    on_schedule: typing.Optional[TriggerOnSchedule] = None
    """Settings of a scheduled trigger, or ``None`` if the trigger is event-driven."""

    enabled: bool
    """Whether the trigger is enabled. A disabled trigger never invokes its action."""

    action: ActionReference
    """Action the trigger invokes. A reference without a digest invokes the action's latest version."""

    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    """Values for the action's parameters, keyed by parameter name, or ``None`` if the trigger sets none."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Compute requirements that replace the action's own in each invocation, or ``None`` to use the action's."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Container parameters that replace the action's own in each invocation, or ``None`` to use the action's."""

    timeout: typing.Optional[int] = None
    """Maximum run time of each invocation, in minutes, or ``None`` to use the action's timeout."""

    invocation_upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Where each invocation uploads its output files, or ``None`` if the trigger sets no destination."""

    service_user_id: str
    """ID of the service user the trigger invokes its action as."""

    org_id: str
    """ID of the organization that owns the trigger."""

    created: datetime.datetime
    """Time the trigger was created."""

    created_by: str
    """ID of the user who created the trigger."""

    modified: datetime.datetime
    """Time the trigger was last modified."""

    modified_by: str
    """ID of the user who last modified the trigger.

    Roboto's own system user when Roboto made the change.
    """

    def to_event_trigger_record(self) -> typing.Optional[TriggerRecord]:
        """Return this trigger as a :py:class:`~roboto.domain.actions.TriggerRecord`, or ``None`` if it is scheduled.

        The record has no field for ``invocation_upload_destination``, so it leaves that setting out.

        Raises:
            RuntimeError: The trigger is event-driven but ``on_event`` is ``None``.
        """
        if self.trigger_type is not TriggerType.EventDriven:
            return None

        if self.on_event is None:
            raise RuntimeError("Expected self.on_event to be set")
        return TriggerRecord(
            trigger_id=self.trigger_id,
            name=self.name,
            action=self.action.model_copy(deep=True),
            enabled=self.enabled,
            required_inputs=self.on_event.required_inputs,
            additional_inputs=(self.on_event.additional_inputs[:] if self.on_event.additional_inputs else None),
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
                self.compute_requirement_overrides.model_copy(deep=True) if self.compute_requirement_overrides else None
            ),
            container_parameter_overrides=(
                self.container_parameter_overrides.model_copy(deep=True) if self.container_parameter_overrides else None
            ),
            timeout=self.timeout,
            parameter_values=(dict(self.parameter_values) if self.parameter_values else dict()),
        )

    def to_scheduled_trigger_record(self) -> typing.Optional[ScheduledTriggerRecord]:
        """Return this trigger as a scheduled trigger record, or ``None`` if it is event-driven.

        The record is a :py:class:`~roboto.domain.actions.ScheduledTriggerRecord`, which has no field for
        ``service_user_id`` and so leaves it out.

        Raises:
            RuntimeError: The trigger is scheduled but ``on_schedule`` is ``None``.
        """
        if self.trigger_type is not TriggerType.Scheduled:
            return None

        if self.on_schedule is None:
            raise RuntimeError("Expected self.on_schedule to be set")
        return ScheduledTriggerRecord(
            trigger_id=self.trigger_id,
            name=self.name,
            action=self.action.model_copy(deep=True),
            schedule=self.on_schedule.schedule,
            enabled=self.enabled,
            invocation_input=(
                self.on_schedule.invocation_input.model_copy(deep=True) if self.on_schedule.invocation_input else None
            ),
            invocation_upload_destination=(
                self.invocation_upload_destination.model_copy(deep=True) if self.invocation_upload_destination else None
            ),
            next_occurrence=self.on_schedule.next_occurrence,
            created=self.created,
            created_by=self.created_by,
            modified=self.modified,
            modified_by=self.modified_by,
            org_id=self.org_id,
            compute_requirement_overrides=(
                self.compute_requirement_overrides.model_copy(deep=True) if self.compute_requirement_overrides else None
            ),
            container_parameter_overrides=(
                self.container_parameter_overrides.model_copy(deep=True) if self.container_parameter_overrides else None
            ),
            timeout=self.timeout,
            parameter_values=(dict(self.parameter_values) if self.parameter_values else None),
        )
