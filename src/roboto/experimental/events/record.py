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
    """Field of a topic that a session event is about: one field of one of the topic's schemas.

    Carried in ``EventTopic.fields``.
    """

    field_id: str
    """ID of the schema field, beginning with ``sf_``.

    Each schema of a topic has its own field IDs, so when the topic's schema changes, the same path gets a new ID. The
    event names this field only in the data written with this field's schema.
    """

    path_in_schema: tuple[str, ...]
    """Path of the field within its schema, one element per level, such as ``("pose", "position", "x")``."""


class EventTopic(pydantic.BaseModel):
    """Topic that a session event is about, and the fields of that topic it is about, if it names any.

    Carried in ``EventRecord.topics``.
    """

    topic_id: str
    """ID of the topic, beginning with ``ti_``.

    Unlike the ``tp_`` ID of a topic in one file, it is the same in every file and schema that carries the topic.
    """

    topic_name: str
    """Name of the topic, such as ``"/imu/data"``, unique within its organization."""

    fields: typing.Optional[list[EventTopicField]] = None
    """Fields of the topic the event is about, ordered by path, or ``None`` if the event is about the whole topic."""


class EventRecord(pydantic.BaseModel):
    """Data record of a session event, as the Roboto API returns it.

    A session event is a moment or span of interest in one session's data. It is separate from the events that belong
    to a dataset, whose IDs begin with ``ev_``. ``Event`` wraps this record with methods that act on the event, and
    exposes it as ``Event.record``.
    """

    event_id: str
    """Unique ID of the event, beginning with ``evt_``."""

    org_id: str
    """ID of the organization that owns the event, which also owns the event's session."""

    name: str
    """Human-readable name of the event, such as ``"Takeoff"``. Roboto does not require names to be unique."""

    description: typing.Optional[str] = None
    """Human-readable description of the event, or ``None`` if it has none."""

    session_id: str
    """ID of the session the event belongs to. Fixed when the event is created."""

    topics: list[EventTopic] = pydantic.Field(default_factory=list)
    """Topics, or fields of topics, the event is about, ordered by topic name.

    Empty when the event is about all of the session's data.
    """

    start_time: int
    """Inclusive start of the event's time span, in nanoseconds since the Unix epoch."""

    end_time: int
    """Inclusive end of the event's time span, in nanoseconds since the Unix epoch.

    Equal to ``start_time`` for an event at a single point in time, and never earlier than ``start_time``.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the event."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the event."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the custom fields the organization defines for events, keyed by field name.

    Every event custom field in the :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state appears as
    a key, mapped to ``None`` when the event has no value for it. Fields in any other state are absent, so the map is
    empty when no event custom field is in that state.
    """

    display_options: typing.Optional[EventDisplayOptions] = None
    """How the Roboto web app displays the event, such as its color, or ``None`` if no display options are set."""

    created: datetime.datetime
    """Time the event was created."""

    created_by: str
    """Principal that created the event, as ``<type>:<id>``, such as ``user:<user_id>``."""

    modified: datetime.datetime
    """Time the event was last modified."""

    modified_by: str
    """Principal that last modified the event, in the same ``<type>:<id>`` form as ``created_by``."""

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)
