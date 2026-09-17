# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""One fixed scenario, rendered as a platform event of every type.

The ids below name one org, one dataset, one file, one invocation, one session, and
one trigger; every sample envelope and every sample entity record refers to them, so
the samples agree with each other across types.
"""

import datetime
import typing

from ...updates import MetadataChangeset
from ..actions import InvocationStatus
from .events import (
    PlatformEvent,
    PlatformEventType,
    platform_event_source,
)

SAMPLE_TIME = datetime.datetime(2026, 8, 28, 14, 32, 11, tzinfo=datetime.timezone.utc)
"""The instant every sample event and record is dated from, so samples are stable
across calls."""

# One scenario, referenced by every root so the ids agree across records.
SAMPLE_API_DOMAIN = "api.roboto.ai"
SAMPLE_ORG_ID = "og_k3m8w2rq7nxd"
SAMPLE_TRIGGER_ID = "tr_3nq7wk2mx9pd"
SAMPLE_USER = "maria.chen@acme-robotics.com"
SAMPLE_DATASET_ID = "ds_7h2k9m4qxp3w"
SAMPLE_EVENT_ID = "ev_7g3n5kq2wxrd"
SAMPLE_FILE_ID = "fl_q8v2n6ty4mcs"
SAMPLE_INVOCATION_ID = "iv_2x9pd7wk5rhf"
SAMPLE_SESSION_ID = "se_m4t7c1zq9bvn"
SAMPLE_TRANSACTION_ID = "tx_5jw8r3ne2kpq"
SAMPLE_ACTION_NAME = "ros-ingest"
SAMPLE_ACTION_DIGEST = "sha256:9f1c2e7b4a0d8c6f3e5b1a7d2c4f8e6a0b3d5c7e9f1a2b4c6d8e0f2a4b6c8d0e"

SAMPLE_TAGS_ADDED = ["validated", "nightly"]
SAMPLE_CHANGESET = MetadataChangeset(
    put_fields={"vehicle_id": "rover-07", "route": "warehouse-loop-b"},
    put_tags=SAMPLE_TAGS_ADDED,
    remove_tags=["needs-review"],
)


def _payload_for(event_type: PlatformEventType) -> dict[str, typing.Any]:
    """The envelope's ``data`` for ``event_type``, from the same scenario."""
    if event_type in (PlatformEventType.FileUploaded, PlatformEventType.FileIngested):
        return {"dataset_id": SAMPLE_DATASET_ID, "file_id": SAMPLE_FILE_ID, "transaction_id": SAMPLE_TRANSACTION_ID}
    if event_type is PlatformEventType.UploadCompleted:
        return {"dataset_id": SAMPLE_DATASET_ID, "transaction_id": SAMPLE_TRANSACTION_ID}
    if event_type is PlatformEventType.FileMetadataUpdated:
        return {"dataset_id": SAMPLE_DATASET_ID, "file_id": SAMPLE_FILE_ID, "changeset": SAMPLE_CHANGESET}
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
    if event_type is PlatformEventType.SessionCreated:
        return {"session_id": SAMPLE_SESSION_ID}
    if event_type is PlatformEventType.SessionFilesAdded:
        return {"session_id": SAMPLE_SESSION_ID, "file_ids": [SAMPLE_FILE_ID, "fl_8kd3p5xw2nqr"]}
    if event_type is PlatformEventType.SessionUpdated:
        return {"session_id": SAMPLE_SESSION_ID, "changeset": SAMPLE_CHANGESET}
    if event_type is PlatformEventType.EventCreated:
        return {"event_id": SAMPLE_EVENT_ID}
    if event_type is PlatformEventType.ScheduleFired:
        return {"trigger_id": SAMPLE_TRIGGER_ID, "scheduled_for": SAMPLE_TIME.replace(second=0, microsecond=0)}
    raise ValueError(f"No sample payload for event type {event_type.value!r}.")


def sample_platform_event(event_type: PlatformEventType) -> PlatformEvent:
    """A valid, fully populated event of ``event_type`` from the sample scenario."""
    return PlatformEvent.model_validate(
        {
            "id": f"evt:{_payload_for(event_type)[_subject_key(event_type)]}:{event_type.value}",
            "source": platform_event_source(SAMPLE_API_DOMAIN, SAMPLE_ORG_ID),
            "type": event_type,
            "time": SAMPLE_TIME,
            "org_id": SAMPLE_ORG_ID,
            "data": _payload_for(event_type),
        }
    )


def _subject_key(event_type: PlatformEventType) -> str:
    """Which payload field names the event's subject, for the sample event id."""
    payload = _payload_for(event_type)
    for key in ("file_id", "invocation_id", "session_id", "event_id", "dataset_id", "trigger_id"):
        if key in payload:
            return key
    raise ValueError(f"Sample payload for {event_type.value!r} names no subject.")


__all__ = [
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
    "sample_platform_event",
]
