# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import typing
import warnings

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
from .trigger import _LEGACY_TRIGGER_API_VERSION_HEADERS
from .trigger_record import (
    TriggerEvaluationRecord,
)
from .trigger_view import TriggerType


class TriggerSchedule:
    """A recurring schedule for a ``ScheduledTrigger``, as a cron expression in UTC.

    Build one with ``cron``, which checks the expression, or with ``hourly``, ``daily``, ``weekly`` or ``monthly``.
    The constructor does not check the expression it is given.
    """

    __cron_string: str

    @classmethod
    def cron(cls, cron_string: str) -> TriggerSchedule:
        """Build a schedule for a cron expression, after checking that the expression is valid.

        Args:
            cron_string: Five-field cron expression, evaluated in UTC, such as ``"*/30 * * * *"`` for every 30
                minutes.

        Raises:
            ValueError: ``cron_string`` is not a valid cron expression.
        """

        _ = cron_converter.Cron(cron_string)  # Raises ValueError for an invalid expression.
        return cls(cron_string)

    @classmethod
    def hourly(cls) -> TriggerSchedule:
        """Build a schedule for every hour, on the hour."""

        return cls("0 * * * *")

    @classmethod
    def daily(cls) -> TriggerSchedule:
        """Build a schedule for every day at midnight UTC."""

        return cls("0 0 * * *")

    @classmethod
    def weekly(cls) -> TriggerSchedule:
        """Build a schedule for every Sunday at midnight UTC."""

        return cls("0 0 * * 0")

    @classmethod
    def monthly(cls) -> TriggerSchedule:
        """Build a schedule for the first day of every month, at midnight UTC."""

        return cls("0 0 1 * *")

    def __init__(self, cron_string: str) -> None:
        self.__cron_string = cron_string

    @property
    def cron_string(self) -> str:
        """Cron expression of the schedule, evaluated in UTC."""

        return self.__cron_string


