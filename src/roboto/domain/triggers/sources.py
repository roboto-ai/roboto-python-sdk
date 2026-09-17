# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What makes a trigger fire: a platform event subscription or a schedule.

A trigger has exactly one firing source. Both kinds feed the same condition and the
same targets, and a target cannot tell which one fired it beyond what the event
namespace exposes.
"""

import typing

import cron_converter
import pydantic

from ...compat import StrEnum
from ..platform_events import OncePer, PlatformEventType

_FROZEN = pydantic.ConfigDict(frozen=True)


class TriggerSourceType(StrEnum):
    """Discriminator for :data:`TriggerSource`."""

    Events = "events"
    """The trigger fires when a subscribed platform event occurs."""

    Schedule = "schedule"
    """The trigger fires on a cron schedule."""


class _SourceBase(pydantic.BaseModel):
    """Common base for firing sources.

    Marks the ``type`` discriminator as explicitly set at construction so it survives
    ``exclude_unset`` serialization, the same way target specs do.
    """

    model_config = _FROZEN

    def model_post_init(self, __context: typing.Any) -> None:
        self.__pydantic_fields_set__.add("type")


class EventSubscription(_SourceBase):
    """Fire when any of the subscribed platform events occurs.

    Carries ``once_per`` because it only means something here: it names what the
    *event* is about that the trigger fires at most once for, and a schedule has no
    such subject.
    """

    type: typing.Literal[TriggerSourceType.Events] = TriggerSourceType.Events
    """Discriminator for :data:`TriggerSource`."""

    events: list[PlatformEventType]
    """Event types the trigger subscribes to. At least one; a condition may only
    reference namespace roots exposed by every subscribed event."""

    once_per: OncePer
    """What the trigger fires at most once per: the occurrence, or an entity the event
    names. Must be legal for every subscribed event type."""

    def fires_for(self, event_type: PlatformEventType) -> bool:
        """Return whether an event of ``event_type`` is one this subscription fires for."""
        return event_type in self.events


class Schedule(_SourceBase):
    """Fire on a cron schedule, in UTC.

    Each scheduled minute fires the trigger once (``once_per='occurrence'`` over the
    schedule tick). A
    missed minute is skipped rather than replayed later, so a delayed schedule never
    floods targets with backdated firings. Cron expressions are evaluated in UTC; a
    schedule cannot name a time zone.
    """

    type: typing.Literal[TriggerSourceType.Schedule] = TriggerSourceType.Schedule
    """Discriminator for :data:`TriggerSource`."""

    cron: str
    """A five-field cron expression (``minute hour day-of-month month day-of-week``),
    evaluated in UTC — e.g. ``0 9 * * 1`` for 09:00 UTC every Monday."""

    @property
    def once_per(self) -> OncePer:
        """A schedule always fires once per scheduled minute."""
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
        """Return whether ``event_type`` is the schedule occurrence this source fires for."""
        return event_type is PlatformEventType.ScheduleFired


TriggerSource = typing.Annotated[
    typing.Union[EventSubscription, Schedule],
    pydantic.Field(discriminator="type"),
]
"""A trigger's firing source, discriminated on ``type``."""


__all__ = [
    "EventSubscription",
    "Schedule",
    "TriggerSource",
    "TriggerSourceType",
]
