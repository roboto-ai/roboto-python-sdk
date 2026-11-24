# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Events: annotations that tie datasets, files, topics, or message paths to a span of time, such as a takeoff.

Use :py:class:`~roboto.domain.events.Event` to create, find, and update events, and to read the data of the topics
they annotate within their time span.
"""

from .event import Event
from .operations import (
    MAX_EVENT_NAME_BYTES,
    MAX_EVENTS_PER_DELETE_BATCH,
    CreateEventRequest,
    DeleteEventsRequest,
    EventDisplayOptions,
    EventDisplayOptionsChangeset,
    QueryEventsForAssociationsRequest,
    UpdateEventRequest,
)
from .record import EventRecord

__all__ = [
    "MAX_EVENT_NAME_BYTES",
    "MAX_EVENTS_PER_DELETE_BATCH",
    "CreateEventRequest",
    "DeleteEventsRequest",
    "Event",
    "EventDisplayOptions",
    "EventDisplayOptionsChangeset",
    "EventRecord",
    "QueryEventsForAssociationsRequest",
    "UpdateEventRequest",
]
