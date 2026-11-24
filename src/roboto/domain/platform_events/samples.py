# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

from ...updates import MetadataChangeset
from ..actions import InvocationStatus
from .catalog import DEFAULT_PLATFORM_EVENT_CATALOG
from .events import (
    PlatformEvent,
    PlatformEventType,
    platform_event_source,
)

SAMPLE_TIME = datetime.datetime(2026, 8, 28, 14, 32, 11, tzinfo=datetime.timezone.utc)
"""Time every sample event and sample record is dated from, fixed so that samples are the same on every call."""

SAMPLE_API_DOMAIN = "api.roboto.ai"
"""API domain in the ``source`` of every sample event."""

SAMPLE_ORG_ID = "og_k3m8w2rq7nxd"
"""ID of the organization every sample event and sample record belongs to."""

SAMPLE_TRIGGER_ID = "tr_3nq7wk2mx9pd"
"""ID of the sample trigger, and of the trigger whose schedule fires in the sample ``ScheduleFired`` event."""

SAMPLE_USER = "maria.chen@acme-robotics.com"
"""User in the ``created_by`` and ``modified_by`` fields of the sample records."""

SAMPLE_DATASET_ID = "ds_7h2k9m4qxp3w"
"""ID of the dataset the sample events name."""

SAMPLE_EVENT_ID = "ev_7g3n5kq2wxrd"
"""ID of the event created in the sample ``EventCreated`` event."""

SAMPLE_SESSION_EVENT_ID = "evt_4p8m2xk7qw9tdr3n"
"""ID of the event created on a session in the sample ``SessionEventCreated`` event, beginning with ``evt_``."""

SAMPLE_FILE_ID = "fl_q8v2n6ty4mcs"
"""ID of the file the sample events name."""

SAMPLE_FILE_VERSION = 2
"""Version of the sample file that the sample file events name."""

SAMPLE_INVOCATION_ID = "iv_2x9pd7wk5rhf"
"""ID of the invocation in the sample ``InvocationCompleted`` and ``InvocationFailed`` events."""

SAMPLE_SESSION_ID = "se_m4t7c1zq9bvn"
"""ID of the session in the sample ``SessionIngested`` and ``SessionEventCreated`` events."""

SAMPLE_TRANSACTION_ID = "tx_5jw8r3ne2kpq"
"""ID of the upload transaction the sample file arrived in."""

SAMPLE_ACTION_NAME = "ros-ingest"
"""Name of the action the sample invocation runs."""

SAMPLE_ACTION_DIGEST = "sha256:9f1c2e7b4a0d8c6f3e5b1a7d2c4f8e6a0b3d5c7e9f1a2b4c6d8e0f2a4b6c8d0e"
"""Digest of the version of the action the sample invocation runs."""

SAMPLE_TAGS_ADDED = ["validated", "nightly"]
"""Tags added to the dataset in the sample ``DatasetTagAdded`` event.

``SAMPLE_CHANGESET`` puts the same tags."""

SAMPLE_CHANGESET = MetadataChangeset(
    put_fields={"vehicle_id": "rover-07", "route": "warehouse-loop-b"},
    put_tags=SAMPLE_TAGS_ADDED,
    remove_tags=["needs-review"],
)
"""Change in the sample ``FileMetadataUpdated`` and ``DatasetMetadataUpdated`` events.

It sets two metadata keys, adds the tags in ``SAMPLE_TAGS_ADDED``, and removes the tag ``needs-review``."""


