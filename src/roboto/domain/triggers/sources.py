# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import cron_converter
import pydantic

from ...compat import StrEnum
from ..platform_events import OncePer, PlatformEventType

_FROZEN = pydantic.ConfigDict(frozen=True)


class TriggerSourceType(StrEnum):
    """Kind of firing source, the ``type`` of each ``TriggerSource``."""

    Events = "events"
    """Subscription to platform events: the trigger fires when one of them occurs."""

    Schedule = "schedule"
    """Cron schedule: the trigger fires at each of its scheduled minutes."""


class _SourceBase(pydantic.BaseModel):
    """Common base for firing sources.

    Marks ``type`` as set at construction, because the SDK serializes request bodies with ``exclude_unset``, and a
    source sent without ``type`` cannot be parsed back into ``TriggerSource``.
    """

    model_config = _FROZEN

    def model_post_init(self, __context: typing.Any) -> None:
        self.__pydantic_fields_set__.add("type")


class EventSubscription(_SourceBase):
    """Firing source that fires a trigger when any of its subscribed platform events occurs.

    When the trigger is saved, Roboto requires at least one event type, all about the same kind of entity, such as
    files, and rejects :py:attr:`~roboto.domain.platform_events.PlatformEventType.ScheduleFired`; a trigger fires on
    a schedule by declaring a ``Schedule`` instead.

    Constructing a subscription with a ``type`` other than ``TriggerSourceType.Events`` raises
    ``pydantic.ValidationError``.
    """

    type: typing.Literal[TriggerSourceType.Events] = TriggerSourceType.Events
    """Kind of firing source, always ``TriggerSourceType.Events``."""

    events: list[PlatformEventType]
    """Platform event types the trigger subscribes to.

    Its condition and target templates can read only the names, such as ``dataset``, that every one of them exposes.
    """

    once_per: OncePer
    """What the trigger runs each target at most once for.

    :py:class:`~roboto.domain.platform_events.OncePer` describes the choices and which event types support each.
    """

    def fires_for(self, event_type: PlatformEventType) -> bool:
        """Return whether a platform event of ``event_type`` fires this subscription's trigger.

        Roboto calls this when it evaluates a trigger for a platform event.

        Args:
            event_type: Type of the platform event.
        """
        return event_type in self.events


class Schedule(_SourceBase):
    """Firing source that fires a trigger on a cron schedule, in UTC.

    Each scheduled minute runs the trigger's targets at most once, even when Roboto delivers that minute twice. A
    minute Roboto misses, such as during an outage, is skipped and never fired later, so a delayed schedule does not
    run its targets for past minutes. A schedule cannot name a time zone. The trigger's condition and target templates
    read the firing under ``schedule``: ``schedule.scheduled_for`` is the scheduled minute and ``schedule.cron`` the
    cron expression.

    Constructing a schedule with a cron expression that cannot be parsed, or with a ``type`` other than
    ``TriggerSourceType.Schedule``, raises ``pydantic.ValidationError``.
    """

    type: typing.Literal[TriggerSourceType.Schedule] = TriggerSourceType.Schedule
    """Kind of firing source, always ``TriggerSourceType.Schedule``."""

    cron: str
    """Five-field cron expression (``minute hour day-of-month month day-of-week``), evaluated in UTC.

    For example, ``0 9 * * 1`` fires at 09:00 UTC every Monday.
    """

    @property
    def once_per(self) -> OncePer:
        """Firing limit, :py:attr:`~roboto.domain.platform_events.OncePer.Occurrence`: once per scheduled minute."""
        return OncePer.Occurrence

    @pydantic.field_validator("cron")
    @classmethod
    def _validate_cron(cls, value: str) -> str:
        try:
            cron_converter.Cron(value)
        except Exception as exc:
            raise ValueError(f"{value!r} is not a valid cron expression: {exc}") from exc
        return value

    def fires_for(self, event_type: PlatformEventType) -> bool:
        """Return whether a platform event of ``event_type`` fires this schedule's trigger.

        Roboto calls this when it evaluates a trigger for a platform event. Only
        :py:attr:`~roboto.domain.platform_events.PlatformEventType.ScheduleFired` fires it.

        Args:
            event_type: Type of the platform event.
        """
        return event_type is PlatformEventType.ScheduleFired


TriggerSource = typing.Annotated[
    typing.Union[EventSubscription, Schedule],
    pydantic.Field(discriminator="type"),
]
"""Firing source of any kind: one of ``EventSubscription`` and ``Schedule``, told apart by ``type``.

A trigger has exactly one firing source.
"""


__all__ = [
    "EventSubscription",
    "Schedule",
    "TriggerSource",
    "TriggerSourceType",
]
