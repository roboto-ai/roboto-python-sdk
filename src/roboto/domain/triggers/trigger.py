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
    """A trigger: a firing source (event subscriptions or a schedule), an optional condition, and targets.

    Triggers created through the older ``causes``/``for_each`` API
    (:class:`roboto.domain.actions.Trigger`) are listed and loaded here too, projected
    onto this shape and marked ``engine == "v1"``; they accept a narrower set of edits
    (see :meth:`update`).

    Examples:
        Start an agent whenever a dataset gains a ``ready`` tag:

        >>> from roboto.domain.platform_events import OncePer, PlatformEventType
        >>> from roboto.domain.triggers import StartAgentTarget, Trigger
        >>> trigger = Trigger.create(
        ...     name="analyze-ready-datasets",
        ...     targets=[StartAgentTarget(target_id="analyze", agent_id="ag_abc123")],
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
        """Create a trigger in the caller's org.

        Args:
            name: Trigger name, unique within the org.
            targets: What to dispatch on a match. At least one.
            events: Platform event types to subscribe to (with ``once_per``). At least one.
            once_per: What the trigger fires at most once per; must be legal for every subscribed event.
            schedule: A cron expression (UTC) to fire on instead of events.
            fires_on: The firing source itself, as an alternative to the
                ``events``/``once_per`` or ``schedule`` shorthands.
            condition: Optional predicate over the firing's namespace.
            enabled: Whether the trigger is active immediately.
            caller_org_id: Org to create the trigger in. Defaults to the caller's org.
            roboto_client: Roboto client instance. Uses the default if not provided.

        Returns:
            The created trigger.

        Raises:
            RobotoInvalidRequestException: A cross-field validation rule fails (e.g.
                the condition references a root not exposed by every subscribed event).
            RobotoConflictException: The name is already taken in the org.
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
        """Load the trigger with the given id, whichever API created it."""
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
        """Load the trigger with the given name, whichever API created it. Names are unique within an org."""
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get(f"v1/triggers/{name}", owner_org_id=owner_org_id)
        return cls(response.to_record(TriggerRecord), roboto_client)

    @classmethod
    def platform_event_samples(
        cls,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> dict[PlatformEventType, PlatformEventSample]:
        """Fetch a realistic sample of every event type, dereferenced.

        Each sample carries the event envelope, every namespace root the type
        exposes with a full record under it, and the ``root.path`` list a
        condition field or ``{{ }}`` placeholder may name. Use it to see what a
        template will resolve to before writing one.

        Examples:
            >>> samples = Trigger.platform_event_samples()
            >>> samples[PlatformEventType.FileUploaded].paths[:3]
            ['envelope.id', 'envelope.type', 'envelope.time']
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
        """Yield every trigger in the org, event-fired and scheduled, newest first, whichever API created it."""
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
        return self.__record.condition

    @property
    def enabled(self) -> bool:
        return self.__record.enabled

    @property
    def engine(self) -> str:
        """Which trigger shape this trigger was created in: ``"v2"``, or ``"v1"`` for a trigger
        created through the older ``causes``/``for_each`` API."""
        return self.__record.engine

    @property
    def events(self) -> typing.Optional[typing.List[PlatformEventType]]:
        """The subscribed event types, or ``None`` for a schedule-fired trigger."""
        source = self.__record.fires_on
        return list(source.events) if isinstance(source, EventSubscription) else None

    @property
    def fires_on(self) -> TriggerSource:
        """What makes the trigger fire: an event subscription or a schedule."""
        return self.__record.fires_on

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def once_per(self) -> OncePer:
        """What the trigger fires at most once per; always ``occurrence`` (one firing per minute) for a schedule."""
        return self.__record.fires_on.once_per

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def record(self) -> TriggerRecord:
        return self.__record

    @property
    def schedule(self) -> typing.Optional[str]:
        """The cron expression (UTC) the trigger fires on, or ``None`` for an event-fired trigger."""
        source = self.__record.fires_on
        return source.cron if isinstance(source, Schedule) else None

    @property
    def targets(self) -> typing.List[TriggerTargetSpec]:
        return self.__record.targets

    @property
    def trigger_id(self) -> str:
        return self.__record.trigger_id

    def delete(self) -> None:
        """Delete this trigger. Idempotent."""
        self.__roboto_client.delete(f"v1/triggers/{self.name}", owner_org_id=self.org_id)

    def disable(self) -> "Trigger":
        """Disable this trigger."""
        return self.update(enabled=False)

    def dispatches(
        self,
        limit: int = 100,
    ) -> collections.abc.Generator[TriggerDispatchRecord, None, None]:
        """Yield this trigger's dispatch history, newest first.

        A dispatch is one attempt to run one target for one matched event; only
        matches are recorded, so an empty history means the trigger never fired.

        Args:
            limit: Page size for the underlying requests.
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
        session_id: typing.Optional[str] = None,
        event_id: typing.Optional[str] = None,
        event_type: typing.Optional[PlatformEventType] = None,
        scheduled_for: typing.Optional[datetime.datetime] = None,
    ) -> TriggerDryRunResponse:
        """Ask "would this trigger fire?" without dispatching anything.

        Provide either a full ``event`` or exactly one entity reference, from which
        the server synthesizes an event (``event_type`` optionally picks which kind).
        A schedule-fired trigger takes no reference: pass ``scheduled_for`` to pick
        the minute, or nothing for the schedule's next occurrence.
        The response is the evaluator's gate-by-gate trace: subscribed, enabled,
        condition (with per-leaf actual values), target prefilter, already fired.

        Examples:
            >>> trace = trigger.dry_run(dataset_id="ds_abc123")
            >>> print(trace.verdict)
        """
        request = TriggerDryRunRequest(
            event=event,
            dataset_id=dataset_id,
            file_id=file_id,
            invocation_id=invocation_id,
            session_id=session_id,
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
        """Enable this trigger."""
        return self.update(enabled=True)

    def set_enabled(self, enabled: bool) -> "Trigger":
        """Enable or disable this trigger."""
        return self.update(enabled=enabled)

    def to_dict(self) -> dict[str, typing.Any]:
        """Return this trigger's record as a JSON-able dict."""
        return self.__record.model_dump(mode="json")

    def update(
        self,
        *,
        fires_on: typing.Union[TriggerSource, NotSetType] = NotSet,
        events: typing.Union[typing.List[PlatformEventType], NotSetType] = NotSet,
        once_per: typing.Union[OncePer, NotSetType] = NotSet,
        schedule: typing.Union[str, NotSetType] = NotSet,
        condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet,
        targets: typing.Union[typing.List[TriggerTargetSpec], NotSetType] = NotSet,
        enabled: typing.Union[bool, NotSetType] = NotSet,
    ) -> "Trigger":
        """Apply a partial update to this trigger and refresh this instance.

        Only provided fields change; ``condition=None`` clears the condition. The
        firing source is replaced whole: pass ``fires_on``, or the ``events`` /
        ``once_per`` / ``schedule`` shorthands, which are merged over the current
        source before being sent. A trigger with ``engine == "v1"`` accepts only edits
        its older shape can express — a single invoke-action target, event types that
        map onto it, ``once_per`` of ``file`` or ``dataset`` — and rejects the rest with
        a message naming what it cannot store.
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
                fires_on=new_source,
                condition=condition,
                targets=targets,
                enabled=enabled,
            )
        )
        response = self.__roboto_client.put(
            f"v1/triggers/{self.name}",
            data=request,
            owner_org_id=self.org_id,
        )
        self.__record = response.to_record(TriggerRecord)
        return self


def _source_from_parts(
    *,
    fires_on: typing.Optional[TriggerSource],
    events: typing.Optional[list[PlatformEventType]],
    once_per: typing.Optional[OncePer],
    schedule: typing.Optional[str],
) -> TriggerSource:
    """Build the firing source from whichever shorthand the caller used.

    Raises:
        ValueError: The shorthands are mixed, or none is given.
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
