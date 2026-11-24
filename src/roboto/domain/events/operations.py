# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...association import Association
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    value_or_default_if_unset,
)
from ...updates import CustomFieldChangeset, MetadataChangeset

MAX_EVENT_NAME_BYTES = 2600
"""Maximum length of an event name, in bytes of its UTF-8 encoding.

Roboto enforces the same limit when it stores an event.
"""


def _check_name_size(name: str) -> None:
    if len(name.encode("utf-8")) > MAX_EVENT_NAME_BYTES:
        raise ValueError(f"An event name may be at most {MAX_EVENT_NAME_BYTES} bytes of UTF-8")


class EventDisplayOptions(pydantic.BaseModel):
    """Options for how Roboto displays an event, such as its color.

    Carried in :py:attr:`~roboto.domain.events.EventRecord.display_options` and ``CreateEventRequest.display_options``.
    """

    color: typing.Optional[str] = None
    """Display color of the event, as any CSS color value, such as ``"red"``, ``"#ff0000"`` or ``"rgb(255 0 0)"``.

    The color distinguishes the event on a timeline, and can signal what the event means, such as red for a critical
    issue. ``None`` lets Roboto choose a color.
    """

    def has_options(self) -> bool:
        """Return whether any display option is set."""

        return any([self.color])


class EventDisplayOptionsChangeset(pydantic.BaseModel):
    """Changes to an event's display options.

    A field left unset (``NotSet``) is unchanged. Carried in ``UpdateEventRequest.display_options_changeset``.
    """

    color: typing.Union[str, None, NotSetType] = NotSet
    """Display color to set on the event, as any CSS color value. ``None`` clears it, so Roboto chooses one."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    def apply_to(self, display_options: EventDisplayOptions) -> EventDisplayOptions:
        """Return the display options that result from applying this changeset to ``display_options``.

        Args:
            display_options: Display options to apply the changes to. They are not modified.
        """

        color: typing.Optional[str] = value_or_default_if_unset(self.color, display_options.color)

        return EventDisplayOptions(color=color)

    def has_changes(self) -> bool:
        """Return whether this changeset changes any display option."""

        return any(map(is_set, [self.color]))


class CreateEventRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.events.Event.create`.

    Building it raises ``pydantic.ValidationError`` when ``name`` is longer than ``MAX_EVENT_NAME_BYTES`` in UTF-8.
    """

    associations: list[Association] = pydantic.Field(default_factory=list)
    """Datasets, files, topics and message paths the event is associated with.

    Must contain at least one, and each must belong to the organization the event is created in. Otherwise the request
    raises ``RobotoInvalidRequestException``.
    """

    description: typing.Optional[str] = None
    """Human-readable description of the event."""

    end_time: int
    """End of the event, in nanoseconds since the Unix epoch.

    Equal to ``start_time`` for an event at a single instant, and never earlier than ``start_time``.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
    )
    """Key-value metadata to set on the event."""

    name: str
    """Human-readable name of the event, such as ``"Takeoff"`` or ``"CPU Spike"``.

    Must not be blank, and at most 2,600 bytes long in UTF-8 (``MAX_EVENT_NAME_BYTES``). Event names are not unique.
    """

    start_time: int
    """Start of the event, in nanoseconds since the Unix epoch."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the event. Defaults to none."""

    display_options: typing.Optional[EventDisplayOptions] = None
    """How Roboto displays the event, such as its color. ``None`` lets Roboto choose."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = None
    """Initial values for the event's custom fields, keyed by field name. ``None`` sets none.

    Each name must be a :py:class:`~roboto.domain.custom_fields.CustomField` defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Event` in the organization the event is created in, with
    status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that field's
    declared type. Otherwise the request raises ``RobotoIllegalArgumentException``.
    """

    @pydantic.field_validator("name")
    @classmethod
    def _validate_name_size(cls, name: str) -> str:
        _check_name_size(name)
        return name


MAX_EVENTS_PER_DELETE_BATCH = 1000
"""Maximum number of event IDs in one ``DeleteEventsRequest``.

A request with more fails with :py:class:`~roboto.exceptions.RobotoInvalidRequestException`.
:py:meth:`~roboto.domain.events.Event.delete_many` accepts any number of IDs and sends them in requests of at most this
many.
"""


class DeleteEventsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.events.Event.delete_many`.

    IDs that match no event are skipped, so a request can be retried safely. If the caller cannot delete one of the
    events, the request fails and deletes nothing.
    """

    event_ids: list[str]
    """IDs of the events to delete, at most 1,000 (``MAX_EVENTS_PER_DELETE_BATCH``)."""


class QueryEventsForAssociationsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.events.Event.get_by_associations`."""

    associations: list[Association]
    """Datasets, files, topics and message paths to find events for.

    An event matches when it is associated with any of them. Must contain at least one.
    """

    page_token: typing.Optional[str] = None
    """Token from a previous page's response that resumes the listing after it. ``None`` starts at the first page."""


class UpdateEventRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.events.Event.update`.

    A field left at its default (``NotSet`` or ``None``) is unchanged. Building it raises ``pydantic.ValidationError``
    when ``name`` is longer than ``MAX_EVENT_NAME_BYTES`` in UTF-8.
    """

    description: typing.Union[str, None, NotSetType] = NotSet
    """Human-readable description of the event. ``None`` clears it."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the event's tags and metadata."""

    name: typing.Union[str, NotSetType] = NotSet
    """Human-readable name of the event, at most 2,600 bytes long in UTF-8 (``MAX_EVENT_NAME_BYTES``).

    Event names are not unique.
    """

    start_time: typing.Union[int, NotSetType] = NotSet
    """Start of the event, in nanoseconds since the Unix epoch."""

    end_time: typing.Union[int, NotSetType] = NotSet
    """End of the event, in nanoseconds since the Unix epoch.

    An update that would leave the event ending before it starts raises ``RobotoIllegalArgumentException``.
    """

    display_options_changeset: typing.Union[EventDisplayOptionsChangeset, NotSetType] = NotSet
    """Changes to the event's display options."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to the event's custom-field values. ``None`` leaves them unchanged.

    Each field name the changeset references must be a custom field defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Event` in the event's organization, with status
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each ``set_fields`` value must match that
    field's declared type. Otherwise the request raises ``RobotoIllegalArgumentException``. See
    :py:class:`~roboto.updates.CustomFieldChangeset`.
    """

    # The schema modifier shows NotSet fields as nullable in the JSON schema, not as a NotSetType object.
    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.field_validator("name")
    @classmethod
    def _validate_name_size(cls, name: typing.Union[str, NotSetType]) -> typing.Union[str, NotSetType]:
        if is_set(name):
            _check_name_size(name)
        return name
