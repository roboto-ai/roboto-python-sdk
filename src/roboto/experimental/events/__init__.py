# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Session events: moments or spans of interest in one session's data.

These are separate from the events that belong to a dataset, in :py:mod:`~roboto.domain.events`. Use ``Event`` to
create, find, and update session events, and to read their session's topic data over an event's time span.
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