class ScheduledTrigger:
    """Deprecated. A trigger that invokes an action on a recurring schedule, such as hourly or daily.

    Use :py:class:`~roboto.domain.triggers.Trigger` instead, which reads and edits every trigger; pass ``schedule``
    to :py:meth:`~roboto.domain.triggers.Trigger.create` to create one that runs on a schedule. This class will be
    removed, and constructing one emits a ``DeprecationWarning``. It reads and edits only triggers that run on a
    schedule and invoke one action: to this class, a trigger with several targets, or with an agent or Slack target,
    does not exist.

    The schedule is a five-field cron expression evaluated in UTC; ``TriggerSchedule`` builds common ones. Each time
    the schedule comes due, the trigger invokes the latest version of its action with the trigger's input, parameter
    values, and overrides.
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
        invocation_upload_destination: typing.Optional[InvocationUploadDestination] = None,
        parameter_values: typing.Optional[dict[str, typing.Any]] = None,
        timeout: typing.Optional[int] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> ScheduledTrigger:
        """Create a scheduled trigger.

        When ``enabled`` is ``True`` and the organization is already at its limit on enabled triggers, Roboto creates
        the trigger disabled rather than failing. Check ``enabled`` on the result.

        Args:
            name: Human-readable name of the trigger, unique within its organization. At most 256 characters, of
                letters, digits, underscores, and hyphens.
            schedule: When the trigger invokes the action: a five-field cron expression evaluated in UTC, or a
                ``TriggerSchedule``.
            action_name: Name of the action to invoke. The trigger invokes the action's latest version.
            action_owner_id: ID of the organization that owns the action. ``None`` uses the organization the trigger
                is created in. An action another organization owns must be published in Action Hub.
            compute_requirement_overrides: Overrides of the action's compute requirements for each invocation.
                ``None`` uses the action's own.
            container_parameter_overrides: Overrides of the action's container parameters for each invocation.
                ``None`` uses the action's own.
            enabled: Whether the trigger invokes the action on its schedule once it is created.
            invocation_input: Query that selects each invocation's input data when the invocation runs. ``None``
                selects none.
            invocation_upload_destination: Where each invocation uploads its output files, which must be a dataset.
                ``None`` sets none.
            parameter_values: Values of the action's parameters, keyed by parameter name. ``None`` passes none.
            timeout: Maximum run time of each invocation, in minutes. ``None`` uses the action's own.
            caller_org_id: Organization to create the trigger in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new scheduled trigger.

        Raises:
            ValueError: ``schedule`` is not a valid cron expression, ``name`` is longer than 256 characters or
                contains characters other than letters, digits, underscores, and hyphens, or ``timeout`` is negative.
            RobotoNotFoundException: The organization that owns the action has no action named ``action_name``.
            RobotoUnauthorizedException: The action belongs to another organization and is not published in Action
                Hub, or the caller may not upload files to ``invocation_upload_destination``.
            RobotoInvalidRequestException: ``invocation_upload_destination`` is not a dataset, or
                ``container_parameter_overrides`` is set for an action that inherits its container from another
                action.
            RobotoConflictException: Another trigger in the organization has this name.
            RobotoLimitExceededException: ``timeout`` exceeds the organization's maximum action timeout.

        Examples:
            Create an hourly trigger to invoke an analytics action with no explicit inputs:

            >>> from roboto.domain.actions import ScheduledTrigger, TriggerSchedule
            >>> scheduled_trigger = ScheduledTrigger.create(
            ...     name="analytics_action_hourly_trigger",
            ...     action_name="analytics_action",
            ...     schedule=TriggerSchedule.hourly(),
            ... )

            Create a daily trigger whose invocations each take the CSV files created after a given date:

            >>> from roboto.domain.actions import ScheduledTrigger, TriggerSchedule, InvocationInput
            >>> scheduled_trigger = ScheduledTrigger.create(
            ...     name="csv_processor_daily_trigger",
            ...     action_name="csv_processor",
            ...     schedule=TriggerSchedule.daily(),
            ...     invocation_input=InvocationInput.file_query("created > '2025-04-05' AND path LIKE '%.csv'"),
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
        """Fetch a scheduled trigger by its ID.

        Args:
            trigger_id: Unique ID of the trigger.
            owner_org_id: Organization that owns the trigger. Roboto finds the trigger by its ID alone, so this can
                be left out.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No trigger has this ID, or the trigger does not run on a schedule, or it has
                more than one target or a target that does not invoke an action.
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
        """Fetch a scheduled trigger by its name, which is unique within its organization.

        Args:
            name: Name of the trigger.
            owner_org_id: Organization that owns the trigger. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no trigger with this name, or the trigger does not run on a
                schedule, or it has more than one target or a target that does not invoke an action.
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
        warnings.warn(
            "roboto.domain.actions.ScheduledTrigger is the legacy trigger model and will be removed; "
            "use roboto.domain.triggers.Trigger.",
            DeprecationWarning,
            stacklevel=2,
        )
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
        """Action the trigger invokes."""

        return self.__record.action

    @property
    def compute_requirement_overrides(self) -> typing.Optional[ComputeRequirements]:
        """Overrides of the action's compute requirements for each invocation, or ``None`` to use the action's own."""

        return self.__record.compute_requirement_overrides

    @property
    def container_parameter_overrides(self) -> typing.Optional[ContainerParameters]:
        """Overrides of the action's container parameters for each invocation, or ``None`` to use the action's own."""

        return self.__record.container_parameter_overrides

    @property
    def created(self) -> datetime.datetime:
        """Time the scheduled trigger was created."""

        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the scheduled trigger."""

        return self.__record.created_by

    @property
    def enabled(self) -> bool:
        """Whether the trigger invokes the action on its schedule."""

        return self.__record.enabled

    @property
    def invocation_input(self) -> typing.Optional[InvocationInput]:
        """Input each invocation receives, or ``None`` if invocations take no input."""

        return self.__record.invocation_input

    @property
    def invocation_upload_destination(
        self,
    ) -> typing.Optional[InvocationUploadDestination]:
        """Where each invocation uploads its output files, or ``None`` if the trigger sets no destination."""

        return self.__record.invocation_upload_destination

    @property
    def name(self) -> str:
        """Human-readable name of the scheduled trigger, unique within its organization."""

        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the scheduled trigger."""

        return self.__record.org_id

    @property
    def parameter_values(self) -> typing.Optional[dict[str, typing.Any]]:
        """Values for the action's parameters, keyed by parameter name, or ``None`` if the trigger sets none."""

        return self.__record.parameter_values

    @property
    def record(self) -> ScheduledTriggerRecord:
        """Record of the scheduled trigger that this instance holds.

        ``update`` replaces it with Roboto's response.
        """

        return self.__record

    @property
    def schedule(self) -> str:
        """Cron expression, in UTC, for when the trigger invokes the action, such as ``"0 * * * *"`` for every hour."""

        return self.__record.schedule

    @property
    def timeout(self) -> typing.Optional[int]:
        """Timeout of each invocation, in minutes, or ``None`` to use the action's own."""

        return self.__record.timeout

    @property
    def trigger_id(self) -> str:
        """Unique ID of the scheduled trigger."""

        return self.__record.trigger_id

    @property
    def modified(self) -> datetime.datetime:
        """Time the scheduled trigger was last modified."""

        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the scheduled trigger.

        :py:attr:`~roboto.domain.actions.ScheduledTriggerRecord.modified_by` says when it is Roboto's own system user.
        """

        return self.__record.modified_by

    def delete(self) -> None:
        """Delete the scheduled trigger.

        Deleting a scheduled trigger that no longer exists succeeds and changes nothing.
        """

        self.__roboto_client.delete(
            f"v1/triggers/scheduled/id/{self.trigger_id}",
            owner_org_id=self.org_id,
        )

    def disable(self) -> None:
        """Disable the scheduled trigger, so it starts no invocations until it is enabled again.

        Invocations already running continue to completion. A trigger that is already disabled, as far as this
        instance's record shows, is left as it is without a request; otherwise this calls ``update`` with
        ``enabled=False``.
        """

        if self.enabled:
            self.update(enabled=False)

    def enable(self) -> bool:
        """Enable the scheduled trigger, so it invokes the action on its schedule.

        A trigger that is already enabled, as far as this instance's record shows, is left as it is without a
        request; otherwise this calls ``update`` with ``enabled=True``.

        Returns:
            ``True``. When the trigger cannot be enabled, the call raises instead of returning ``False``.

        Raises:
            RobotoLimitExceededException: The organization is already at its limit on enabled triggers.
            RobotoNotFoundException: The action the trigger invokes no longer exists.
        """

        if not self.enabled:
            self.update(enabled=True)

        return self.enabled

    def get_action(self) -> Action:
        """Fetch the latest version of the :py:class:`~roboto.domain.actions.Action` the trigger invokes.

        Raises:
            RobotoNotFoundException: The action no longer exists.
        """

        return Action.from_name(
            name=self.action_reference.name,
            owner_org_id=self.action_reference.owner,
            roboto_client=self.__roboto_client,
        )

    def get_evaluations(
        self,
    ) -> collections.abc.Generator[TriggerEvaluationRecord, None, None]:
        """Yield a record of each time the trigger came due and tried to invoke the action, newest first.

        Each :py:class:`~roboto.domain.actions.TriggerEvaluationRecord` says when the attempt started and ended and
        whether it invoked the action. Records are fetched 100 at a time, as the iteration reaches them.
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
                headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
            ).to_paginated_list(TriggerEvaluationRecord)

            for record in result_page.items:
                yield record

            if result_page.next_token:
                page_token = result_page.next_token
            else:
                break

    def get_invocations(self) -> collections.abc.Generator[Invocation, None, None]:
        """Yield the :py:class:`~roboto.domain.actions.Invocation` objects the trigger started, newest first.

        Invocations are fetched 100 at a time, as the iteration reaches them.
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
        compute_requirement_overrides: typing.Union[typing.Optional[ComputeRequirements], NotSetType] = NotSet,
        container_parameter_overrides: typing.Union[typing.Optional[ContainerParameters], NotSetType] = NotSet,
        enabled: typing.Union[bool, NotSetType] = NotSet,
        invocation_input: typing.Union[typing.Optional[InvocationInput], NotSetType] = NotSet,
        invocation_upload_destination: typing.Union[typing.Optional[InvocationUploadDestination], NotSetType] = NotSet,
        parameter_values: typing.Union[typing.Optional[dict[str, typing.Any]], NotSetType] = NotSet,
        schedule: typing.Union[str, TriggerSchedule, NotSetType] = NotSet,
        timeout: typing.Union[typing.Optional[int], NotSetType] = NotSet,
    ) -> ScheduledTrigger:
        """Update the scheduled trigger's properties.

        Each argument left unset (``NotSet``) leaves that property unchanged.

        Args:
            action_name: Name of the action to invoke. The action's owner stays the same unless ``action_owner_id`` is
                also set.
            action_owner_id: ID of the organization that owns the action. An action another organization owns must be
                published in Action Hub.
            compute_requirement_overrides: Overrides of the action's compute requirements for each invocation.
                ``None`` clears the override, so invocations use the action's own.
            container_parameter_overrides: Overrides of the action's container parameters for each invocation.
                ``None`` clears the override, so invocations use the action's own.
            enabled: Whether the trigger invokes the action on its schedule.
            invocation_input: Query that selects each invocation's input data when the invocation runs. ``None``
                clears it.
            invocation_upload_destination: Where each invocation uploads its output files, which must be a dataset.
                ``None`` clears it.
            parameter_values: Values of the action's parameters, keyed by parameter name. ``None`` clears them.
            schedule: When the trigger invokes the action: a five-field cron expression evaluated in UTC, or a
                ``TriggerSchedule``.
            timeout: Maximum run time of each invocation, in minutes. ``None`` clears the override, so invocations
                use the action's own.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            ValueError: ``schedule`` is not a valid cron expression, or ``timeout`` is negative.
            RobotoNotFoundException: The organization that owns the action has no action with the trigger's action name.
            RobotoUnauthorizedException: The action belongs to another organization and is not published in Action
                Hub, or the caller may not upload files to ``invocation_upload_destination``.
            RobotoInvalidRequestException: ``invocation_upload_destination`` is not a dataset, or the action inherits
                its container from another action and the trigger sets container parameter overrides.
            RobotoLimitExceededException: The update enables the trigger and the organization is already at its limit
                on enabled triggers, or ``timeout`` exceeds the organization's maximum action timeout.
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
