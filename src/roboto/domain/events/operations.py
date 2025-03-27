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
from ...updates import MetadataChangeset


class EventDisplayOptions(pydantic.BaseModel):
    """Display options for an event."""

    color: typing.Optional[str] = None
    """
    Display color for the event.

    Used to visually distinguish events on a timeline, and optionally to signal semantic
    information about the event (e.g. "red" for events representing critical issues).

    Any value that is permissible in CSS to define a valid color can be used here, encoded
    as a string. For instance, the following are all valid: "red", "#ff0000", "rgb(255 0 0)".
    """

    def has_options(self) -> bool:
        """Checks whether any display options have been specified."""

        return any([self.color])


class EventDisplayOptionsChangeset(pydantic.BaseModel):
    """A set of changes to the display options of an event."""

    color: typing.Union[str, None, NotSetType] = NotSet
    """
    An update to an event's color.

    Use ``None`` to clear any previously set color value. On the Roboto website, the event
    will be displayed using an automatically selected color.
    """

    def apply_to(self, display_options: EventDisplayOptions) -> EventDisplayOptions:
        """Applies this changeset to some existing display options."""

        color: typing.Optional[str] = value_or_default_if_unset(
            self.color, display_options.color
        )

        return EventDisplayOptions(color=color)

    def has_changes(self) -> bool:
        """Checks whether this changeset contains any changes."""

        return any(map(is_set, [self.color]))


class CreateEventRequest(pydantic.BaseModel):
    """
    Request payload for the Create Event operation.
    """

    associations: list[Association] = pydantic.Field(default_factory=list)
    """
    Datasets, files, topics and message paths which this event relates to. At least one must be provided. All referenced
    datasets, files, topics and message paths must be owned by the same organization.
    """

    description: typing.Optional[str] = None
    """
    An optional human-readable description of the event.
    """

    end_time: int
    """
    The end time of the event, in nanoseconds since epoch (assumed Unix epoch). This can be equal to start_time if
    the event is discrete, but can never be less than start_time.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
    )
    """
    Initial key-value pairs to associate with this event for discovery and search.
    """

    name: str
    """
    A brief human-readable name for the event. Many events can have the same name. "Takeoff", "Crash", "CPU Spike",
    "Bad Image Quality", and "Unexpected Left" are a few potential examples.
    """

    start_time: int
    """
    The start time of the event, in nanoseconds since epoch (assumed Unix epoch).
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """
    Initial tags to associate with this event for discovery and search.
    """

    display_options: typing.Optional[EventDisplayOptions] = None
    """
    Display options for this event, such as color.
    """


class QueryEventsForAssociationsRequest(pydantic.BaseModel):
    """
    Request payload for the Query Events for Associations operation.
    """

    associations: list[Association]
    """Associations to query events for."""

    page_token: typing.Optional[str] = None
    """Token to use to fetch the next page of results, use None for the first page."""


class UpdateEventRequest(pydantic.BaseModel):
    """
    Request payload for the Update Event operation. Allows any of the mutable fields of an event to be changed.
    """

    description: typing.Union[str, None, NotSetType] = NotSet
    """
    An optional human-readable description of the event.
    """

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """
    Metadata and tag changes to make for this event
    """

    name: typing.Union[str, NotSetType] = NotSet
    """
    A brief human-readable name for the event. Many events can have the same name. "Takeoff", "Crash", "CPU Spike",
    "Bad Image Quality", and "Unexpected Left" are a few potential examples.
    """

    start_time: typing.Union[int, NotSetType] = NotSet
    """
    The start time of the event, in nanoseconds since epoch (assumed Unix epoch).
    """

    end_time: typing.Union[int, NotSetType] = NotSet
    """
    The end time of the event, in nanoseconds since epoch (assumed Unix epoch). This can be equal to start_time if
    the event is discrete, but can never be less than start_time.
    """

    display_options_changeset: typing.Union[
        EventDisplayOptionsChangeset, NotSetType
    ] = NotSet
    """
    Display options changes to apply to this event.
    """

    # This is required to get NotSet/NotSetType to serialize appropriately.
    model_config = pydantic.ConfigDict(
        extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier
    )
