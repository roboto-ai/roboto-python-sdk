# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...http import RobotoClient
from ...query import ConditionType
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ..platform_events import (
    OncePer,
    PlatformEvent,
    PlatformEventType,
)
from .dispatch import TriggerDispatchRecord
from .dry_run import (
    TriggerDryRunRequest,
    TriggerDryRunResponse,
)
from .operations import (
    CreateTriggerRequest,
    UpdateTriggerRequest,
)
from .record import TriggerRecord
from .samples import (
    PlatformEventSample,
    PlatformEventSamplesResponse,
)
from .sources import (
    EventSubscription,
    Schedule,
    TriggerSource,
)
from .targets import TriggerTargetSpec


class Trigger:
    """A trigger: a rule that runs targets when a platform event matches it, or on a schedule.

    A trigger has one firing source (a subscription to platform events, or a cron schedule), an optional condition
    over the variables a firing exposes, and one or more targets: invoking an action, starting an agent, or sending a
    Slack message. Its targets run as its organization's service user. This class reads every trigger, including
    those created with the deprecated :py:class:`~roboto.domain.actions.Trigger`.

    Get a ``Trigger`` from ``create``, ``from_id``, ``from_name``, or ``list``. To wrap a
    :py:class:`~roboto.domain.triggers.TriggerRecord` already fetched from Roboto, build a ``Trigger`` from it
    directly. Each instance holds a copy of the trigger's record, which ``update`` and the methods that enable or
    disable the trigger replace with Roboto's response.

    Args:
        record: Record of the trigger.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
    """

    __record: TriggerRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        targets: list[TriggerTargetSpec],
        *,
        events: typing.Optional[list[PlatformEventType]] = None,
        once_per: typing.Optional[OncePer] = None,
        schedule: typing.Optional[str] = None,
        fires_on: typing.Optional[TriggerSource] = None,
        condition: typing.Optional[ConditionType] = None,
        enabled: bool = True,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Trigger":
        """Create a trigger.

        Give exactly one firing source: ``events`` together with ``once_per``, ``schedule``, or ``fires_on``. If
        ``enabled`` is ``True`` and the organization is at its limit of active triggers, Roboto creates the trigger
        disabled.

        Args:
            name: Human-readable name of the trigger, unique within its organization: letters, digits, underscores
                and hyphens, at most 256 characters (:py:const:`~roboto.domain.triggers.MAX_TRIGGER_NAME_LENGTH`).
            targets: Targets to run when the trigger fires. At least one, each with a ``target_id`` unique within the
                trigger.
            events: Platform event types to subscribe to. At least one. Requires ``once_per``.
            once_per: What the trigger runs each target at most once for, such as each platform event or each
                dataset. Every event type in ``events`` must support it. Requires ``events``.
            schedule: Five-field cron expression to fire on, evaluated in UTC, such as ``"0 9 * * 1"`` for 09:00 UTC
                every Monday.
            fires_on: Firing source, an :py:class:`~roboto.domain.triggers.EventSubscription` or a
                :py:class:`~roboto.domain.triggers.Schedule`, in place of ``events`` and ``once_per`` or ``schedule``.
            condition: Condition over the variables a firing exposes, such as fields under ``dataset.``. The trigger
                runs its targets only when the condition holds. ``None`` runs them on every firing.
            enabled: Whether the trigger is active once created.
            caller_org_id: Organization to create the trigger in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new trigger.

        Raises:
            ValueError: The arguments give no firing source or more than one, or give only one of ``events`` and
                ``once_per``.
            pydantic.ValidationError: ``name`` has a character other than a letter, digit, underscore or hyphen, or
                is longer than 256 characters, or ``schedule`` is not a valid cron expression.
            RobotoInvalidRequestException: The trigger's parts do not fit together, such as a condition that names a
                variable some subscribed platform event does not expose, or a target names an agent or Slack channel
                the organization does not have.
            RobotoNotFoundException: A target names an action that does not exist.
            RobotoUnauthorizedException: A target names an action in another organization that is not in the Action
                Hub, or a dataset to upload outputs to that the caller may not upload to.
            RobotoLimitExceededException: A target's timeout exceeds the organization's limit for action timeouts.
            RobotoConflictException: Another trigger in the organization already has ``name``.

        Examples:
            Start an agent each time a dataset gains a tag:

            >>> from roboto.domain.platform_events import OncePer, PlatformEventType
            >>> from roboto.domain.triggers import StartAgentTarget, Trigger
            >>> trigger = Trigger.create(
            ...     name="analyze-tagged-datasets",
            ...     targets=[StartAgentTarget(target_id="analyze", agent_id="agt_12345")],
            ...     events=[PlatformEventType.DatasetTagAdded],
            ...     once_per=OncePer.Occurrence,
            ... )

            Post to Slack every Monday at 09:00 UTC:

            >>> from roboto.domain.triggers import SendSlackMessageTarget
            >>> weekly = Trigger.create(
            ...     name="weekly-status",
            ...     targets=[SendSlackMessageTarget(target_id="post", channel_id="C0123", text="Weekly check-in")],
            ...     schedule="0 9 * * 1",
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateTriggerRequest(
            name=name,
            fires_on=_source_from_parts(fires_on=fires_on, events=events, once_per=once_per, schedule=schedule),
            condition=condition,
            targets=targets,
            enabled=enabled,
        )
        response = roboto_client.post("v1/triggers", data=request, caller_org_id=caller_org_id)
        return cls(response.to_record(TriggerRecord), roboto_client)

    @classmethod
    def from_id(
        cls,
        trigger_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Trigger":
        """Fetch a trigger by ID.

        Finds any trigger, including one created with the deprecated :py:class:`~roboto.domain.actions.Trigger`.

        Args:
            trigger_id: ID of the trigger, beginning with ``tr_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No trigger has this ID.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_id("tr_12345")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get(f"v1/triggers/id/{trigger_id}")
        return cls(response.to_record(TriggerRecord), roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Trigger":
        """Fetch a trigger by name.

        Trigger names are unique within an organization, so a name and an organization identify one trigger. Finds
        any trigger, including one created with the deprecated :py:class:`~roboto.domain.actions.Trigger`.

        Args:
            name: Name of the trigger.
            owner_org_id: Organization that owns the trigger. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no trigger with this name.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("weekly-status")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get(f"v1/triggers/{name}", owner_org_id=owner_org_id)
        return cls(response.to_record(TriggerRecord), roboto_client)

    @classmethod
    def platform_event_samples(
        cls,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> dict[PlatformEventType, PlatformEventSample]:
        """Fetch a sample of every platform event type, showing what a trigger's condition and targets can read.

        Each sample holds the platform event, the record under every root a condition or target template may read
        for that event type, and every ``<root>.<path>`` a condition field or ``{{ }}`` placeholder may name. Use a
        sample to see what a condition or template resolves to before writing it. The values are made up and name
        nothing that exists in Roboto.

        Event types that this version of the SDK's :py:class:`~roboto.domain.platform_events.PlatformEventType` does
        not name, such as one Roboto added after this version was released, are left out. Upgrade the SDK to get their
        samples.

        Args:
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            Sample of each platform event type, keyed by type.

        Examples:
            >>> from roboto.domain.platform_events import PlatformEventType
            >>> from roboto.domain.triggers import Trigger
            >>> samples = Trigger.platform_event_samples()
            >>> samples[PlatformEventType.FileUploaded].paths[:3]
            ['envelope.id', 'envelope.source', 'envelope.subject']
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get("v1/triggers/events/samples")
        return response.to_record(PlatformEventSamplesResponse).samples

    @classmethod
    def list(
        cls,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Trigger", None, None]:
        """Yield every trigger in an organization, newest first.

        Includes triggers that fire on platform events and on a schedule, and those created with the deprecated
        :py:class:`~roboto.domain.actions.Trigger`.

        Args:
            owner_org_id: Organization whose triggers to list. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> for trigger in Trigger.list():
            ...     print(trigger.name, trigger.enabled)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get("v1/triggers", owner_org_id=owner_org_id)
        for record in response.to_paginated_list(TriggerRecord).items:
            yield cls(record, roboto_client)

    def __init__(
        self,
        record: TriggerRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def condition(self) -> typing.Optional[ConditionType]:
        """Condition over the variables a firing exposes, which must hold for the trigger to run its targets.

        ``None`` runs the targets on every firing. :py:attr:`~roboto.domain.triggers.TriggerRecord.condition`
        describes its format.
        """
        return self.__record.condition

    @property
    def enabled(self) -> bool:
        """Whether the trigger is enabled. A disabled trigger does not fire."""
        return self.__record.enabled

    @property
    def engine(self) -> str:
        """Trigger model Roboto evaluates the trigger with, ``"v2"`` or ``"v1"``.

        :py:attr:`~roboto.domain.triggers.TriggerRecord.engine` describes the values.
        """
        return self.__record.engine

    @property
    def events(self) -> typing.Optional[typing.List[PlatformEventType]]:
        """Platform event types the trigger subscribes to, or ``None`` for a schedule-fired trigger."""
        source = self.__record.fires_on
        return list(source.events) if isinstance(source, EventSubscription) else None

    @property
    def fires_on(self) -> TriggerSource:
        """What makes the trigger fire: a subscription to platform events, or a schedule.

        :py:attr:`~roboto.domain.triggers.TriggerRecord.fires_on` describes the values.
        """
        return self.__record.fires_on

    @property
    def name(self) -> str:
        """Human-readable name of the trigger, unique within its organization."""
        return self.__record.name

    @property
    def once_per(self) -> OncePer:
        """What the trigger runs each target at most once for.

        Always :py:attr:`~roboto.domain.platform_events.OncePer.Occurrence` for a schedule-fired trigger, which fires
        once per scheduled minute.
        """
        return self.__record.fires_on.once_per

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the trigger."""
        return self.__record.org_id

    @property
    def record(self) -> TriggerRecord:
        """Record of the trigger that this instance holds."""
        return self.__record

    @property
    def schedule(self) -> typing.Optional[str]:
        """Cron expression the trigger fires on, evaluated in UTC.

        ``None`` for a trigger that fires on platform events.
        """
        source = self.__record.fires_on
        return source.cron if isinstance(source, Schedule) else None

    @property
    def targets(self) -> typing.List[TriggerTargetSpec]:
        """Targets the trigger runs when it fires."""
        return self.__record.targets

    @property
    def trigger_id(self) -> str:
        """Unique ID of the trigger."""
        return self.__record.trigger_id

    def delete(self) -> None:
        """Delete this trigger and its dispatch history.

        Deleting a trigger that no longer exists succeeds and changes nothing.

        Raises:
            RobotoInvalidRequestException: Roboto or an ingestion rule manages the trigger (see
                :py:attr:`~roboto.domain.triggers.TriggerRecord.managed_by`). Disable a trigger Roboto manages
                instead, or delete the ingestion rule that owns the trigger.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("weekly-status")
            >>> trigger.delete()
        """
        self.__roboto_client.delete(f"v1/triggers/id/{self.trigger_id}")

    def disable(self) -> "Trigger":
        """Disable this trigger, so it stops firing.

        A trigger an ingestion rule manages cannot be disabled here; change the rule instead, such as by turning its
        auto-ingest off. It calls ``update``, whose failures also apply.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("weekly-status").disable()
        """
        return self.update(enabled=False)

    def dispatches(
        self,
        limit: int = 100,
    ) -> collections.abc.Generator[TriggerDispatchRecord, None, None]:
        """Yield this trigger's dispatches, most recently claimed first, fetching them a page at a time.

        A dispatch is one attempt to run one of the trigger's targets for a platform event that matched the trigger,
        so a trigger that has never matched a platform event has none. When Roboto disables the trigger itself, such
        as after a target's action was deleted, it also records a failed dispatch whose ``status_detail`` says why.

        Args:
            limit: Maximum number of dispatches per request.

        Raises:
            RobotoNotFoundException: The trigger no longer exists. It surfaces on the first iteration.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("weekly-status")
            >>> for dispatch in trigger.dispatches():
            ...     print(dispatch.target_id, dispatch.status, dispatch.status_detail)
        """
        page_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {"limit": limit}
            if page_token is not None:
                query["page_token"] = page_token
            paginated = self.__roboto_client.get(
                f"v1/triggers/id/{self.trigger_id}/dispatches",
                query=query,
            ).to_paginated_list(TriggerDispatchRecord)
            yield from paginated.items
            if not paginated.next_token:
                break
            page_token = paginated.next_token

    def dry_run(
        self,
        event: typing.Optional[PlatformEvent] = None,
        dataset_id: typing.Optional[str] = None,
        file_id: typing.Optional[str] = None,
        invocation_id: typing.Optional[str] = None,
        event_id: typing.Optional[str] = None,
        event_type: typing.Optional[PlatformEventType] = None,
        scheduled_for: typing.Optional[datetime.datetime] = None,
    ) -> TriggerDryRunResponse:
        """Report whether this trigger would run its targets for a platform event, without running any.

        For a trigger that fires on platform events, give a complete ``event``, or one of ``dataset_id``,
        ``file_id``, ``invocation_id`` and ``event_id`` for Roboto to synthesize a platform event from. For a
        schedule-fired trigger, give ``scheduled_for`` to pick the minute, or nothing to use the schedule's next
        occurrence.

        The response lists the trigger's gates in the order Roboto checks them when the trigger fires: subscribed,
        enabled, condition, target prefilter, and already fired. The first gate that fails is why the trigger would
        not fire, and the condition gate shows the value the event supplied for each field the condition compares.

        Args:
            event: Platform event to evaluate as given. It must belong to the trigger's organization, as must every
                entity it names.
            dataset_id: ID of a dataset to synthesize a platform event about.
            file_id: ID of a file to synthesize a platform event about.
            invocation_id: ID of an invocation to synthesize a platform event about.
            event_id: ID of an event to synthesize a platform event about:
                :py:attr:`~roboto.domain.platform_events.PlatformEventType.EventCreated` for a dataset's event, or
                :py:attr:`~roboto.domain.platform_events.PlatformEventType.SessionEventCreated` for a session's event.
            event_type: Type of platform event to synthesize from a ``dataset_id``, ``file_id``, ``invocation_id`` or
                ``event_id``. ``None`` uses the first of the trigger's subscribed event types that the reference can
                produce.
            scheduled_for: Time of the occurrence to synthesize for a schedule-fired trigger, with seconds and smaller
                units dropped. ``None`` synthesizes the schedule's next occurrence.

        Returns:
            Outcome of each gate, and whether the trigger would fire.

        Raises:
            pydantic.ValidationError: ``event`` is given together with another argument, or more than one of
                ``dataset_id``, ``file_id``, ``invocation_id``, ``event_id`` and ``scheduled_for`` is given.
            RobotoInvalidRequestException: ``event`` belongs to another organization; a trigger that fires on platform
                events gets neither ``event`` nor an entity ID, or gets ``scheduled_for``; a schedule-fired trigger gets
                an entity ID; or the entity cannot produce ``event_type``, or any subscribed event type when
                ``event_type`` is ``None``.
            RobotoNotFoundException: The entity, or an entity ``event`` names, is not in the trigger's organization,
                or is an event the caller may not read.

        Examples:
            Check whether a trigger would fire for a dataset:

            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("analyze-tagged-datasets")
            >>> result = trigger.dry_run(dataset_id="ds_12345")
            >>> print(result.verdict)

            Check a schedule-fired trigger's next occurrence:

            >>> weekly = Trigger.from_name("weekly-status")
            >>> weekly.dry_run().would_fire
        """
        request = TriggerDryRunRequest(
            event=event,
            dataset_id=dataset_id,
            file_id=file_id,
            invocation_id=invocation_id,
            event_id=event_id,
            event_type=event_type,
            scheduled_for=scheduled_for,
        )
        response = self.__roboto_client.post(
            f"v1/triggers/id/{self.trigger_id}/dry-run",
            data=request,
        )
        return response.to_record(TriggerDryRunResponse)

    def enable(self) -> "Trigger":
        """Enable this trigger, so it fires again.

        Enabling a disabled trigger checks again that every action, agent and Slack channel its targets name still
        exists, and fails while one does not, such as after Roboto disabled the trigger because a target's action was
        deleted. It calls ``update``, whose failures also apply.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("weekly-status").enable()
        """
        return self.update(enabled=True)

    def set_enabled(self, enabled: bool) -> "Trigger":
        """Enable or disable this trigger.

        It calls ``update``, whose failures also apply.

        Args:
            enabled: Whether to enable the trigger.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("weekly-status").set_enabled(False)
        """
        return self.update(enabled=enabled)

    def to_dict(self) -> dict[str, typing.Any]:
        """Return this trigger's record as a dictionary of JSON-compatible values.

        Returns:
            :py:class:`~roboto.domain.triggers.TriggerRecord` of the trigger, as a JSON-compatible dictionary.

        Examples:
            >>> from roboto.domain.triggers import Trigger
            >>> Trigger.from_name("weekly-status").to_dict()["name"]
            'weekly-status'
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        *,
        name: typing.Union[str, NotSetType] = NotSet,
        fires_on: typing.Union[TriggerSource, NotSetType] = NotSet,
        events: typing.Union[typing.List[PlatformEventType], NotSetType] = NotSet,
        once_per: typing.Union[OncePer, NotSetType] = NotSet,
        schedule: typing.Union[str, NotSetType] = NotSet,
        condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet,
        targets: typing.Union[typing.List[TriggerTargetSpec], NotSetType] = NotSet,
        enabled: typing.Union[bool, NotSetType] = NotSet,
    ) -> "Trigger":
        """Update this trigger.

        A field left unset (``NotSet``) is unchanged. Roboto checks the updated trigger by the same rules as on
        create.

        The firing source is replaced whole. Give ``fires_on``, ``schedule``, or ``events`` and ``once_per``; when
        only one of ``events`` and ``once_per`` is given, the other keeps its current value. ``fires_on`` takes
        precedence over the other three, and ``schedule`` over ``events`` and ``once_per``; the arguments they take
        precedence over are ignored.

        Args:
            name: New human-readable name of the trigger, unique within its organization. Afterward ``from_name``
                finds the trigger only under this name; its ID does not change.
            fires_on: Firing source that replaces the current one.
            events: Platform event types to subscribe to.
            once_per: What the trigger runs each target at most once for. Required with ``events`` to move a
                schedule-fired trigger onto platform events.
            schedule: Five-field cron expression to fire on, evaluated in UTC.
            condition: New condition. ``None`` clears it, so the trigger runs its targets on every firing.
            targets: Targets that replace the current ones. Roboto keeps which entities a target already fired for
                under its ``target_id``, so a target given a new ``target_id`` fires again for them.
            enabled: Whether the trigger is active.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            ValueError: The trigger fires on a schedule, and ``events`` is given without ``once_per``.
            pydantic.ValidationError: ``name`` has a character other than a letter, digit, underscore or hyphen, or
                is longer than 256 characters (:py:const:`~roboto.domain.triggers.MAX_TRIGGER_NAME_LENGTH`), or
                ``schedule`` is not a valid cron expression.
            RobotoNotFoundException: The trigger no longer exists, or a target names an action that does not.
            RobotoInvalidRequestException: The updated trigger's parts do not fit together, a target names an agent
                or Slack channel the organization does not have, or the trigger is managed (see
                :py:attr:`~roboto.domain.triggers.TriggerRecord.managed_by`): a trigger an ingestion rule owns
                changes only through its rule, and one Roboto manages can only be enabled or disabled.
            RobotoUnauthorizedException: A target names an action the organization may not run, or a dataset to
                upload outputs to that the caller may not upload to.
            RobotoLimitExceededException: Enabling the trigger would put the organization over its limit of active
                triggers, or a target's timeout exceeds the organization's limit for action timeouts.
            RobotoConflictException: Another trigger in the organization already has ``name``, or the trigger kept
                changing while Roboto applied the update; retry it.

        Examples:
            Disable a trigger:

            >>> from roboto.domain.triggers import Trigger
            >>> trigger = Trigger.from_name("analyze-tagged-datasets")
            >>> trigger.update(enabled=False)

            Fire on dataset creation instead, keeping its ``once_per``:

            >>> from roboto.domain.platform_events import PlatformEventType
            >>> trigger.update(events=[PlatformEventType.DatasetCreated])

            Clear its condition:

            >>> trigger.update(condition=None)
        """
        new_source: typing.Union[TriggerSource, NotSetType] = fires_on
        if isinstance(new_source, NotSetType) and not all(
            isinstance(part, NotSetType) for part in (events, once_per, schedule)
        ):
            current = self.__record.fires_on
            if not isinstance(schedule, NotSetType):
                new_source = Schedule(cron=schedule)
            else:
                if not isinstance(current, EventSubscription) and isinstance(once_per, NotSetType):
                    raise ValueError(
                        "This trigger fires on a schedule; to make it fire on platform events instead, "
                        "give once_per along with events."
                    )
                current_events = list(current.events) if isinstance(current, EventSubscription) else []
                new_source = EventSubscription(
                    events=current_events if isinstance(events, NotSetType) else events,
                    once_per=current.once_per if isinstance(once_per, NotSetType) else once_per,
                )
        request = remove_not_set(
            UpdateTriggerRequest(
                name=name,
                fires_on=new_source,
                condition=condition,
                targets=targets,
                enabled=enabled,
            )
        )
        response = self.__roboto_client.put(f"v1/triggers/id/{self.trigger_id}", data=request)
        self.__record = response.to_record(TriggerRecord)
        return self


def _source_from_parts(
    *,
    fires_on: typing.Optional[TriggerSource],
    events: typing.Optional[list[PlatformEventType]],
    once_per: typing.Optional[OncePer],
    schedule: typing.Optional[str],
) -> TriggerSource:
    """Build the firing source that ``fires_on``, ``schedule``, or ``events`` with ``once_per`` describes.

    Raises:
        ValueError: The arguments describe no firing source or more than one, or give only one of ``events`` and
            ``once_per``.
    """
    given = [name for name, value in (("fires_on", fires_on), ("schedule", schedule)) if value is not None]
    if events is not None or once_per is not None:
        given.append("events/once_per")
    if len(given) != 1:
        raise ValueError(
            "Provide exactly one firing source: fires_on, schedule, or events together with once_per "
            f"(got {given or 'none'})."
        )
    if fires_on is not None:
        return fires_on
    if schedule is not None:
        return Schedule(cron=schedule)
    if events is None or once_per is None:
        raise ValueError("events and once_per must be given together.")
    return EventSubscription(events=events, once_per=once_per)


__all__ = ["Trigger"]
