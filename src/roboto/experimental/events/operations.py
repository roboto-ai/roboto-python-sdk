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
"""Maximum number of event IDs one ``DeleteEventsRequest`` may name.

``Event.delete_many`` sends a longer list of IDs in batches of this size.
"""

MAX_EVENTS_PER_PAGE = 1000
"""Maximum number of events in one page of a session's event listing.

:py:meth:`~roboto.experimental.sessions.Session.list_events` requests pages of this size.
"""


class EventTopicRequest(pydantic.BaseModel):
    """A topic an event is about, and optionally which of its fields.

    Carried in ``CreateEventRequest.topics`` and ``UpdateEventRequest.topics``.
    """

    topic_id: str
    """ID of the topic, beginning with ``ti_``: the one ID the topic has in every file that logs it, not a ``tp_`` ID.

    A topic outside the event's organization raises ``RobotoInvalidRequestException``.
    """

    field_ids: typing.Optional[list[str]] = None
    """IDs of the topic's schema fields the event is about, each beginning with ``sf_``. ``None`` means the whole topic.

    Each must be a field of a schema that the topic's data in the event's session carries. A field ID belongs to one
    schema, so the event names that field only in data written with that schema; to cover a field across schema
    versions, name its ID in each. A field outside that data, or an empty list, raises
    ``RobotoInvalidRequestException``.
    """


class CreateEventRequest(pydantic.BaseModel):
    """Request body for ``Event.create``."""

    name: str
    """Human-readable name of the event. Names are not unique. A blank name raises ``RobotoInvalidRequestException``."""

    session_id: str
    """ID of the session the event belongs to, beginning with ``se_``.

    A session outside the organization the event is created in raises ``RobotoInvalidRequestException``.
    """

    start_time: int
    """Inclusive start of the event, in nanoseconds since the Unix epoch.

    A negative time raises ``RobotoInvalidRequestException``.
    """

    end_time: typing.Optional[int] = None
    """Inclusive end of the event, in the same form as ``start_time``.

    ``None`` makes the event instantaneous, ending at ``start_time``. An end before ``start_time`` raises
    ``RobotoInvalidRequestException``.
    """

    topics: list[EventTopicRequest] = pydantic.Field(default_factory=list)
    """Topics, or fields of topics, the event is about. Empty makes the event about all of the session's data.

    A topic named twice raises ``RobotoInvalidRequestException``.
    """

    description: typing.Optional[str] = None
    """Human-readable description of the event."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the event."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the event."""

    display_options: typing.Optional[EventDisplayOptions] = None
    """Display options for the event, such as its color."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Values to set for the event's custom fields, keyed by field name.

    Each key must name a custom field on events in the event's organization whose status is
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`. Any other key, or a value the field's type does
    not accept, raises ``RobotoIllegalArgumentException``.
    """


class UpdateEventRequest(pydantic.BaseModel):
    """Request body for ``Event.update``.

    A field left at its default (``NotSet`` or ``None``) is unchanged. An event's session cannot change.
    """

    name: typing.Union[str, NotSetType] = NotSet
    """Human-readable name of the event. A blank name raises ``RobotoInvalidRequestException``."""

    description: typing.Union[str, None, NotSetType] = NotSet
    """Human-readable description of the event. ``None`` clears it."""

    start_time: typing.Union[int, NotSetType] = NotSet
    """Inclusive start of the event, in nanoseconds since the Unix epoch.

    A negative time raises ``RobotoInvalidRequestException``.
    """

    end_time: typing.Union[int, NotSetType] = NotSet
    """Inclusive end of the event, in the same form as ``start_time``.

    An end before the start, once both changes apply, raises ``RobotoInvalidRequestException``.
    """

    topics: typing.Union[list[EventTopicRequest], NotSetType] = NotSet
    """Topics, or fields of topics, the event is about, replacing every one it names.

    Empty makes the event about all of its session's data. A topic named twice raises
    ``RobotoInvalidRequestException``.
    """

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the event's tags and metadata."""

    display_options_changeset: typing.Union[EventDisplayOptionsChangeset, NotSetType] = NotSet
    """Changes to the event's display options."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to the event's custom field values. Fields the changeset does not name are unchanged.

    A field that is not a custom field on events with status
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, or a value the field's type does not accept, raises
    ``RobotoIllegalArgumentException``.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class DeleteEventsRequest(pydantic.BaseModel):
    """Request body for ``Event.delete_many``.

    IDs that match no event are ignored, so repeating a request succeeds. If the caller may not delete one of the
    named events, none of them is deleted.
    """

    event_ids: list[str]
    """IDs of the events to delete, each beginning with ``evt_``.

    More than 1000 (``MAX_EVENTS_PER_DELETE_BATCH``) raises ``RobotoInvalidRequestException``.
    """
