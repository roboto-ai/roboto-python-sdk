# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...domain.events import EventDisplayOptions, EventDisplayOptionsChangeset
from ...sentinels import NotSet, NotSetType
from ...updates import CustomFieldChangeset, MetadataChangeset

MAX_EVENTS_PER_DELETE_BATCH = 1000
"""Maximum number of event IDs that one request to the bulk Delete Events API may name."""

MAX_EVENTS_PER_PAGE = 1000
"""Maximum number of events one page of an event listing holds."""


class EventTopicRequest(pydantic.BaseModel):
    """A topic, and optionally fields of it, that an event is about."""

    topic_id: str
    """ID of the topic (``ti_*``). It must belong to the event's organization."""

    field_ids: typing.Optional[list[str]] = None
    """The fields the event is about, as schema field IDs (``sf_*``), or ``None`` for the whole topic.

    Each must be a field of a schema that the topic's data in the event's session carries. A field ID belongs to one
    schema, so the event names that field only in data written with that schema; to cover a field across schema
    versions, name its ID in each. An empty list is rejected; use ``None`` for the whole topic.
    """


class CreateEventRequest(pydantic.BaseModel):
    """Request body for ``POST /v2/events``."""

    name: str
    """A brief human-readable name for the event. Must not be blank. Many events can have the same name."""

    session_id: str
    """The session the event belongs to. It must belong to the caller's organization."""

    start_time: int
    """The start of the event, inclusive, in nanoseconds since the Unix epoch. Must not be negative."""

    end_time: typing.Optional[int] = None
    """The end of the event, inclusive, in nanoseconds since the Unix epoch. ``None`` makes the event instantaneous
    (``end_time`` equal to ``start_time``). Must not be earlier than ``start_time``."""

    topics: list[EventTopicRequest] = pydantic.Field(default_factory=list)
    """The topics, or topic fields, the event is about: one topic, several, or, when empty, all of the session's data.
    Each topic may appear once."""

    description: typing.Optional[str] = None
    """An optional human-readable description of the event."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Initial tags to associate with the event."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Initial key-value pairs to associate with the event."""

    display_options: typing.Optional[EventDisplayOptions] = None
    """Display options for the event, such as its color."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Initial values for ``Ready`` custom fields defined on events in the caller's organization.

    Each key must name such a field and each value must satisfy the field's declared type; anything else is rejected.
    """


class UpdateEventRequest(pydantic.BaseModel):
    """Request body for ``PUT /v2/events/id/<event_id>``. Fields left unset keep their stored values.

    An event's session cannot be changed.
    """

    name: typing.Union[str, NotSetType] = NotSet
    """A new name for the event. Must not be blank."""

    description: typing.Union[str, None, NotSetType] = NotSet
    """A new description for the event, or ``None`` to clear it."""

    start_time: typing.Union[int, NotSetType] = NotSet
    """A new start time, inclusive, in nanoseconds since the Unix epoch. Must not be negative."""

    end_time: typing.Union[int, NotSetType] = NotSet
    """A new end time, inclusive, in nanoseconds since the Unix epoch. The resulting end must not be earlier than the
    resulting start."""

    topics: typing.Union[list[EventTopicRequest], NotSetType] = NotSet
    """A replacement for every topic, or topic field, the event is about. An empty list makes the event about all of
    its session's data."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Metadata and tag changes to make to the event."""

    display_options_changeset: typing.Union[EventDisplayOptionsChangeset, NotSetType] = NotSet
    """Display option changes to make to the event."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to the event's values for ``Ready`` custom fields defined on events in its organization. Fields the
    changeset does not name are left unchanged."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class DeleteEventsRequest(pydantic.BaseModel):
    """Request body for ``POST /v2/events/delete``.

    IDs of events that do not exist are ignored, so repeating a request is not an error. If the caller may not delete
    one of the named events, none of them is deleted.
    """

    event_ids: list[str]
    """The events to delete, at most :py:data:`MAX_EVENTS_PER_DELETE_BATCH`."""
