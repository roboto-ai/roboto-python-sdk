# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Sample events: what a trigger's condition and target templates can see, shown
with realistic values.

Before writing a condition or a message template, an author needs to know what
``{{dataset.name}}`` or ``file.relative_path`` will resolve to. The event catalog says
which namespace roots an event exposes, but not what sits under them. A sample fills
that in: it is built with the same :class:`~roboto.domain.triggers.EventNamespace` and
record models that serve a real firing, so the shape it shows is the shape a trigger
sees. One coherent scenario runs through every root — one robot, one drive, one file,
one action run on it — so the values read as a story rather than as placeholders.

Values are illustrative, not templates for real ids. Every id here is fabricated.
"""

import collections.abc
import datetime
import typing

import pydantic
import pydantic_core

from ...association import Association
from ...experimental.sessions import SessionRecord
from ..actions import (
    ActionProvenance,
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
    ExecutableProvenance,
    InvocationDataSource,
    InvocationDataSourceType,
    InvocationProvenance,
    InvocationRecord,
    InvocationSource,
    InvocationStatus,
    InvocationStatusRecord,
    SourceProvenance,
)
from ..datasets import DatasetRecord
from ..events import EventRecord
from ..files import (
    FileRecord,
    FileStatus,
    IngestionStatus,
)
from ..platform_events import (
    DEFAULT_PLATFORM_EVENT_CATALOG,
    SAMPLE_ACTION_DIGEST,
    SAMPLE_ACTION_NAME,
    SAMPLE_DATASET_ID,
    SAMPLE_EVENT_ID,
    SAMPLE_FILE_ID,
    SAMPLE_INVOCATION_ID,
    SAMPLE_ORG_ID,
    SAMPLE_SESSION_ID,
    SAMPLE_TIME,
    SAMPLE_TRANSACTION_ID,
    SAMPLE_TRIGGER_ID,
    SAMPLE_USER,
    OncePer,
    PlatformEvent,
    PlatformEventCatalog,
    PlatformEventType,
    sample_platform_event,
)
from .namespace import (
    ENVELOPE_ROOT,
    TRIGGER_ROOT,
    EventNamespace,
)
from .record import TriggerRecord
from .sources import EventSubscription, Schedule
from .targets import InvokeActionTarget


def _dataset() -> DatasetRecord:
    return DatasetRecord(
        dataset_id=SAMPLE_DATASET_ID,
        org_id=SAMPLE_ORG_ID,
        name="rover-07 warehouse loop 2026-08-28",
        description="Autonomous warehouse loop, morning shift. Two laps of route B with the new lidar mount.",
        device_id="rover-07",
        metadata={
            "vehicle_id": "rover-07",
            "route": "warehouse-loop-b",
            "operator": "mchen",
            "firmware": "4.12.1",
            "weather": "indoor",
        },
        tags=["validated", "nightly", "lidar-v2"],
        created=SAMPLE_TIME - datetime.timedelta(hours=2),
        created_by=SAMPLE_USER,
        modified=SAMPLE_TIME,
        modified_by=SAMPLE_USER,
    )


def _file() -> FileRecord:
    return FileRecord(
        file_id=SAMPLE_FILE_ID,
        association_id=SAMPLE_DATASET_ID,
        org_id=SAMPLE_ORG_ID,
        name="lap_02.mcap",
        relative_path="logs/lap_02.mcap",
        uri=f"s3://acme-robotics-roboto/{SAMPLE_DATASET_ID}/logs/lap_02.mcap",
        size=734_003_200,
        version=1,
        description="Second lap, full sensor suite.",
        device_id="rover-07",
        metadata={"lap": 2, "sensors": ["lidar", "imu", "camera_front"]},
        tags=["mcap", "lap-02"],
        status=FileStatus.Available,
        ingestion_status=IngestionStatus.Ingested,
        upload_id=SAMPLE_TRANSACTION_ID,
        origination="roboto upload",
        created=SAMPLE_TIME - datetime.timedelta(minutes=40),
        created_by=SAMPLE_USER,
        modified=SAMPLE_TIME,
        modified_by=SAMPLE_USER,
    )


def _invocation() -> InvocationRecord:
    started = SAMPLE_TIME - datetime.timedelta(minutes=12)
    return InvocationRecord(
        invocation_id=SAMPLE_INVOCATION_ID,
        org_id=SAMPLE_ORG_ID,
        created=started,
        data_source=InvocationDataSource(
            data_source_type=InvocationDataSourceType.Dataset,
            data_source_id=SAMPLE_DATASET_ID,
        ),
        input_data=["**/*.mcap"],
        compute_requirements=ComputeRequirements(vCPU=2048, memory=4096),
        container_parameters=ContainerParameters(),
        last_status=InvocationStatus.Completed,
        parameter_values={"topics": "/lidar/points,/imu/data", "downsample_hz": 10},
        provenance=InvocationProvenance(
            action=ActionProvenance(name=SAMPLE_ACTION_NAME, org_id=SAMPLE_ORG_ID, digest=SAMPLE_ACTION_DIGEST),
            executable=ExecutableProvenance(
                container_image_uri=f"123456789012.dkr.ecr.us-west-2.amazonaws.com/{SAMPLE_ACTION_NAME}:1.4.0",
                container_image_digest="sha256:0c8e4f2a6b1d3e5f7a9c1b3d5e7f9a1c3e5b7d9f1a3c5e7b9d1f3a5c7e9b1d3f",
            ),
            source=SourceProvenance(source_type=InvocationSource.Trigger, source_id="tr_3nq7wk2mx9pd"),
        ),
        status=[
            InvocationStatusRecord(status=InvocationStatus.Queued, timestamp=started),
            InvocationStatusRecord(
                status=InvocationStatus.Processing, timestamp=started + datetime.timedelta(minutes=1)
            ),
            InvocationStatusRecord(status=InvocationStatus.Completed, timestamp=SAMPLE_TIME),
        ],
        duration=datetime.timedelta(minutes=11, seconds=48),
        timeout=3600,
        last_heartbeat=SAMPLE_TIME,
    )


def _session() -> SessionRecord:
    return SessionRecord(
        session_id=SAMPLE_SESSION_ID,
        org_id=SAMPLE_ORG_ID,
        name="rover-07 morning shift",
        description="All drives from rover-07's 2026-08-28 morning shift.",
        metadata={"vehicle_id": "rover-07", "shift": "morning"},
        tags=["nightly"],
        min_timestamp_ns=1_787_000_000_000_000_000,
        max_timestamp_ns=1_787_003_600_000_000_000,
        created=SAMPLE_TIME - datetime.timedelta(hours=3),
        created_by=SAMPLE_USER,
        modified=SAMPLE_TIME,
        modified_by=SAMPLE_USER,
    )


def _event() -> EventRecord:
    return EventRecord(
        event_id=SAMPLE_EVENT_ID,
        org_id=SAMPLE_ORG_ID,
        name="hard-brake",
        description="Emergency stop halfway round the warehouse loop.",
        associations=[Association.dataset(SAMPLE_DATASET_ID), Association.file(SAMPLE_FILE_ID)],
        start_time=1_787_000_120_000_000_000,
        end_time=1_787_000_123_500_000_000,
        metadata={"severity": "high", "vehicle_id": "rover-07"},
        tags=["safety"],
        created=SAMPLE_TIME,
        created_by=SAMPLE_USER,
        modified=SAMPLE_TIME,
        modified_by=SAMPLE_USER,
    )


def sample_trigger() -> TriggerRecord:
    """The trigger the sample is evaluated for; what ``{{trigger.*}}`` sees."""
    return TriggerRecord(
        trigger_id=SAMPLE_TRIGGER_ID,
        org_id=SAMPLE_ORG_ID,
        name="ingest-rover-drives",
        enabled=True,
        engine="v2",
        fires_on=EventSubscription(events=[PlatformEventType.FileUploaded], once_per=OncePer.File),
        targets=[
            InvokeActionTarget(
                target_id="ingest", action=ActionReference(name=SAMPLE_ACTION_NAME), required_inputs=["**/*.mcap"]
            )
        ],
        created=SAMPLE_TIME - datetime.timedelta(days=30),
        created_by=SAMPLE_USER,
        modified=SAMPLE_TIME - datetime.timedelta(days=2),
        modified_by=SAMPLE_USER,
    )


def sample_schedule_trigger() -> TriggerRecord:
    """The schedule-fired trigger the ``schedule.fired`` sample is evaluated for, so the
    sample's ``schedule`` root carries the ``cron`` a template may name."""
    return sample_trigger().model_copy(update={"name": "weekly-report", "fires_on": Schedule(cron="0 9 * * 1")})