def _payload_for(event_type: PlatformEventType) -> dict[str, typing.Any]:
    """Build the sample payload, the event's ``data``, for ``event_type``."""
    if event_type in (PlatformEventType.FileUploaded, PlatformEventType.FileIngested):
        return {
            "dataset_id": SAMPLE_DATASET_ID,
            "file_id": SAMPLE_FILE_ID,
            "file_version": SAMPLE_FILE_VERSION,
            "transaction_id": SAMPLE_TRANSACTION_ID,
        }
    if event_type is PlatformEventType.UploadCompleted:
        return {"dataset_id": SAMPLE_DATASET_ID, "transaction_id": SAMPLE_TRANSACTION_ID}
    if event_type is PlatformEventType.FileMetadataUpdated:
        return {
            "dataset_id": SAMPLE_DATASET_ID,
            "file_id": SAMPLE_FILE_ID,
            "file_version": SAMPLE_FILE_VERSION,
            "changeset": SAMPLE_CHANGESET,
        }
    if event_type is PlatformEventType.DatasetMetadataUpdated:
        return {"dataset_id": SAMPLE_DATASET_ID, "changeset": SAMPLE_CHANGESET}
    if event_type is PlatformEventType.DatasetCreated:
        return {"dataset_id": SAMPLE_DATASET_ID}
    if event_type is PlatformEventType.DatasetTagAdded:
        return {"dataset_id": SAMPLE_DATASET_ID, "tags_added": SAMPLE_TAGS_ADDED}
    if event_type in (PlatformEventType.InvocationCompleted, PlatformEventType.InvocationFailed):
        status = (
            InvocationStatus.Completed
            if event_type is PlatformEventType.InvocationCompleted
            else InvocationStatus.Failed
        )
        return {
            "invocation_id": SAMPLE_INVOCATION_ID,
            "action_name": SAMPLE_ACTION_NAME,
            "action_owner_id": SAMPLE_ORG_ID,
            "status": status,
        }
    if event_type is PlatformEventType.SessionIngested:
        return {"session_id": SAMPLE_SESSION_ID, "ingestion_number": 1}
    if event_type is PlatformEventType.EventCreated:
        return {"event_id": SAMPLE_EVENT_ID}
    if event_type is PlatformEventType.SessionEventCreated:
        return {"event_id": SAMPLE_SESSION_EVENT_ID, "session_id": SAMPLE_SESSION_ID}
    if event_type is PlatformEventType.ScheduleFired:
        return {"trigger_id": SAMPLE_TRIGGER_ID, "scheduled_for": SAMPLE_TIME.replace(second=0, microsecond=0)}
    raise ValueError(f"No sample payload for event type {event_type.value!r}.")


def sample_platform_event(event_type: PlatformEventType) -> PlatformEvent:
    """Build a sample platform event of ``event_type``, with every optional payload field set.

    Every sample takes its IDs and time from the ``SAMPLE_*`` constants in this module, so samples of different types
    describe one scenario: one organization, dataset, file, session, and action invocation. The values are made up and
    name nothing that exists in Roboto. :py:func:`~roboto.domain.triggers.platform_event_sample` builds on these
    samples to show what a trigger's conditions and templates can read.

    Args:
        event_type: Type of the platform event to return.

    Raises:
        ValueError: This version of the SDK has no sample payload for ``event_type``.

    Examples:
        >>> from roboto.domain.platform_events import PlatformEventType, sample_platform_event
        >>> event = sample_platform_event(PlatformEventType.FileUploaded)
        >>> event.id
        'evt:fl_q8v2n6ty4mcs:file.uploaded'
    """
    payload = _payload_for(event_type)
    # Build the ID from the payload field that PlatformEvent.subject reads, the subject
    # entity's <type>_id, so the ID and the subject name the same entity.
    subject_type = DEFAULT_PLATFORM_EVENT_CATALOG.descriptor(event_type).subject_type
    subject_id = payload[f"{subject_type.value}_id"]
    event_id = (
        # Roboto announces a session ingested again each time its files change, so its ID numbers the announcement.
        f"evt:{subject_id}:{payload['ingestion_number']}:ingested"
        if event_type is PlatformEventType.SessionIngested
        else f"evt:{subject_id}:{event_type.value}"
    )
    return PlatformEvent.model_validate(
        {
            "id": event_id,
            "source": platform_event_source(SAMPLE_API_DOMAIN, SAMPLE_ORG_ID),
            "type": event_type,
            "time": SAMPLE_TIME,
            "org_id": SAMPLE_ORG_ID,
            "data": payload,
        }
    )


__all__ = [
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
    "sample_platform_event",
]
