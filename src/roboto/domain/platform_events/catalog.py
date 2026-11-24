# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import dataclasses
import types
import typing

import pydantic

from ...uri import (
    RobotoUri,
    RobotoUriType,
)
from .events import (
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
    PlatformEventType,
    ScheduleFiredPayload,
    SessionEventCreatedPayload,
    SessionIngestedPayload,
    UploadCompletedPayload,
)
from .once_per import OncePer

OncePerProjection = typing.Callable[[PlatformEvent], str]
"""Function that reads a platform event, and returns the value a trigger fires once per, such as the dataset's ID.

A projection reads the event's payload and nothing else: one event in, one string out, with no request to Roboto. A
``once_per`` value can therefore name only what the event itself identifies; there is no "once per file in the dataset
this event is about". ``once_per`` only collapses repeated events into one run of each target; it never fans one event
out into several runs, and a trigger runs each of its targets at most once per event.
"""


ENVELOPE_ROOT = "envelope"
"""Root of the trigger condition and template fields that read the platform event itself.

These fields read the event's ``id``, ``source``, ``subject``, ``type``, ``time`` and ``org_id``, and under ``data``
its payload as published. No descriptor may list this root in ``exposed_roots``.
"""

TRIGGER_ROOT = "trigger"
"""Root of the trigger condition and template fields that read the trigger being evaluated.

No descriptor may list this root in ``exposed_roots``.
"""

RESERVED_ROOTS = frozenset({ENVELOPE_ROOT, TRIGGER_ROOT})
"""Roots Roboto fills in for every event, which no descriptor may list in ``exposed_roots``.

They are ``ENVELOPE_ROOT`` and ``TRIGGER_ROOT``. The event or the trigger would hide a descriptor's root of the same
name, so a descriptor that lists one in ``exposed_roots`` raises ``ValueError``.
"""

DATASET_ROOT = "dataset"
"""Root of the fields that read the dataset an event is about or happened within.

An action target's ``required_inputs`` and ``additional_inputs`` patterns match that dataset's files, so a trigger may
set them only when every event it fires for exposes this root.
"""


def _subject_id(event: PlatformEvent, field: str) -> str:
    """Return one identifier from the event's payload, the only input a projection has.

    Raises:
        ValueError: The payload has no string field named ``field``. Not raised for the default catalog's
            projections: validating a :py:class:`~roboto.domain.platform_events.PlatformEvent` parses ``data`` with
            the payload model registered for its type, and each of those descriptors registers only projections its
            payload model supports.
    """
    value = getattr(event.data, field, None)
    if not isinstance(value, str):
        raise ValueError(
            f"Cannot project a {event.type.value!r} event onto {field!r}: its payload "
            f"({type(event.data).__name__}) carries no such identifier."
        )
    return value


def _event_id(event: PlatformEvent) -> str:
    return event.id


def _dataset_id(event: PlatformEvent) -> str:
    return _subject_id(event, "dataset_id")


def _file_id(event: PlatformEvent) -> str:
    return _subject_id(event, "file_id")


def _invocation_id(event: PlatformEvent) -> str:
    return _subject_id(event, "invocation_id")


def _annotation_event_id(event: PlatformEvent) -> str:
    return _subject_id(event, "event_id")


SubjectProjection = typing.Callable[[PlatformEvent], RobotoUri]
"""Function that reads a platform event, and returns the ``roboto://`` URI of the entity it is about.

That URI is the event's CloudEvents ``subject``. Like ``OncePerProjection``, it reads only the payload, so it can name
only an entity the event itself identifies.
"""