def _as_json_mapping(record: pydantic.BaseModel) -> collections.abc.Mapping[str, typing.Any]:
    """Dump a record with the same keys and nesting a condition sees, JSON-typed.

    Datetimes come out as ISO strings and enums as their values, which is both what a
    sample carries on the wire and what a ``{{ }}`` placeholder substitutes.
    """
    return record.model_dump(mode="json")


class SampleNamespaceSource:
    """A :class:`NamespaceSource` that hydrates every root from the sample scenario.

    Serves each root the way a real firing does — including ``action`` as the
    invocation's provenance and ``upload`` as the bare transaction id — so a sample
    carries exactly the roots a trigger would see.
    """

    def record_for_root(
        self, root: str, event: PlatformEvent
    ) -> typing.Optional[collections.abc.Mapping[str, typing.Any]]:
        if root == "dataset":
            return _as_json_mapping(_dataset())
        if root == "file":
            return _as_json_mapping(_file())
        if root == "invocation":
            return _as_json_mapping(_invocation())
        if root == "action":
            return _as_json_mapping(_invocation().provenance.action)
        if root == "session":
            return _as_json_mapping(_session())
        if root == "event":
            return _as_json_mapping(_event())
        if root == "upload":
            return {"transaction_id": SAMPLE_TRANSACTION_ID}
        return None


