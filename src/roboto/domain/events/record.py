# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...association import Association
from ...pydantic.serializers import field_serializer_custom_field_values
from .operations import EventDisplayOptions


class EventRecord(pydantic.BaseModel):
    """Data record of an event, as the Roboto API returns it.

    An event is an annotation that ties datasets, files, topics, or message paths to a span of time, such as a
    takeoff or a crash. :py:class:`~roboto.domain.events.Event` wraps this record with methods that act on the event,
    and exposes it as :py:attr:`~roboto.domain.events.Event.record`.
    """

    associations: list[Association] = pydantic.Field(default_factory=list)
    """Datasets, files, topics, and message paths the event annotates."""

    created: datetime.datetime
    """Time the event was created."""

    created_by: str
    """Principal that created the event, as ``<type>:<id>``, such as ``user:<user_id>``."""

    description: typing.Optional[str] = None
    """Human-readable description of the event, or ``None`` if it has none."""

    end_time: int
    """End of the event's time span, in nanoseconds since the Unix epoch.

    Equal to ``start_time`` for an event at a single point in time, and never earlier than ``start_time``.
    """

    event_id: str
    """Unique ID of the event, beginning with ``ev_``."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the event."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the custom fields the organization defines for events, keyed by field name.

    Every event custom field in the :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state appears as
    a key, mapped to ``None`` when the event has no value for it. Fields in any other state are absent, so the map is
    empty when no event custom field is in that state.
    """

    modified: datetime.datetime
    """Time the event was last modified."""

    modified_by: str
    """Principal that last modified the event, in the same ``<type>:<id>`` form as ``created_by``."""

    name: str
    """Human-readable name of the event, such as ``"Takeoff"`` or ``"CPU Spike"``.

    Roboto does not require names to be unique, so many events can share one.
    """

    org_id: str
    """ID of the organization that owns the event."""

    start_time: int
    """Start of the event's time span, in nanoseconds since the Unix epoch."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the event."""

    display_options: typing.Optional[EventDisplayOptions] = None
    """How the Roboto web app displays the event, such as its color, or ``None`` if no display options are set."""

    def __eq__(self, other: typing.Any) -> bool:
        """Return whether two event records hold the same values, ignoring the order of associations and of tags.

        Tags are compared as sets, so a repeated tag does not make two records unequal.
        """
        if not isinstance(other, EventRecord):
            return NotImplemented

        return (
            sorted(
                self.associations,
                key=lambda a: (a.association_type.value, a.association_id),
            )
            == sorted(
                other.associations,
                key=lambda a: (a.association_type.value, a.association_id),
            )
            and self.created == other.created
            and self.created_by == other.created_by
            and self.description == other.description
            and self.end_time == other.end_time
            and self.event_id == other.event_id
            and self.metadata == other.metadata
            and self.custom_fields == other.custom_fields
            and self.modified == other.modified
            and self.modified_by == other.modified_by
            and self.name == other.name
            and self.org_id == other.org_id
            and self.start_time == other.start_time
            and set(self.tags) == set(other.tags)
            and self.display_options == other.display_options
        )

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)
