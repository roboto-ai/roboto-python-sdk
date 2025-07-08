# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...association import Association
from .operations import EventDisplayOptions


class EventRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of an event.
    """

    associations: list[Association] = pydantic.Field(default_factory=list)
    """
    Datasets, files, topics and message paths which this event pertains to.
    """

    created: datetime.datetime
    """
    Date/time when this event was created.
    """

    created_by: str
    """
    The user who created this event.
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

    event_id: str
    """
    A globally unique ID used to reference an event.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """
    Key-value pairs to associate with this event for discovery and search.
    """

    modified: datetime.datetime
    """
    Date/time when this event was last modified.
    """

    modified_by: str
    """
    The user who last modified this event.
    """

    name: str
    """
    A brief human-readable name for the event. Many events can have the same name. "Takeoff", "Crash", "CPU Spike",
    "Bad Image Quality", and "Unexpected Left" are a few potential examples.
    """

    org_id: str
    """
    The organization to which this event belongs.
    """

    start_time: int
    """
    The start time of the event, in nanoseconds since epoch (assumed Unix epoch).
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """
    Tags to associate with this event for discovery and search.
    """

    display_options: typing.Optional[EventDisplayOptions] = None
    """
    Display options for the event, such as color.
    """

    def __eq__(self, other: typing.Any) -> bool:
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
            and self.modified == other.modified
            and self.modified_by == other.modified_by
            and self.name == other.name
            and self.org_id == other.org_id
            and self.start_time == other.start_time
            and set(self.tags) == set(other.tags)
            and self.display_options == other.display_options
        )
