# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Mark moments of interest in a session's data.

Each event belongs to exactly one session, spans a start and an end time, and can be about one or more topics,
or fields of a topic. It carries tags, metadata, custom fields, and display options. These events are separate from
the events that belong to a dataset, in :py:mod:`roboto.domain.events`.
"""

from .event import Event
from .operations import (
    MAX_EVENTS_PER_DELETE_BATCH,
    MAX_EVENTS_PER_PAGE,
    CreateEventRequest,
    DeleteEventsRequest,
    EventTopicRequest,
    UpdateEventRequest,
)
from .record import EventRecord, EventTopic, EventTopicField

__all__ = (
    "MAX_EVENTS_PER_DELETE_BATCH",
    "MAX_EVENTS_PER_PAGE",
    "CreateEventRequest",
    "DeleteEventsRequest",
    "Event",
    "EventRecord",
    "EventTopic",
    "EventTopicField",
    "EventTopicRequest",
    "UpdateEventRequest",
)
