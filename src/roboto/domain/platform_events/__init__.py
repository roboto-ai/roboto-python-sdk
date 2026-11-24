# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Platform events: records of something that happened in an organization, which Roboto emits and triggers subscribe to.

A platform event is not an event (:py:mod:`roboto.domain.events`), which is an annotation over a span of time. Use
:py:class:`~roboto.domain.platform_events.PlatformEvent` and
:py:class:`~roboto.domain.platform_events.PlatformEventType` to read what happened, such as a file finishing ingestion,
:py:class:`~roboto.domain.platform_events.PlatformEventCatalog` to look up the payload and the data a trigger's
conditions can read for each type, and :py:class:`~roboto.domain.platform_events.OncePer` to limit a trigger to firing
once per file, dataset, or other resource a platform event names.
"""

from .catalog import (
    DATASET_ROOT,
    DEFAULT_PLATFORM_EVENT_CATALOG,
    ENVELOPE_ROOT,
    RESERVED_ROOTS,
    TRIGGER_ROOT,
    OncePerProjection,
    PlatformEventCatalog,
    PlatformEventDescriptor,
    event_catalog_manifest,
)
from .events import (
    CLOUDEVENTS_SPECVERSION,
    CLOUDEVENTS_TYPE_PREFIX,
    DatasetCreatedPayload,
    DatasetMetadataUpdatedPayload,
    DatasetTagAddedPayload,
    EventCreatedPayload,
    FileIngestedPayload,
    FileMetadataUpdatedPayload,
    FileUploadedPayload,
    InvocationCompletedPayload,
    InvocationFailedPayload,
    PlatformEvent,
    PlatformEventPayload,
    PlatformEventType,
    ScheduleFiredPayload,
    SessionEventCreatedPayload,
    SessionIngestedPayload,
    UploadCompletedPayload,
    platform_event_source,
)
from .once_per import OncePer
from .samples import (
    SAMPLE_ACTION_DIGEST,
    SAMPLE_ACTION_NAME,
    SAMPLE_API_DOMAIN,
    SAMPLE_CHANGESET,
    SAMPLE_DATASET_ID,
    SAMPLE_EVENT_ID,
    SAMPLE_FILE_ID,
    SAMPLE_FILE_VERSION,
    SAMPLE_INVOCATION_ID,
    SAMPLE_ORG_ID,
    SAMPLE_SESSION_EVENT_ID,
    SAMPLE_SESSION_ID,
    SAMPLE_TAGS_ADDED,
    SAMPLE_TIME,
    SAMPLE_TRANSACTION_ID,
    SAMPLE_TRIGGER_ID,
    SAMPLE_USER,
    sample_platform_event,
)

__all__ = [
    "CLOUDEVENTS_SPECVERSION",
    "DATASET_ROOT",
    "event_catalog_manifest",
    "CLOUDEVENTS_TYPE_PREFIX",
    "DEFAULT_PLATFORM_EVENT_CATALOG",
    "ENVELOPE_ROOT",
    "RESERVED_ROOTS",
    "TRIGGER_ROOT",
    "SAMPLE_ACTION_DIGEST",
    "SAMPLE_ACTION_NAME",
    "SAMPLE_API_DOMAIN",
    "SAMPLE_CHANGESET",
    "SAMPLE_DATASET_ID",
    "SAMPLE_EVENT_ID",
    "SAMPLE_FILE_ID",
    "SAMPLE_FILE_VERSION",
    "SAMPLE_INVOCATION_ID",
    "SAMPLE_ORG_ID",
    "SAMPLE_SESSION_EVENT_ID",
    "SAMPLE_SESSION_ID",
    "SAMPLE_TAGS_ADDED",
    "SAMPLE_TIME",
    "SAMPLE_TRANSACTION_ID",
    "SAMPLE_TRIGGER_ID",
    "SAMPLE_USER",
    "DatasetCreatedPayload",
    "DatasetMetadataUpdatedPayload",
    "DatasetTagAddedPayload",
    "EventCreatedPayload",
    "FileIngestedPayload",
    "FileMetadataUpdatedPayload",
    "FileUploadedPayload",
    "InvocationCompletedPayload",
    "InvocationFailedPayload",
    "OncePer",
    "OncePerProjection",
    "PlatformEvent",
    "PlatformEventCatalog",
    "PlatformEventDescriptor",
    "PlatformEventPayload",
    "PlatformEventType",
    "ScheduleFiredPayload",
    "SessionEventCreatedPayload",
    "SessionIngestedPayload",
    "UploadCompletedPayload",
    "platform_event_source",
    "sample_platform_event",
]
