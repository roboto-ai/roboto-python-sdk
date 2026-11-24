# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

import pydantic
import pydantic_core

from ...association import Association
from ...experimental import events as experimental_events
from ...experimental.sessions import (
    SessionRecord,
    SessionStatus,
)
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
    SAMPLE_FILE_VERSION,
    SAMPLE_INVOCATION_ID,
    SAMPLE_ORG_ID,
    SAMPLE_SESSION_EVENT_ID,
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
    session_event_root,
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
        version=SAMPLE_FILE_VERSION,
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
        status=SessionStatus.Complete,
        completed_at=SAMPLE_TIME - datetime.timedelta(minutes=30),
        completed_by=SAMPLE_USER,
        ingested_at=SAMPLE_TIME,
        ingestion_count=1,
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


def _session_event() -> experimental_events.EventRecord:
    return experimental_events.EventRecord(
        event_id=SAMPLE_SESSION_EVENT_ID,
        org_id=SAMPLE_ORG_ID,
        name="hard-brake",
        description="Emergency stop halfway round the warehouse loop.",
        session_id=SAMPLE_SESSION_ID,
        topics=[
            experimental_events.EventTopic(
                topic_id="ti_6r2m8kq4xw7p",
                topic_name="/imu",
                fields=[experimental_events.EventTopicField(field_id="sf_3k8w2mq7xp4n", path_in_schema=("accel", "x"))],
            )
        ],
        start_time=1_787_000_120_000_000_000,
        end_time=1_787_000_123_500_000_000,
        metadata={"severity": "high"},
        tags=["safety"],
        created=SAMPLE_TIME,
        created_by=SAMPLE_USER,
        modified=SAMPLE_TIME,
        modified_by=SAMPLE_USER,
    )


def sample_trigger() -> TriggerRecord:
    """Build the sample trigger, which the ``trigger`` root shows in every sample but one.

    It subscribes to :py:attr:`~roboto.domain.platform_events.PlatformEventType.FileUploaded` once per file and
    invokes the sample action on the file's ``.mcap`` files. The
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.ScheduleFired` sample shows
    ``sample_schedule_trigger`` instead.
    """
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
    """Build the sample trigger that the sample of a schedule firing shows.

    It is ``sample_trigger`` renamed ``weekly-report`` and fired by the cron schedule
    ``0 9 * * 1`` in place of an event subscription, so the
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.ScheduleFired` sample's ``schedule`` root includes the
    ``cron`` a template may name.
    """
    return sample_trigger().model_copy(update={"name": "weekly-report", "fires_on": Schedule(cron="0 9 * * 1")})


def _as_json_mapping(record: pydantic.BaseModel) -> collections.abc.Mapping[str, typing.Any]:
    """Dump a record the way a real firing's entity root reads it: datetimes as ISO strings, enums as values."""
    return record.model_dump(mode="json")


