# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...domain.events import EventDisplayOptions
from ...pydantic.serializers import field_serializer_custom_field_values


class EventTopicField(pydantic.BaseModel):
    """A field of a topic an event is about: one field of one of the topic's schemas."""

    field_id: str
    """ID of the schema field (``sf_*``). A field ID belongs to one schema: when the topic's schema changes, its fields
    get new IDs, so the event names this field only in data written with that schema."""

    path_in_schema: tuple[str, ...]
    """The field's path within its schema, for display."""


class EventTopic(pydantic.BaseModel):
    """A topic an event is about, and optionally the fields of that topic it is about."""

    topic_id: str
    """ID of the topic (``ti_*``), the same in every file and schema that carries it."""

    topic_name: str
    """The topic's name, unique within the organization."""

    fields: typing.Optional[list[EventTopicField]] = None
    """The fields the event is about, or ``None`` for the whole topic. Ordered by path."""


class EventRecord(pydantic.BaseModel):
    """A wire-transmissible representation of an event that belongs to a session."""

    event_id: str
    """A globally unique ID used to reference the event (``evt_*``)."""

    org_id: str
    """The organization that owns the event, which is also the organization that owns its session."""

    name: str
    """A brief human-readable name for the event. Many events can have the same name."""

    description: typing.Optional[str] = None
    """An optional human-readable description of the event."""

    session_id: str
    """The session the event belongs to. Fixed when the event is created."""

    topics: list[EventTopic] = pydantic.Field(default_factory=list)
    """The topics, or topic fields, the event is about, ordered by topic name: one topic, several, or, when empty, all
    of the session's data."""

    start_time: int
    """The start of the event, inclusive, in nanoseconds since the Unix epoch."""

    end_time: int
    """The end of the event, inclusive, in nanoseconds since the Unix epoch. Equal to ``start_time`` for an
    instantaneous event, and never earlier."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to associate with the event for discovery and search."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value pairs to associate with the event for discovery and search."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values for the custom fields defined on events in this organization.

    Every ``Ready`` custom field defined on events in the organization appears as a key, and a field with no value
    reads ``None``. Empty when the organization defines no custom fields on events.
    """

    display_options: typing.Optional[EventDisplayOptions] = None
    """Display options for the event, such as its color."""

    created: datetime.datetime
    """Date and time when the event was created."""

    created_by: str
    """The principal who created the event."""

    modified: datetime.datetime
    """Date and time when the event was last modified."""

    modified_by: str
    """The principal who last modified the event."""

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)