@dataclasses.dataclass(frozen=True)
class PlatformEventDescriptor:
    """Description of one platform event type: its payload, the fields triggers can read, and its ``once_per`` values.

    A root is the first segment of a field path in a trigger's condition or target templates, such as ``dataset`` in
    ``dataset.metadata.vehicle_id``. A descriptor lists the roots its event type exposes and the root a condition field
    with no root reads from. It also maps each :py:class:`~roboto.domain.platform_events.OncePer` value the event type
    supports to a ``OncePerProjection``, which computes the value a trigger with that ``once_per`` fires once per.

    Raises:
        ValueError: ``default_root`` is not in ``exposed_roots``, ``once_per_projections`` has no entry for
            :py:attr:`~roboto.domain.platform_events.OncePer.Occurrence`, or ``exposed_roots`` includes a root in
            ``RESERVED_ROOTS``.
    """

    event_type: PlatformEventType
    """Event type this descriptor describes."""

    payload_model: type[pydantic.BaseModel]
    """Pydantic model of :py:attr:`~roboto.domain.platform_events.PlatformEvent.data` for this event type."""

    exposed_roots: frozenset[str]
    """Roots this event type exposes to trigger conditions and target templates.

    Examples are ``dataset``, ``file`` and ``changed``.
    """

    default_root: str
    """Root that a condition field with no root reads from. Always one of ``exposed_roots``."""

    once_per_projections: collections.abc.Mapping[OncePer, OncePerProjection]
    """``once_per`` values this event type supports, each mapped to its projection.

    A value absent from the keys is unsupported, and every event type supports
    :py:attr:`~roboto.domain.platform_events.OncePer.Occurrence`.
    """

    subject_type: RobotoUriType
    """Kind of entity this event is about, its CloudEvents ``subject``.

    The payload carries that entity's ID under ``<subject_type>_id`` and may say more about it, such as the version a
    file was at. The rest of the payload is context around the entity, such as the upload transaction a file arrived in
    or the metadata changes applied.
    """

    subscribable: bool = True
    """Whether a trigger may name this event type in an :py:class:`~roboto.domain.triggers.EventSubscription`.

    ``False`` for an event Roboto delivers to a single trigger rather than to every subscriber, such as a trigger's
    schedule reaching one of its minutes. Such an event type still has a descriptor, so its ``once_per`` values and
    roots work the same way.
    """

    def __post_init__(self) -> None:
        if self.default_root not in self.exposed_roots:
            raise ValueError(
                f"Descriptor for {self.event_type.value!r}: default root {self.default_root!r} "
                f"must be one of its exposed roots {sorted(self.exposed_roots)}."
            )
        if OncePer.Occurrence not in self.once_per_projections:
            raise ValueError(
                f"Descriptor for {self.event_type.value!r} must support once_per='occurrence'; every event does."
            )
        claimed = self.exposed_roots & RESERVED_ROOTS
        if claimed:
            raise ValueError(
                f"Descriptor for {self.event_type.value!r} exposes {sorted(claimed)}, which the evaluation "
                f"namespace serves itself; an entity root cannot share a reserved name."
            )
        object.__setattr__(self, "once_per_projections", types.MappingProxyType(dict(self.once_per_projections)))

    @property
    def supported_once_per(self) -> frozenset[OncePer]:
        """:py:class:`~roboto.domain.platform_events.OncePer` values this event type supports."""
        return frozenset(self.once_per_projections)

    def supports_once_per(self, once_per: OncePer) -> bool:
        """Return whether this event type supports ``once_per``.

        Args:
            once_per: Value to check.
        """
        return once_per in self.once_per_projections

    def subject(self, event: PlatformEvent) -> RobotoUri:
        """Return the ``roboto://`` URI of the entity ``event`` is about.

        Args:
            event: Event to name the subject of. Must be of this descriptor's event type.

        Raises:
            ValueError: ``event`` is of another event type.
        """
        if event.type is not self.event_type:
            raise ValueError(
                f"Cannot name the subject of a {event.type.value!r} event "
                f"with the {self.event_type.value!r} descriptor."
            )
        return RobotoUri(self.subject_type, _subject_id(event, f"{self.subject_type.value}_id"))

    def idempotency_token(self, event: PlatformEvent, once_per: OncePer) -> str:
        """Return the token that identifies ``event`` for a trigger that fires once per ``once_per``.

        A trigger runs each of its targets at most once for all the events that share a token.

        Args:
            event: Event to compute the token for. Must be of this descriptor's event type.
            once_per: What the trigger fires once per.

        Returns:
            Token of the form ``<event type>|<once_per>:<value>``, such as ``file.uploaded|dataset:ds_12345``.

        Raises:
            ValueError: ``event`` is of another event type, or this event type does not support ``once_per``.
        """
        if event.type is not self.event_type:
            raise ValueError(
                f"Cannot build an idempotency token for a {event.type.value!r} event "
                f"with the {self.event_type.value!r} descriptor."
            )
        projection = self.once_per_projections.get(once_per)
        if projection is None:
            supported = sorted(member.value for member in self.once_per_projections)
            raise ValueError(
                f"once_per={once_per.value!r} is not supported by event type {self.event_type.value!r}; "
                f"supported once_per values: {supported}."
            )
        return f"{self.event_type.value}|{once_per.value}:{projection(event)}"


