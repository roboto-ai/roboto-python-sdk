# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Platform events: what happened to an entity on the platform, as a record.

Distinct from :mod:`roboto.domain.events`, whose ``Event`` is a time-anchored annotation
on robotics data. A platform event is emitted by the platform when a file is uploaded,
a dataset is created, an invocation finishes, and so on. Triggers subscribe to them;
outgoing integrations receive them as CloudEvents. The catalog describes each type: its
payload model, the namespace roots it exposes, and the ``once_per`` values it supports.
"""

from .catalog import (
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
    SessionCreatedPayload,
    SessionFilesAddedPayload,
    SessionUpdatedPayload,
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
    SAMPLE_INVOCATION_ID,
    SAMPLE_ORG_ID,
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
    "SAMPLE_INVOCATION_ID",
    "SAMPLE_ORG_ID",
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
    "SessionCreatedPayload",
    "SessionFilesAddedPayload",
    "SessionUpdatedPayload",
    "UploadCompletedPayload",
    "platform_event_source",
    "sample_platform_event",
]