class SampleNamespaceSource:
    """Namespace source that loads every entity root, such as ``dataset`` and ``file``, from the sample records.

    Each root has the shape it has when a trigger fires: ``action`` is the sample invocation's action provenance, and
    ``upload`` holds only the upload's ``transaction_id``. Pass it to :py:class:`~roboto.domain.triggers.EventNamespace`
    with a sample platform event to evaluate a condition or template against the sample scenario.
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
            # A session event's event root has a session and topics in place of a dataset event's associations,
            # as in a real firing.
            if event.type is PlatformEventType.SessionEventCreated:
                return session_event_root(_session_event())
            return _as_json_mapping(_event())
        if root == "upload":
            return {"transaction_id": SAMPLE_TRANSACTION_ID}
        return None


def template_paths(record: collections.abc.Mapping[str, typing.Any], prefix: str) -> list[str]:
    """Return every dotted path a condition field or ``{{ }}`` placeholder may name in ``record``, in key order.

    Descends into nested mappings only. A list is a leaf, because a path resolves through mappings and stops at
    anything else: ``dataset.tags`` resolves, ``dataset.tags.0`` does not.

    Args:
        record: Record of one namespace root, such as a dataset's.
        prefix: Path of ``record`` itself, such as ``"dataset"``. Every returned path begins with it and a dot.
    """
    paths: list[str] = []
    for key, value in record.items():
        path = f"{prefix}.{key}"
        paths.append(path)
        if isinstance(value, collections.abc.Mapping) and value:
            paths.extend(template_paths(value, path))
    return paths


class PlatformEventSample(pydantic.BaseModel):
    """Sample of one platform event type: the event, every root it exposes, and the paths that resolve against them.

    Use a sample to see what a trigger's condition fields and target template placeholders, such as
    ``{{dataset.name}}``, resolve to before writing them. A sample is built with the same
    :py:class:`~roboto.domain.triggers.EventNamespace` and record models that serve a real firing, so its roots have
    the shape a trigger sees. Every sample describes one scenario: one organization, robot, dataset, file, session,
    and action invocation. The values are made up and name nothing that exists in Roboto. Carried in
    ``PlatformEventSamplesResponse.samples``.
    """

    event_type: PlatformEventType
    """Platform event type the sample shows."""

    event: dict[str, typing.Any]
    """:py:class:`~roboto.domain.platform_events.PlatformEvent` as a JSON-compatible dictionary.

    It is the sample platform event, with its payload under ``data``.
    """

    namespace: dict[str, dict[str, typing.Any]]
    """Record of every root a condition or template may read for this event type, keyed by root name.

    Begins with ``envelope`` and ``trigger``, then the roots the catalog exposes for the event type, sorted by name.
    """

    paths: list[str]
    """Every ``root.path`` a condition field or ``{{ }}`` placeholder may name.

    The paths follow the order of the roots and their fields in ``namespace``.
    """


class PlatformEventSamplesResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.triggers.Trigger.platform_event_samples`."""

    samples: dict[PlatformEventType, PlatformEventSample]
    """One sample per platform event type, keyed by type.

    A sample whose type this SDK's :py:class:`~roboto.domain.platform_events.PlatformEventType` does not name is
    left out, so the response still parses when Roboto offers an event type newer than this SDK.
    """

    @pydantic.field_validator("samples", mode="before")
    @classmethod
    def _omit_unknown_event_types(cls, samples: typing.Any) -> typing.Any:
        if not isinstance(samples, collections.abc.Mapping):
            return samples
        known = {member.value for member in PlatformEventType}
        return {event_type: sample for event_type, sample in samples.items() if event_type in known}


def platform_event_sample(
    event_type: PlatformEventType,
    catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG,
) -> PlatformEventSample:
    """Build the sample of one platform event type.

    The ``envelope``, ``trigger``, ``changed``, ``tag`` and ``schedule`` roots come from the same
    :py:class:`~roboto.domain.triggers.EventNamespace` that serves them when a trigger fires. The entity roots, such as
    ``dataset`` and ``file``, come from ``SampleNamespaceSource``.

    Args:
        event_type: Platform event type to return the sample of.
        catalog: Catalog that says which roots ``event_type`` exposes. Defaults to
            :py:const:`~roboto.domain.platform_events.DEFAULT_PLATFORM_EVENT_CATALOG`.

    Raises:
        ValueError: This version of the SDK has no sample payload for ``event_type``, ``catalog`` has no descriptor
            for it, or ``catalog`` exposes a root the sample scenario cannot fill.
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
    """Build the sample of every platform event type in ``catalog``, keyed by event type, in catalog order.

    Args:
        catalog: Catalog of the event types to return samples of, and of the roots each exposes. Defaults to
            :py:const:`~roboto.domain.platform_events.DEFAULT_PLATFORM_EVENT_CATALOG`.

    Raises:
        ValueError: This version of the SDK has no sample payload for one of the event types, or ``catalog`` exposes
            a root the sample scenario cannot fill.
    """
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