class PlatformEventCatalog:
    """Set of platform event descriptors, at most one per event type, looked up by type.

    Everything that varies by event type, such as the payload model, the roots and the ``once_per`` values, is on the
    ``PlatformEventDescriptor`` registered for it. ``DEFAULT_PLATFORM_EVENT_CATALOG`` registers every
    :py:class:`~roboto.domain.platform_events.PlatformEventType`; you may build a catalog of a subset. Iterating a
    catalog yields its descriptors, and ``event_type in catalog`` tests whether one is registered for ``event_type``.

    Args:
        descriptors: Descriptors to register, at most one per event type.

    Raises:
        ValueError: Two descriptors share an event type.
    """

    def __init__(self, descriptors: collections.abc.Iterable[PlatformEventDescriptor]) -> None:
        self.__descriptors: dict[PlatformEventType, PlatformEventDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.event_type in self.__descriptors:
                raise ValueError(f"Duplicate descriptor for event type {descriptor.event_type.value!r}.")
            self.__descriptors[descriptor.event_type] = descriptor

    def __contains__(self, event_type: PlatformEventType) -> bool:
        return event_type in self.__descriptors

    def __iter__(self) -> collections.abc.Iterator[PlatformEventDescriptor]:
        return iter(self.__descriptors.values())

    def descriptor(self, event_type: PlatformEventType) -> PlatformEventDescriptor:
        """Return the descriptor for ``event_type``.

        Args:
            event_type: Event type to look up.

        Raises:
            ValueError: No descriptor is registered for ``event_type``.
        """
        descriptor = self.__descriptors.get(event_type)
        if descriptor is None:
            raise ValueError(f"No descriptor registered for event type {event_type.value!r}.")
        return descriptor

    def exposed_roots(self, event_type: PlatformEventType) -> frozenset[str]:
        """Return the roots ``event_type`` exposes to trigger conditions and target templates.

        Args:
            event_type: Event type to look up.

        Raises:
            ValueError: No descriptor is registered for ``event_type``.
        """
        return self.descriptor(event_type).exposed_roots

    def subscribable_types(self) -> frozenset[PlatformEventType]:
        """Return the event types a trigger may subscribe to."""
        return frozenset(descriptor.event_type for descriptor in self if descriptor.subscribable)

    def namespace_roots(self) -> frozenset[str]:
        """Return every root that at least one registered event type exposes."""
        roots: set[str] = set()
        for descriptor in self:
            roots |= descriptor.exposed_roots
        return frozenset(roots)


DEFAULT_PLATFORM_EVENT_CATALOG = PlatformEventCatalog(
    [
        PlatformEventDescriptor(
            event_type=PlatformEventType.FileUploaded,
            payload_model=FileUploadedPayload,
            exposed_roots=frozenset({"file", "dataset"}),
            default_root="dataset",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.File: _file_id,
                OncePer.Dataset: _dataset_id,
            },
            subject_type=RobotoUriType.File,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.UploadCompleted,
            payload_model=UploadCompletedPayload,
            exposed_roots=frozenset({"dataset", "upload"}),
            default_root="dataset",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Dataset: _dataset_id,
            },
            subject_type=RobotoUriType.Dataset,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.FileIngested,
            payload_model=FileIngestedPayload,
            exposed_roots=frozenset({"file", "dataset"}),
            default_root="dataset",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.File: _file_id,
                OncePer.Dataset: _dataset_id,
            },
            subject_type=RobotoUriType.File,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.FileMetadataUpdated,
            payload_model=FileMetadataUpdatedPayload,
            exposed_roots=frozenset({"file", "dataset", "changed", "tag"}),
            default_root="dataset",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.File: _file_id,
                OncePer.Dataset: _dataset_id,
            },
            subject_type=RobotoUriType.File,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.DatasetMetadataUpdated,
            payload_model=DatasetMetadataUpdatedPayload,
            exposed_roots=frozenset({"dataset", "changed", "tag"}),
            default_root="dataset",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Dataset: _dataset_id,
            },
            subject_type=RobotoUriType.Dataset,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.DatasetCreated,
            payload_model=DatasetCreatedPayload,
            exposed_roots=frozenset({"dataset"}),
            default_root="dataset",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Dataset: _dataset_id,
            },
            subject_type=RobotoUriType.Dataset,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.DatasetTagAdded,
            payload_model=DatasetTagAddedPayload,
            exposed_roots=frozenset({"dataset", "tag"}),
            default_root="dataset",
            # Tags are added to a dataset many times over its life. Once per dataset would
            # fire on the first addition and drop every later one.
            once_per_projections={
                OncePer.Occurrence: _event_id,
            },
            subject_type=RobotoUriType.Dataset,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.InvocationCompleted,
            payload_model=InvocationCompletedPayload,
            exposed_roots=frozenset({"invocation", "action"}),
            default_root="invocation",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Invocation: _invocation_id,
            },
            subject_type=RobotoUriType.Invocation,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.InvocationFailed,
            payload_model=InvocationFailedPayload,
            exposed_roots=frozenset({"invocation", "action"}),
            default_root="invocation",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Invocation: _invocation_id,
            },
            subject_type=RobotoUriType.Invocation,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.SessionIngested,
            payload_model=SessionIngestedPayload,
            exposed_roots=frozenset({"session"}),
            default_root="session",
            # Each time a session's changed files are all ingested again is a new event, with a
            # higher ingestion_number, so a trigger fires again.
            once_per_projections={
                OncePer.Occurrence: _event_id,
            },
            subject_type=RobotoUriType.Session,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.EventCreated,
            payload_model=EventCreatedPayload,
            exposed_roots=frozenset({"event"}),
            default_root="event",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Event: _annotation_event_id,
            },
            subject_type=RobotoUriType.Event,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.SessionEventCreated,
            payload_model=SessionEventCreatedPayload,
            exposed_roots=frozenset({"event", "session"}),
            default_root="event",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Event: _annotation_event_id,
            },
            subject_type=RobotoUriType.Event,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.ScheduleFired,
            payload_model=ScheduleFiredPayload,
            exposed_roots=frozenset({"schedule"}),
            default_root="schedule",
            # Roboto builds the event's ID from the trigger and the scheduled minute, so once
            # per occurrence fires once even when the same minute is delivered twice.
            once_per_projections={
                OncePer.Occurrence: _event_id,
            },
            subject_type=RobotoUriType.Trigger,
            subscribable=False,
        ),
    ]
)
"""Catalog with a descriptor for every :py:class:`~roboto.domain.platform_events.PlatformEventType`.

Roboto uses it to parse each event's payload, and to validate and evaluate triggers wherever no other catalog is given.
"""


