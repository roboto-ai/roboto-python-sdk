# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...updates import MetadataChangeset
from ...uri import RobotoUri
from ..actions.invocation_record import (
    InvocationStatus,
)

_FROZEN = pydantic.ConfigDict(frozen=True)

CLOUDEVENTS_SPECVERSION = "1.0"
"""CloudEvents specification version that the CloudEvents form of a platform event follows.

That form is what ``PlatformEvent.to_cloudevent`` produces.
"""

CLOUDEVENTS_TYPE_PREFIX = "ai.roboto."
"""Prefix of the CloudEvents ``type`` attribute, in the reverse-DNS form CloudEvents recommends.

It appears only in what ``PlatformEvent.to_cloudevent`` returns. Trigger subscriptions, conditions, and templates name
an event type by its bare ``PlatformEventType`` value, such as ``file.uploaded``.
"""


class PlatformEventType(StrEnum):
    """Kind of platform event: something Roboto reports happening in an organization, such as a file being ingested.

    Triggers can subscribe to every kind except ``ScheduleFired``. Every member has a
    :py:class:`~roboto.domain.platform_events.PlatformEventDescriptor` in
    :py:const:`~roboto.domain.platform_events.DEFAULT_PLATFORM_EVENT_CATALOG` that gives its payload model, the names
    (namespace roots, such as ``dataset``) a trigger's conditions and target templates can read from it, and the
    :py:class:`~roboto.domain.platform_events.OncePer` values it supports.
    """

    @property
    def cloudevents_type(self) -> str:
        """CloudEvents ``type`` attribute for this event type, such as ``ai.roboto.file.uploaded``."""
        return f"{CLOUDEVENTS_TYPE_PREFIX}{self.value}"

    @classmethod
    def from_cloudevents_type(cls, value: str) -> "PlatformEventType":
        """Return the event type that a CloudEvents ``type`` attribute names.

        Inverse of ``cloudevents_type``.

        Args:
            value: CloudEvents ``type`` attribute, such as ``ai.roboto.file.uploaded``.

        Raises:
            ValueError: ``value`` lacks the ``ai.roboto.`` prefix, or names no platform event type.
        """
        if not value.startswith(CLOUDEVENTS_TYPE_PREFIX):
            raise ValueError(
                f"Not a Roboto CloudEvents type (expected the {CLOUDEVENTS_TYPE_PREFIX!r} prefix): {value!r}"
            )
        return cls(value[len(CLOUDEVENTS_TYPE_PREFIX) :])

    FileUploaded = "file.uploaded"
    """A file finished uploading to a dataset."""

    UploadCompleted = "dataset.upload_completed"
    """An upload transaction to a dataset completed, with all of its files uploaded."""

    FileIngested = "file.ingested"
    """A file finished ingestion, and its topics are available."""

    FileMetadataUpdated = "file.metadata_updated"
    """A file's metadata or tags changed."""

    DatasetMetadataUpdated = "dataset.metadata_updated"
    """A dataset's metadata or tags changed."""

    DatasetCreated = "dataset.created"
    """A dataset was created."""

    DatasetTagAdded = "dataset.tag_added"
    """One or more tags were added to a dataset."""

    InvocationCompleted = "invocation.completed"
    """An invocation of an action ended in the :py:attr:`~roboto.domain.actions.InvocationStatus.Completed` status."""

    InvocationFailed = "invocation.failed"
    """An invocation of an action ended in failure.

    Its status is :py:attr:`~roboto.domain.actions.InvocationStatus.Failed` or
    :py:attr:`~roboto.domain.actions.InvocationStatus.Deadly`.
    """

    SessionIngested = "session.ingested"
    """Every ingestable file in a complete session is ingested.

    Roboto emits it again, as a new occurrence, each time the session's ingestable files change and are all ingested
    again.
    """

    EventCreated = "event.created"
    """An event (:py:class:`~roboto.domain.events.Event`) was created on a dataset, or on its files or topics.

    An event is an annotation over a span of time. Creating an event on a session emits ``SessionEventCreated``
    instead.
    """

    SessionEventCreated = "session_event.created"
    """An event (``roboto.experimental.events.Event``) was created on a session."""

    ScheduleFired = "schedule.fired"
    """A trigger's schedule reached one of its scheduled minutes.

    Triggers cannot subscribe to it. A trigger runs on a schedule by declaring a
    :py:class:`~roboto.domain.triggers.Schedule` source, and Roboto delivers this occurrence to that trigger alone.
    """


class FileUploadedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.FileUploaded`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the dataset the file was uploaded to."""

    file_id: str
    """ID of the uploaded file."""

    file_version: typing.Optional[int] = None
    """Version of the file when Roboto emitted the event, or ``None`` on events recorded before Roboto stored it.

    A newer version may exist by the time a trigger evaluates the event, because changing the file's metadata or tags
    advances its version just as overwriting its contents does.
    """

    transaction_id: typing.Optional[str] = None
    """ID of the upload transaction the file arrived in, or ``None`` if the upload used none."""


class UploadCompletedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.UploadCompleted`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the dataset the upload went to."""

    transaction_id: str
    """ID of the completed upload transaction."""


class FileIngestedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.FileIngested`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the dataset containing the ingested file."""

    file_id: str
    """ID of the ingested file."""

    file_version: typing.Optional[int] = None
    """Version of the file when Roboto emitted the event, or ``None`` on events recorded before Roboto stored it.

    A newer version may exist by the time a trigger evaluates the event, because changing the file's metadata or tags
    advances its version just as overwriting its contents does.
    """

    transaction_id: typing.Optional[str] = None
    """ID of the upload transaction the file arrived in, or ``None`` if it is not known."""


class FileMetadataUpdatedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.FileMetadataUpdated`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the dataset containing the file."""

    file_id: str
    """ID of the file whose metadata or tags changed."""

    file_version: typing.Optional[int] = None
    """Version of the file when Roboto emitted the event, or ``None`` on events recorded before Roboto stored it.

    A newer version may exist by the time a trigger evaluates the event, because changing the file's metadata or tags
    advances its version just as overwriting its contents does.
    """

    changeset: MetadataChangeset
    """Change made to the file's metadata and tags, which conditions read as the ``changed`` and ``tag`` roots."""


class DatasetMetadataUpdatedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.DatasetMetadataUpdated`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the dataset whose metadata or tags changed."""

    changeset: MetadataChangeset
    """Change made to the dataset's metadata and tags, which conditions read as the ``changed`` and ``tag`` roots."""


class DatasetCreatedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.DatasetCreated`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the created dataset."""


class DatasetTagAddedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.DatasetTagAdded`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    dataset_id: str
    """ID of the tagged dataset."""

    tags_added: list[str]
    """Tags the change added to the dataset, which conditions read as the ``tag`` root."""


class InvocationCompletedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.InvocationCompleted`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    invocation_id: str
    """ID of the completed invocation."""

    action_name: str
    """Name of the invoked action, unique within the organization that owns it."""

    action_owner_id: str
    """ID of the organization that owns the invoked action."""

    status: InvocationStatus
    """Status the invocation ended in, always :py:attr:`~roboto.domain.actions.InvocationStatus.Completed`."""


class InvocationFailedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.InvocationFailed`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    invocation_id: str
    """ID of the failed invocation."""

    action_name: str
    """Name of the invoked action, unique within the organization that owns it."""

    action_owner_id: str
    """ID of the organization that owns the invoked action."""

    status: InvocationStatus
    """Status the invocation ended in, one of the two failure statuses.

    Either :py:attr:`~roboto.domain.actions.InvocationStatus.Failed` or
    :py:attr:`~roboto.domain.actions.InvocationStatus.Deadly`.
    """


class EventCreatedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.EventCreated`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    event_id: str
    """ID of the created event (:py:class:`~roboto.domain.events.Event`), beginning with ``ev_``."""


class SessionEventCreatedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.SessionEventCreated`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    event_id: str
    """ID of the created event (``roboto.experimental.events.Event``), beginning with ``evt_``."""

    session_id: str
    """ID of the session the event belongs to."""


class SessionIngestedPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.SessionIngested`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    session_id: str
    """ID of the session whose ingestable files are all ingested."""

    ingestion_number: int
    """Number of times Roboto has emitted this event for the session, counting this one, so the first is 1."""


class ScheduleFiredPayload(pydantic.BaseModel):
    """Payload of a ``PlatformEventType.ScheduleFired`` platform event.

    Carried in ``PlatformEvent.data``.
    """

    model_config = _FROZEN

    trigger_id: str
    """ID of the trigger whose schedule reached the minute."""

    scheduled_for: datetime.datetime
    """Scheduled minute, in UTC, that this occurrence is for."""


PlatformEventPayload = typing.Union[
    FileUploadedPayload,
    UploadCompletedPayload,
    FileIngestedPayload,
    FileMetadataUpdatedPayload,
    DatasetMetadataUpdatedPayload,
    DatasetCreatedPayload,
    DatasetTagAddedPayload,
    InvocationCompletedPayload,
    InvocationFailedPayload,
    SessionIngestedPayload,
    EventCreatedPayload,
    SessionEventCreatedPayload,
    ScheduleFiredPayload,
]
"""Payload of a platform event of any kind: one of the payload models, one per platform event type.

The models are ``FileUploadedPayload``, ``UploadCompletedPayload``, ``FileIngestedPayload``,
``FileMetadataUpdatedPayload``, ``DatasetMetadataUpdatedPayload``, ``DatasetCreatedPayload``,
``DatasetTagAddedPayload``, ``InvocationCompletedPayload``, ``InvocationFailedPayload``, ``SessionIngestedPayload``,
``EventCreatedPayload``, ``SessionEventCreatedPayload``, and ``ScheduleFiredPayload``.

The ``type`` of a ``PlatformEvent`` determines which one its ``data`` must be.
"""


def platform_event_source(api_domain: typing.Optional[str], org_id: str) -> str:
    """Build the CloudEvents ``source`` of one organization's platform events on one deployment of Roboto.

    Roboto calls this when it emits a platform event. Each deployment has its own API domain, so an event's
    ``PlatformEvent.source`` and ``PlatformEvent.id`` together identify one occurrence.

    Args:
        api_domain: Public API host of the deployment that emits the events, such as ``api.roboto.ai``. ``None`` or an
            empty string returns the relative reference ``/v1/orgs/{org_id}``.
        org_id: ID of the organization whose events carry this source.

    Returns:
        The organization's API resource, ``https://{api_domain}/v1/orgs/{org_id}``.
    """
    path = f"/v1/orgs/{org_id}"
    return f"https://{api_domain}{path}" if api_domain else path


class PlatformEvent(pydantic.BaseModel):
    """One occurrence of something that happened in an organization, as a trigger receives it.

    ``id``, ``source``, ``type``, ``time`` and ``subject`` are the CloudEvents context attributes, and
    ``to_cloudevent`` returns the occurrence in that specification's structured JSON form. ``data`` carries entity IDs
    and facts fixed at ``time``, such as a metadata change or a terminal status, but never an entity's current state.
    Conditions and target templates read the current state when the trigger evaluates the event, through an
    :py:class:`~roboto.domain.triggers.EventNamespace`.

    Validation raises ``pydantic.ValidationError`` when ``data`` is not the payload model registered for ``type``.
    """

    model_config = _FROZEN

    id: str
    """ID of the event, unique within ``source``, such as ``evt:iv_12345:completed``.

    For most event types, Roboto builds the ID from the entity and the occurrence, so delivering one occurrence twice
    gives the same ID.
    """

    source: str
    """URI of the organization and deployment of Roboto the event happened in.

    ``platform_event_source`` builds it.
    """

    type: PlatformEventType
    """Kind of event, which determines the payload model of ``data``."""

    time: datetime.datetime
    """Time the event occurred."""

    org_id: str
    """ID of the organization the event happened in, whose triggers receive it."""

    schema_version: int = 1
    """Version of the schema of this event and its payload, which increases only with a change that breaks readers."""

    data: PlatformEventPayload
    """Payload of the event, whose model depends on ``type``.

    The model is the one :py:const:`~roboto.domain.platform_events.DEFAULT_PLATFORM_EVENT_CATALOG` registers for
    ``type``.
    """

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def subject(self) -> str:
        """Entity the event is about, as a ``roboto://`` URI such as ``roboto://file/fl_12345``.

        Derived from ``data`` rather than stored, so it always agrees with the payload. It serializes like a declared
        field.
        """
        return str(self.subject_uri)

    @property
    def subject_uri(self) -> RobotoUri:
        """Entity the event is about, as a parsed :py:class:`~roboto.uri.RobotoUri`."""
        # Deferred to avoid a module-level cycle: catalog.py imports the models above.
        from .catalog import (
            DEFAULT_PLATFORM_EVENT_CATALOG,
        )

        return DEFAULT_PLATFORM_EVENT_CATALOG.descriptor(self.type).subject(self)

    def to_cloudevent(self) -> dict[str, typing.Any]:
        """Return this event as CloudEvents 1.0 structured JSON (``application/cloudevents+json``).

        The context attributes sit at the top level under their specification names. ``type`` carries the
        ``CLOUDEVENTS_TYPE_PREFIX`` prefix, and ``datacontenttype`` is always ``application/json``. ``org_id`` and
        ``schema_version`` appear as the extension attributes ``orgid`` and ``schemaversion``, because CloudEvents
        extension names must be lowercase letters and digits. The returned dict is JSON-serializable as it is.
        """
        as_json = self.model_dump(mode="json")
        return {
            "specversion": CLOUDEVENTS_SPECVERSION,
            "id": self.id,
            "source": self.source,
            "type": self.type.cloudevents_type,
            "time": as_json["time"],
            "subject": self.subject,
            "datacontenttype": "application/json",
            "orgid": self.org_id,
            "schemaversion": self.schema_version,
            "data": as_json["data"],
        }

    @pydantic.model_validator(mode="before")
    @classmethod
    def _bind_payload_to_type(cls, values: typing.Any) -> typing.Any:
        """Parse ``data`` with the payload model the default catalog registers for ``type``.

        Some payload models have the same fields (``FileUploadedPayload`` and ``FileIngestedPayload``,
        ``InvocationCompletedPayload`` and ``InvocationFailedPayload``), so pydantic's union matching cannot tell them
        apart and would parse a raw dict as whichever comes first in ``PlatformEventPayload``. Looking the model up by
        ``type`` picks the right one. An already-built payload of another class raises ``ValueError``.
        """
        if not isinstance(values, collections.abc.Mapping):
            return values

        # Deferred to avoid a module-level cycle: catalog.py imports the models above.
        from .catalog import (
            DEFAULT_PLATFORM_EVENT_CATALOG,
        )

        raw_type: typing.Any = values.get("type")
        try:
            event_type = PlatformEventType(raw_type)
        except ValueError:
            return values  # Let field validation report the unknown type.

        payload_model = DEFAULT_PLATFORM_EVENT_CATALOG.descriptor(event_type).payload_model
        data = values.get("data")
        if isinstance(data, pydantic.BaseModel):
            if type(data) is not payload_model:
                raise ValueError(
                    f"Event type {event_type.value!r} requires a {payload_model.__name__} payload, "
                    f"got {type(data).__name__}."
                )
            return values
        if isinstance(data, collections.abc.Mapping):
            return {**values, "data": payload_model.model_validate(data)}
        return values


__all__ = [
    "CLOUDEVENTS_SPECVERSION",
    "CLOUDEVENTS_TYPE_PREFIX",
    "DatasetCreatedPayload",
    "DatasetMetadataUpdatedPayload",
    "DatasetTagAddedPayload",
    "EventCreatedPayload",
    "FileIngestedPayload",
    "FileMetadataUpdatedPayload",
    "FileUploadedPayload",
    "InvocationCompletedPayload",
    "InvocationFailedPayload",
    "PlatformEvent",
    "PlatformEventPayload",
    "PlatformEventType",
    "ScheduleFiredPayload",
    "SessionEventCreatedPayload",
    "SessionIngestedPayload",
    "UploadCompletedPayload",
    "platform_event_source",
]
