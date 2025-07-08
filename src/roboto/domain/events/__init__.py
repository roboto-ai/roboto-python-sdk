# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Events domain module for the Roboto SDK.

This module provides functionality for creating and managing events, which are time-anchored
annotations that relate Roboto entities (datasets, files, topics, and message paths) to
specific time periods. Events enable temporal analysis, data annotation, and correlation
of activities across different data sources.

The events domain includes:

- Event creation and management
- Association with datasets, files, topics, and message paths
- Time-based data retrieval and analysis
- Display options and metadata management
- Event querying and filtering capabilities
"""

from .event import Event
from .operations import (
    CreateEventRequest,
    EventDisplayOptions,
    EventDisplayOptionsChangeset,
    QueryEventsForAssociationsRequest,
    UpdateEventRequest,
)
from .record import EventRecord

__all__ = [
    "CreateEventRequest",
    "Event",
    "EventDisplayOptions",
    "EventDisplayOptionsChangeset",
    "EventRecord",
    "QueryEventsForAssociationsRequest",
    "UpdateEventRequest",
]
