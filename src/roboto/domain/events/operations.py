# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...association import Association
from ...sentinels import NotSet, NotSetType
from ...updates import MetadataChangeset


class CreateEventRequest(pydantic.BaseModel):
    """
    Request payload for the Create Event operation.
    """

    associations: list[Association] = pydantic.Field(default_factory=list)
    """
    Datasets, files, and topics which this event pertains to. At least one must be provided. All referenced
    datasets, files, and topics must be owned by the same organization.
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

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """
    An optional human-readable description of the event.
    """

    metadata_changeset: typing.Optional[MetadataChangeset] = None
    """
    Metadata and tag changes to make for this event
    """

    name: typing.Optional[str] = None
    """
    A brief human-readable name for the event. Many events can have the same name. "Takeoff", "Crash", "CPU Spike",
    "Bad Image Quality", and "Unexpected Left" are a few potential examples.
    """

    # This is required to get NotSet/NotSetType to serialize appropriately.
    model_config = pydantic.ConfigDict(
        extra="forbid", json_schema_extra=NotSetType.openapi_schema_modifier
    )