def template_paths(record: collections.abc.Mapping[str, typing.Any], prefix: str) -> list[str]:
    """Every dotted path a template may reference under ``prefix``, in document order.

    Walks nested mappings only. A list is a leaf, because path resolution descends
    through mappings and stops at anything else: ``dataset.tags`` is addressable,
    ``dataset.tags.0`` is not.
    """
    paths: list[str] = []
    for key, value in record.items():
        path = f"{prefix}.{key}"
        paths.append(path)
        if isinstance(value, collections.abc.Mapping) and value:
            paths.extend(template_paths(value, path))
    return paths


class PlatformEventSample(pydantic.BaseModel):
    """One event type, dereferenced: the envelope, every root it exposes, and the
    template paths that resolve against them."""

    event_type: PlatformEventType
    """The event type this sample illustrates."""

    event: dict[str, typing.Any]
    """The event envelope as it would arrive: id, type, time, org, and payload."""

    namespace: dict[str, dict[str, typing.Any]]
    """Every namespace root a condition or template may reference for this event
    type, keyed by root name, with the full record under each. Always includes
    ``envelope`` and ``trigger``; the rest are the catalog's exposed roots for the type."""

    paths: list[str]
    """Every ``root.path`` a ``{{ }}`` placeholder or condition field may name, in
    the order the roots and their fields appear in :attr:`namespace`."""


class PlatformEventSamplesResponse(pydantic.BaseModel):
    """Wire shape of ``GET /v1/triggers/events/samples``: one sample per platform event type."""

    samples: dict[PlatformEventType, PlatformEventSample]


def platform_event_sample(
    event_type: PlatformEventType,
    catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG,
) -> PlatformEventSample:
    """Build the sample for one event type.

    The ``event``, ``changed`` and ``tag`` roots are built by the same
    :class:`EventNamespace` that serves them when a trigger fires; the entity roots are
    exactly the ones ``catalog`` exposes for the type.
    """
    event = sample_platform_event(event_type)
    trigger = sample_schedule_trigger() if event_type is PlatformEventType.ScheduleFired else sample_trigger()
    namespace = EventNamespace(event, SampleNamespaceSource()).bound_to(trigger)
    roots = [ENVELOPE_ROOT, TRIGGER_ROOT, *sorted(catalog.descriptor(event_type).exposed_roots)]

    records: dict[str, dict[str, typing.Any]] = {}
    for root in roots:
        record = namespace.record(root)
        if record is None:
            raise ValueError(f"Sample source hydrated nothing for root {root!r} of {event_type.value!r}.")
        records[root] = dict(pydantic_core.to_jsonable_python(record))

    return PlatformEventSample(
        event_type=event_type,
        event=event.model_dump(mode="json"),
        namespace=records,
        paths=[path for root in roots for path in template_paths(records[root], root)],
    )


def platform_event_samples(
    catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG,
) -> dict[PlatformEventType, PlatformEventSample]:
    """A sample for every event type in ``catalog``, in catalog order."""
    return {descriptor.event_type: platform_event_sample(descriptor.event_type, catalog) for descriptor in catalog}


__all__ = [
    "SAMPLE_TIME",
    "PlatformEventSamplesResponse",
    "PlatformEventSample",
    "SampleNamespaceSource",
    "platform_event_sample",
    "platform_event_samples",
    "sample_platform_event",
    "sample_trigger",
    "template_paths",
]
