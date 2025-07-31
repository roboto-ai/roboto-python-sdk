# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import typing

import cron_converter

from ...http import RobotoClient
from ...query import (
    Comparator,
    Condition,
    QuerySpecification,
    SortDirection,
)
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from .action import Action
from .action_record import (
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from .invocation import Invocation
from .invocation_record import (
    InvocationInput,
    InvocationUploadDestination,
)
from .scheduled_trigger_operations import (
    CreateScheduledTriggerRequest,
    UpdateScheduledTriggerRequest,
)
from .scheduled_trigger_record import (
    ScheduledTriggerRecord,
)
from .trigger_record import (
    TriggerEvaluationRecord,
)
from .trigger_view import TriggerType


class TriggerSchedule:
    """Utility for defining trigger schedules."""

    __cron_string: str

    @classmethod
    def cron(cls, cron_string: str) -> TriggerSchedule:
        """Create a trigger schedule based on a Cron expression.

        Args:
            cron_string: A Cron expression like `*/30 * * * *`.

        Returns:
            A :py:class:`TriggerSchedule` instance.

        Raises:
            ValueError: If the provided string is not a valid Cron expression.
        """

        _ = cron_converter.Cron(cron_string)  # check validity
        return cls(cron_string)

    @classmethod
    def hourly(cls) -> TriggerSchedule:
        """Every hour on the hour."""

        return cls("0 * * * *")

    @classmethod
    def daily(cls) -> TriggerSchedule:
        """Every day at midnight UTC."""

        return cls("0 0 * * *")

    @classmethod
    def weekly(cls) -> TriggerSchedule:
        """Every Sunday at midnight UTC."""

        return cls("0 0 * * 0")

    @classmethod
    def monthly(cls) -> TriggerSchedule:
        """Every 1st of the month at midnight UTC."""

        return cls("0 0 1 * *")

    def __init__(self, cron_string: str) -> None:
        self.__cron_string = cron_string

    @property
    def cron_string(self) -> str:
        """Cron string representing the schedule."""

        return self.__cron_string


class ScheduledTrigger:
    """A trigger that invokes actions on a recurring schedule, e.g. hourly or daily.

    Schedules are currently specified using standard Cron expressions, with times in UTC.
    A handful of common schedules are provided by the :py:class:`TriggerSchedule` class.

    Once a scheduled time is reached, the action associated with this trigger will be
    invoked using the optionally provided input specification, and any other overrides
    such as compute requirements or parameter values.
    """

    __record: ScheduledTriggerRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        schedule: typing.Union[str, TriggerSchedule],
        action_name: str,
        action_owner_id: typing.Optional[str] = None,
        compute_requirement_overrides: typing.Optional[ComputeRequirements] = None,
        container_parameter_overrides: typing.Optional[ContainerParameters] = None,
        enabled: bool = True,
        invocation_input: typing.Optional[InvocationInput] = None,
        invocation_upload_destination: typing.Optional[
            InvocationUploadDestination
        ] = None,
        parameter_values: typing.Optional[dict[str, typing.Any]] = None,
        timeout: typing.Optional[int] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> ScheduledTrigger:
        """Create a new scheduled trigger.

        If the trigger is enabled on creation, action invocations will commence on the
        provided schedule. Note that the total number of active triggers in an organization is
        subject to a tier-specific limit. Exceeding that limit will result in the trigger
        being disabled.

        Args:
            name: Unique name for the scheduled trigger. Must not exceed 256 characters.
            schedule: Recurring schedule for the trigger, e.g. hourly.
            action_name: Name of the action to invoke on schedule.
            action_owner_id: Organization ID that owns the target action. If not provided,
                searches the caller's organization.
            compute_requirement_overrides: Optional compute requirement overrides for
                action invocations.
            container_parameter_overrides: Optional container parameter overrides for
                action invocations.
            enabled: Whether the trigger should be active immediately after creation.
            invocation_input: Optional input specification to be used for all scheduled
                action invocations.
            invocation_upload_destination: Optional upload destination for invocation
                outputs. Currently supports datasets.
            parameter_values: Optional parameter values to pass to the action when invoked.
            timeout: Optional timeout override for action invocations, in minutes.
            caller_org_id: Organization ID to create the trigger in. Defaults to caller's org.
            roboto_client: Roboto client instance. If not provided, defaults to the caller's
                Roboto configuration.

        Returns:
            The newly created ``ScheduledTrigger`` instance.

        Raises:
            ValueError: If request parameters have invalid values, e.g. a negative timeout.
            RobotoInvalidRequestException: If the request cannot be satisfied as provided.
            RobotoUnauthorizedException: If the caller lacks permission to create triggers,
                invoke the specified action or upload to the specified upload destination.
            RobotoConflictException: If a scheduled trigger with the provided name already
                exists in the target organization.
            RobotoLimitExceededException: If the caller has exceeded their organization's
                maximum action timeout limit (in minutes).

        Examples:
            Create an hourly trigger to invoke an analytics action with no explicit inputs:

            >>> from roboto.domain.actions import ScheduledTrigger, TriggerSchedule
            >>> scheduled_trigger = ScheduledTrigger.create(
            ...     name="analytics_action_hourly_trigger",
            ...     action_name="analytics_action",
            ...     schedule=TriggerSchedule.hourly(),
            ... )

            Create a daily trigger to invoke an action that processes CSV files created after a given date:

            >>> from roboto.domain.actions import ScheduledTrigger, TriggerSchedule, InvocationInput
            >>> scheduled_trigger = ScheduledTrigger.create(
            ...     name="csv_processor_daily_trigger",
            ...     action_name="csv_processor",
            ...     schedule=TriggerSchedule.daily(),
            ...     invocation_input=InvocationInput.file_query("created > '2025-04-05' AND path LIKE '%.csv'")
            ... )

        """

        if isinstance(schedule, str):
            trigger_schedule = TriggerSchedule.cron(schedule)
        else:
            trigger_schedule = schedule

        request = CreateScheduledTriggerRequest(
            name=name,
            schedule=trigger_schedule.cron_string,
            action_name=action_name,
            action_owner_id=action_owner_id,
            compute_requirement_overrides=compute_requirement_overrides,
            container_parameter_overrides=container_parameter_overrides,
            enabled=enabled,
            invocation_input=invocation_input,
            invocation_upload_destination=invocation_upload_destination,
            parameter_values=parameter_values,
            timeout=timeout,
        )

        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.post(
            "v1/triggers/scheduled",
            data=request,
            caller_org_id=caller_org_id,
        )

        record = response.to_record(ScheduledTriggerRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls,
        trigger_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> ScheduledTrigger:
        """Fetch a scheduled trigger by its unique ID.

        Args:
            trigger_id: Unique trigger ID.
            owner_org_id: Organization ID which owns the trigger. Defaults to caller's org.
            roboto_client: Roboto client instance. If not provided, defaults to the caller's
                Roboto configuration.

        Returns:
            The ``ScheduledTrigger`` with the provided unique ID.

        Raises:
            RobotoNotFoundException: If no scheduled trigger exists with the provided ID in the
                target organization.
            RobotoUnauthorizedException: If the caller is not a member of the trigger's
                target organization.
        """

        roboto_client = RobotoClient.defaulted(roboto_client)

        record = roboto_client.get(
            f"v1/triggers/scheduled/id/{trigger_id}",
            owner_org_id=owner_org_id,
        ).to_record(ScheduledTriggerRecord)

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> ScheduledTrigger:
        """Fetch a scheduled trigger by its unique name within an organization.

        Args:
            name: Name of the scheduled trigger.
            owner_org_id: Organization ID which owns the trigger. Defaults to caller's org.
            roboto_client: Roboto client instance. If not provided, defaults to the caller's
                Roboto configuration.

        Returns:
            The ``ScheduledTrigger`` with the provided unique name.

        Raises:
            RobotoNotFoundException: If no scheduled trigger exists with the provided name in the
                target organization.
            RobotoUnauthorizedException: If the caller is not a member of the trigger's
                target organization.
        """

        roboto_client = RobotoClient.defaulted(roboto_client)

        record = roboto_client.get(
            f"v1/triggers/scheduled/{name}",
            owner_org_id=owner_org_id,
        ).to_record(ScheduledTriggerRecord)

        return cls(record=record, roboto_client=roboto_client)

    def __init__(
        self,
        record: ScheduledTriggerRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, ScheduledTrigger):
            return self.__record == other.__record

        return False

    def __repr__(self) -> str:
        return "ScheduledTrigger(" + self.__record.model_dump_json(indent=2) + ")"

    @property
    def action_reference(self) -> ActionReference:
        """Reference to the action this trigger invokes."""

        return self.__record.action

    @property
    def compute_requirement_overrides(self) -> typing.Optional[ComputeRequirements]:
        """Optional compute requirement overrides."""

        return self.__record.compute_requirement_overrides

    @property
    def container_parameter_overrides(self) -> typing.Optional[ContainerParameters]:
        """Optional container parameter overrides."""

        return self.__record.container_parameter_overrides

    @property
    def created(self) -> datetime.datetime:
        """Creation time for this scheduled trigger."""

        return self.__record.created

    @property
    def created_by(self) -> str:
        """User who created this scheduled trigger."""

        return self.__record.created_by

    @property
    def enabled(self) -> bool:
        """True if this scheduled trigger is enabled."""

        return self.__record.enabled

    @property
    def invocation_input(self) -> typing.Optional[InvocationInput]:
        """Optional input specification for action invocations."""

        return self.__record.invocation_input

    @property
    def invocation_upload_destination(
        self,
    ) -> typing.Optional[InvocationUploadDestination]:
        """Optional upload destination for action invocation outputs."""

        return self.__record.invocation_upload_destination

    @property
    def name(self) -> str:
        """This trigger's name, unique among scheduled triggers in the org."""

        return self.__record.name

    @property
    def org_id(self) -> str:
        """Organization ID which owns this scheduled trigger."""

        return self.__record.org_id

    @property
    def parameter_values(self) -> typing.Optional[dict[str, typing.Any]]:
        """Optional action parameter values."""

        return self.__record.parameter_values

    @property
    def record(self) -> ScheduledTriggerRecord:
        """Wire-transmissible representation of this scheduled trigger."""

        return self.__record

    @property
    def schedule(self) -> str:
        """Invocation schedule for the target action."""

        return self.__record.schedule

    @property
    def timeout(self) -> typing.Optional[int]:
        """Optional invocation timeout, in minutes."""

        return self.__record.timeout

    @property
    def trigger_id(self) -> str:
        """Unique ID of the scheduled trigger."""

        return self.__record.trigger_id

    @property
    def modified(self) -> datetime.datetime:
        """Last modification time for this scheduled trigger."""

        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """User who last modified this scheduled trigger."""

        return self.__record.modified_by

    def delete(self) -> None:
        """Delete this scheduled trigger."""

        self.__roboto_client.delete(
            f"v1/triggers/scheduled/id/{self.trigger_id}",
            owner_org_id=self.org_id,
        )

    def disable(self) -> None:
        """Disable this scheduled trigger.

        If the trigger is already disabled, the call has no effect.

        Any currently running scheduled invocations will proceed to completion,
        but no new scheduled invocations will occur, unless and until the trigger
        is re-enabled.
        """

        if self.enabled:
            self.update(enabled=False)

    def enable(self) -> bool:
        """Enable this scheduled trigger.

        If the trigger is already enabled, the call has no effect.

        The total number of active triggers within an organization is subject
        to a tier-specific limit. If this operation results in the limit
        being exceeded, this trigger will remain disabled.

        Returns:
            ``True`` if the trigger is now enabled, ``False`` otherwise.
        """

        if not self.enabled:
            self.update(enabled=True)

        return self.enabled

    def get_action(self) -> Action:
        """Get the target :py:class:`~roboto.domain.actions.Action` for this scheduled trigger.

        Returns:
            The action this trigger invokes on a recurring schedule.
        """

        return Action.from_name(
            name=self.action_reference.name,
            owner_org_id=self.action_reference.owner,
            roboto_client=self.__roboto_client,
        )

    def get_evaluations(
        self,
    ) -> collections.abc.Generator[TriggerEvaluationRecord, None, None]:
        """Get the evaluation history for this scheduled trigger.

        Under normal circumstances, this trigger's target action will simply
        be invoked on the configured schedule, for as long as the trigger is enabled.
        However, it's possible that an error occurs when attempting to invoke the
        action. In either case, a trigger evaluation record is created to capture
        the details of what happened.

        Returns:
            A generator that yields :py:class:`~roboto.domain.actions.TriggerEvaluationRecord`
            instances, ordered by descending evaluation start time.
        """

        query_params: dict[str, typing.Any] = {
            "limit": 100,
            "trigger_type": TriggerType.Scheduled.value,
        }

        page_token: typing.Optional[str] = None
        while True:
            if page_token:
                query_params["page_token"] = page_token

            result_page = self.__roboto_client.get(
                f"v1/triggers/{self.name}/evaluations",
                query=query_params,
                owner_org_id=self.org_id,
            ).to_paginated_list(TriggerEvaluationRecord)

            for record in result_page.items:
                yield record

            if result_page.next_token:
                page_token = result_page.next_token
            else:
                break

    def get_invocations(self) -> collections.abc.Generator[Invocation, None, None]:
        """Get the scheduled invocations initiated by this trigger, if any.

        Returns:
            A generator that yields :py:class:`~roboto.domain.actions.Invocation`
            instances for any scheduled invocations kicked off by this trigger.
            The invocations are ordered from most to least recently created.
        """

        query_spec = QuerySpecification(
            condition=Condition(
                field="provenance.source.source_id",
                comparator=Comparator.Equals,
                value=self.trigger_id,
            ),
            sort_by="created",
            sort_direction=SortDirection.Descending,
            limit=100,
        )

        yield from Invocation.query(
            query_spec,
            owner_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def update(
        self,
        action_name: typing.Union[str, NotSetType] = NotSet,
        action_owner_id: typing.Union[str, NotSetType] = NotSet,
        compute_requirement_overrides: typing.Union[
            typing.Optional[ComputeRequirements], NotSetType
        ] = NotSet,
        container_parameter_overrides: typing.Union[
            typing.Optional[ContainerParameters], NotSetType
        ] = NotSet,
        enabled: typing.Union[bool, NotSetType] = NotSet,
        invocation_input: typing.Union[
            typing.Optional[InvocationInput], NotSetType
        ] = NotSet,
        invocation_upload_destination: typing.Union[
            typing.Optional[InvocationUploadDestination], NotSetType
        ] = NotSet,
        parameter_values: typing.Union[
            typing.Optional[dict[str, typing.Any]], NotSetType
        ] = NotSet,
        schedule: typing.Union[str, TriggerSchedule, NotSetType] = NotSet,
        timeout: typing.Union[typing.Optional[int], NotSetType] = NotSet,
    ) -> ScheduledTrigger:
        """Update this scheduled trigger.

        Changing the action associated with this trigger, or the default upload destination,
        are subject to authorization checks. Enabling the trigger or changing the target
        action's timeout are subject to tier-specific organization limit checks.

        Per Roboto convention, the sentinel value ``NotSet`` is the default for all
        arguments to this call, indicating that the corresponding trigger attribute should
        not be updated. The value ``None``, on the other hand, indicates that the relevant trigger
        attribute should be set to ``None`` (i.e. cleared).

        Args:
            action_name: Name of the target action to associate with this trigger.
            action_owner_id: Organization ID that owns the target action.
            compute_requirement_overrides: Optional compute requirement overrides for
                action invocations.
            container_parameter_overrides: Optional container parameter overrides for
                action invocations.
            enabled: Whether the trigger should be active immediately after creation.
            invocation_input: Optional input specification to be used for all scheduled
                action invocations.
            invocation_upload_destination: Optional upload destination for invocation
                outputs.
            parameter_values: Optional parameter values to pass to the action when invoked.
            schedule: Recurring schedule for the trigger, e.g. hourly.
            timeout: Optional timeout override for action invocations, in minutes.

        Returns:
            This trigger with any updates applied.

        Raises:
            ValueError: If request parameters have invalid values, e.g. a negative timeout.
            RobotoInvalidRequestException: If the request cannot be satisfied as provided.
            RobotoUnauthorizedException: If the caller lacks permission to invoke the
                specified action or upload to the specified upload destination.
            RobotoLimitExceededException: If the caller has exceeded their organization's
                maximum action timeout limit (in minutes).
        """

        trigger_schedule: typing.Union[str, NotSetType] = NotSet
        if is_set(schedule):
            if isinstance(schedule, str):
                trigger_schedule = TriggerSchedule.cron(schedule).cron_string
            elif isinstance(schedule, TriggerSchedule):
                trigger_schedule = schedule.cron_string

        request = remove_not_set(
            UpdateScheduledTriggerRequest(
                action_name=action_name,
                action_owner_id=action_owner_id,
                compute_requirement_overrides=compute_requirement_overrides,
                container_parameter_overrides=container_parameter_overrides,
                enabled=enabled,
                invocation_input=invocation_input,
                invocation_upload_destination=invocation_upload_destination,
                parameter_values=parameter_values,
                schedule=trigger_schedule,
                timeout=timeout,
            )
        )

        record = self.__roboto_client.put(
            f"v1/triggers/scheduled/id/{self.trigger_id}",
            data=request,
            owner_org_id=self.org_id,
        ).to_record(ScheduledTriggerRecord)

        self.__record = record
        return self
