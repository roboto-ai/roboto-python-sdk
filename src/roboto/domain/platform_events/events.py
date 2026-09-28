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
"""The CloudEvents spec version :meth:`PlatformEvent.to_cloudevent` produces."""

CLOUDEVENTS_TYPE_PREFIX = "ai.roboto."
"""Reverse-DNS prefix CloudEvents recommends on ``type``. It appears only in what
:meth:`PlatformEvent.to_cloudevent` returns; subscriptions, conditions, and templates
name an event by its bare :class:`PlatformEventType` value (``file.uploaded``)."""


class PlatformEventType(StrEnum):
    """A thing that happens on the platform that triggers can subscribe to.

    Every member has a :class:`~roboto.domain.platform_events.PlatformEventDescriptor` in the
    default :class:`~roboto.domain.platform_events.PlatformEventCatalog` describing its payload
    model, the namespace roots it exposes to conditions and templates, and the
    :class:`~roboto.domain.platform_events.OncePer` values it supports.
    """

    @property
    def cloudevents_type(self) -> str:
        """This type as a CloudEvents ``type`` attribute: ``ai.roboto.file.uploaded``."""
        return f"{CLOUDEVENTS_TYPE_PREFIX}{self.value}"

    @classmethod
    def from_cloudevents_type(cls, value: str) -> "PlatformEventType":
        """Return the event type a CloudEvents ``type`` attribute names; the inverse of :attr:`cloudevents_type`.

        Args:
            value: A prefixed type, such as ``ai.roboto.file.uploaded``.

        Raises:
            ValueError: ``value`` lacks the prefix or names no platform event type.
        """
        if not value.startswith(CLOUDEVENTS_TYPE_PREFIX):
            raise ValueError(
                f"Not a Roboto CloudEvents type (expected the {CLOUDEVENTS_TYPE_PREFIX!r} prefix): {value!r}"
            )
        return cls(value[len(CLOUDEVENTS_TYPE_PREFIX) :])

    FileUploaded = "file.uploaded"
    """A file finished uploading to a dataset."""

    UploadCompleted = "dataset.upload_completed"
    """An upload transaction to a dataset completed (all of its files uploaded)."""

    FileIngested = "file.ingested"
    """A file finished ingestion (post-processing) and its topics are available."""

    FileMetadataUpdated = "file.metadata_updated"
    """A file's metadata or tags changed."""

    DatasetMetadataUpdated = "dataset.metadata_updated"
    """A dataset's metadata or tags changed."""

    DatasetCreated = "dataset.created"
    """A dataset was created."""

    DatasetTagAdded = "dataset.tag_added"
    """One or more tags were added to a dataset."""

    InvocationCompleted = "invocation.completed"
    """An action invocation reached a successful terminal status."""

    InvocationFailed = "invocation.failed"
    """An action invocation reached a failed terminal status (``Failed`` or ``Deadly``)."""

    SessionCreated = "session.created"
    """A session was created."""

    SessionFilesAdded = "session.files_added"
    """Files were added to a session."""

    SessionUpdated = "session.updated"
    """A session's metadata or tags changed."""

    EventCreated = "event.created"
    """An event, the annotation marking a span of time on your data, was created."""

    ScheduleFired = "schedule.fired"
    """A trigger's own schedule reached one of its minutes. Not subscribable: a trigger
    fires on a schedule by declaring a :class:`~roboto.domain.triggers.Schedule` source,
    and the scheduler delivers this occurrence to that trigger alone."""


class FileUploadedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.FileUploaded`."""

    model_config = _FROZEN

    dataset_id: str
    """Dataset the file was uploaded to."""

    file_id: str
    """The uploaded file."""

    transaction_id: typing.Optional[str] = None
    """Upload transaction the file arrived in, when the upload used one."""


class UploadCompletedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.UploadCompleted`."""

    model_config = _FROZEN

    dataset_id: str
    """Dataset the upload targeted."""

    transaction_id: str
    """The completed upload transaction."""


class FileIngestedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.FileIngested`."""

    model_config = _FROZEN

    dataset_id: str
    """Dataset containing the ingested file."""

    file_id: str
    """The ingested file."""

    transaction_id: typing.Optional[str] = None
    """Upload transaction the file arrived in, when known."""


class FileMetadataUpdatedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.FileMetadataUpdated`."""

    model_config = _FROZEN

    dataset_id: str
    """Dataset containing the updated file."""

    file_id: str
    """The file whose metadata changed."""

    changeset: MetadataChangeset
    """The applied metadata/tag delta, served to conditions as the ``changed`` and ``tag`` roots."""


class DatasetMetadataUpdatedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.DatasetMetadataUpdated`."""

    model_config = _FROZEN

    dataset_id: str
    """The dataset whose metadata changed."""

    changeset: MetadataChangeset
    """The applied metadata/tag delta, served to conditions as the ``changed`` and ``tag`` roots."""


class DatasetCreatedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.DatasetCreated`."""

    model_config = _FROZEN

    dataset_id: str
    """The created dataset."""


class DatasetTagAddedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.DatasetTagAdded`."""

    model_config = _FROZEN

    dataset_id: str
    """The tagged dataset."""

    tags_added: list[str]
    """Tags added by the mutation, served to conditions as the ``tag`` root."""


class InvocationCompletedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.InvocationCompleted`."""

    model_config = _FROZEN

    invocation_id: str
    """The completed invocation."""

    action_name: str
    """Name of the invoked action. Unique within :attr:`action_owner_id`'s org."""

    action_owner_id: str
    """Org that owns the invoked action."""

    status: InvocationStatus
    """Terminal status the invocation reached."""


class InvocationFailedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.InvocationFailed`."""

    model_config = _FROZEN

    invocation_id: str
    """The failed invocation."""

    action_name: str
    """Name of the invoked action. Unique within :attr:`action_owner_id`'s org."""

    action_owner_id: str
    """Org that owns the invoked action."""

    status: InvocationStatus
    """Terminal status the invocation reached (``Failed`` or ``Deadly``)."""


class SessionCreatedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.SessionCreated`."""

    model_config = _FROZEN

    session_id: str
    """The created session."""


class EventCreatedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.EventCreated`."""

    model_config = _FROZEN

    event_id: str
    """The created event, an :class:`~roboto.domain.events.EventRecord`."""


class SessionFilesAddedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.SessionFilesAdded`."""

    model_config = _FROZEN

    session_id: str
    """The session files were added to."""

    file_ids: list[str]
    """The added files."""


class SessionUpdatedPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.SessionUpdated`."""

    model_config = _FROZEN

    session_id: str
    """The session whose metadata changed."""

    changeset: MetadataChangeset
    """The applied metadata/tag delta, served to conditions as the ``changed`` and ``tag`` roots."""


class ScheduleFiredPayload(pydantic.BaseModel):
    """Payload for :attr:`PlatformEventType.ScheduleFired`."""

    model_config = _FROZEN

    trigger_id: str
    """The trigger whose schedule fired."""

    scheduled_for: datetime.datetime
    """The scheduled minute (UTC) this occurrence stands for."""


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
    SessionCreatedPayload,
    SessionFilesAddedPayload,
    SessionUpdatedPayload,
    EventCreatedPayload,
    ScheduleFiredPayload,
]
"""Union of every per-type payload model. Which member is legal for a given
:class:`PlatformEvent` is dictated by its :attr:`~PlatformEvent.type`."""


def platform_event_source(api_domain: typing.Optional[str], org_id: str) -> str:
    """Return the CloudEvents ``source`` for one org's events on one deployment.

    The value is the org's own API resource, ``https://{api_domain}/v1/orgs/{org_id}``.
    No two deployments produce the same ``source``, so it pairs with
    :attr:`PlatformEvent.id` to identify a single occurrence.

    Args:
        api_domain: Public API host of the emitting deployment, such as
            ``api.roboto.ai``. Without one, the result is the relative reference
            ``/v1/orgs/{org_id}``.
        org_id: Organization whose events carry this source.
    """
    path = f"/v1/orgs/{org_id}"
    return f"https://{api_domain}{path}" if api_domain else path


class PlatformEvent(pydantic.BaseModel):
    """One occurrence of something that happened on the platform, as a trigger receives it.

    :attr:`id`, :attr:`source`, :attr:`type`, :attr:`time` and :attr:`subject` are the
    CloudEvents 1.0 context attributes; :meth:`to_cloudevent` renders the occurrence in
    that spec's structured-JSON form. The envelope stays thin: :attr:`data` carries
    entity ids and facts fixed at :attr:`time`, such as a metadata delta or a terminal
    status, and never mutable entity state — conditions and target templates read an
    entity's current state at evaluation time through an
    :class:`~roboto.domain.triggers.EventNamespace`.
    """

    model_config = _FROZEN

    id: str
    """Producer-vended event id, unique within :attr:`source`; deterministic where
    possible (e.g. ``evt:{invocation_id}:completed``)."""

    source: str
    """The org and the deployment the event happened in, as built by
    :func:`platform_event_source`."""

    type: PlatformEventType
    """Which kind of event this is. Dictates the concrete model of :attr:`data`."""

    time: datetime.datetime
    """When the event occurred."""

    org_id: str
    """Organization in which the event occurred and whose triggers see it."""

    schema_version: int = 1
    """Version of the envelope + payload schema. Bumped only for breaking changes."""

    data: PlatformEventPayload
    """The per-type payload. Its model must be the one registered for :attr:`type`
    in the default catalog; a mismatch is rejected at validation time."""

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def subject(self) -> str:
        """The entity the event is about, as a ``roboto://`` URI (``roboto://file/fl_1a2b``).

        Computed from :attr:`data` by the event type's catalog descriptor rather than
        stored, so it cannot disagree with the payload, and serialized like a declared
        field.
        """
        return str(self.subject_uri)

    @property
    def subject_uri(self) -> RobotoUri:
        """:attr:`subject` as a parsed :class:`~roboto.uri.RobotoUri`."""
        # Deferred to avoid a module-level cycle: catalog.py imports the models above.
        from .catalog import (
            DEFAULT_PLATFORM_EVENT_CATALOG,
        )

        return DEFAULT_PLATFORM_EVENT_CATALOG.descriptor(self.type).subject(self)

    def to_cloudevent(self) -> dict[str, typing.Any]:
        """Return this event as CloudEvents 1.0 structured JSON (``application/cloudevents+json``).

        Nothing serializes it yet: the command bus carries the model itself. It exists
        so an outbound webhook body needs no redesign.

        Context attributes sit at the top level under their spec names, with ``type``
        carrying :data:`CLOUDEVENTS_TYPE_PREFIX` and ``datacontenttype`` fixed at
        ``application/json``. :attr:`org_id` and :attr:`schema_version` arrive as the
        extension attributes ``orgid`` and ``schemaversion``, because extension names
        must be lowercase alphanumerics. The returned dict is JSON-serializable as-is.
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
        """Parse ``data`` with the payload model the catalog registers for ``type``.

        Several payload models are field-for-field identical — ``FileUploadedPayload``
        and ``FileIngestedPayload``, ``InvocationCompletedPayload`` and
        ``InvocationFailedPayload`` — so left-to-right union coercion would bind a raw
        dict to whichever comes first in :data:`PlatformEventPayload`. Looking the model
        up by ``type`` picks the right one; an already-constructed payload of a
        different class raises ``ValueError``.
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
    "FileIngestedPayload",
    "FileMetadataUpdatedPayload",
    "FileUploadedPayload",
    "InvocationCompletedPayload",
    "InvocationFailedPayload",
    "PlatformEvent",
    "PlatformEventPayload",
    "PlatformEventType",
    "ScheduleFiredPayload",
    "SessionCreatedPayload",
    "SessionFilesAddedPayload",
    "SessionUpdatedPayload",
    "UploadCompletedPayload",
    "platform_event_source",
]
