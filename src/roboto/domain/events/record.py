# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...association import Association


class EventRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of an event.
    """

    associations: list[Association] = pydantic.Field(default_factory=list)
    """
    Datasets, files, and topics which this event pertains to.
    """

    created: datetime.datetime
    """
    Date/time when this event was created.
    """

    created_by: str = pydantic.Field(description="The user who registered this device.")
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
    Date/time when this device record was last modified.
    """

    modified_by: str
    """
    The user who last modified this device record.
    """

    name: str
    """
    A brief human-readable name for the event. Many events can have the same name. "Takeoff", "Crash", "CPU Spike",
    "Bad Image Quality", and "Unexpected Left" are a few potential examples.
    """

    org_id: str = pydantic.Field(description="The org to which this device belongs.")
    """
    The org to which this device belongs.
    """

    start_time: int
    """
    The start time of the event, in nanoseconds since epoch (assumed Unix epoch).
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """
    Tags to associate with this event for discovery and search.
    """