def event_catalog_manifest(catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG) -> dict[str, typing.Any]:
    """Build a JSON-serializable summary of ``catalog``, keyed by event type.

    ``event_catalog.json`` in this package holds its output for the default catalog, which the Roboto web app mirrors.

    Args:
        catalog: Catalog to summarize. Defaults to ``DEFAULT_PLATFORM_EVENT_CATALOG``.

    Returns:
        Dictionary that maps each event type to its ``roots``, ``default_root``, supported ``once_per`` values,
        ``subject_type``, and whether a trigger may subscribe to it (``subscribable``).
    """
    return {
        descriptor.event_type.value: {
            "roots": sorted(descriptor.exposed_roots),
            "default_root": descriptor.default_root,
            "once_per": sorted(member.value for member in descriptor.supported_once_per),
            "subject_type": descriptor.subject_type.value,
            "subscribable": descriptor.subscribable,
        }
        for descriptor in catalog
    }


__all__ = [
    "DATASET_ROOT",
    "DEFAULT_PLATFORM_EVENT_CATALOG",
    "ENVELOPE_ROOT",
    "OncePerProjection",
    "PlatformEventCatalog",
    "PlatformEventDescriptor",
    "RESERVED_ROOTS",
    "TRIGGER_ROOT",
    "event_catalog_manifest",
]
