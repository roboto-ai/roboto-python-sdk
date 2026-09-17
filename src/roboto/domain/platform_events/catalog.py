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
    SessionCreatedPayload,
    SessionFilesAddedPayload,
    SessionUpdatedPayload,
    UploadCompletedPayload,
)
from .once_per import OncePer

OncePerProjection = typing.Callable[[PlatformEvent], str]
"""Projects a :class:`PlatformEvent` onto the token string that identifies what the
trigger fires once per (e.g. the dataset id for ``once_per=dataset``).

A projection reads the event payload and nothing else: one event in, one string out,
with no lookup against platform state. A ``once_per`` value can only name what the
event itself already identifies, so there is no "once per file in the dataset this
event is about". ``once_per`` only collapses repeats; it never fans one event out
into several runs, and a trigger dispatches each of its targets at most once per
event.
"""


ENVELOPE_ROOT = "envelope"
"""Namespace root served from the platform event's own envelope: its id, source, subject,
type, time, and org. Reserved: no event type may expose it as an entity root."""

TRIGGER_ROOT = "trigger"
"""Namespace root describing the trigger being evaluated. Reserved for the consumer; no
event type may expose it as an entity root."""

RESERVED_ROOTS = frozenset({ENVELOPE_ROOT, TRIGGER_ROOT})
"""Roots the evaluation namespace serves itself. A descriptor claiming one would be
silently shadowed by the envelope or the trigger, so construction rejects it."""


def _subject_id(event: PlatformEvent, field: str) -> str:
    """Read one identifier off the event's own payload — a projection's only input.

    Raises:
        ValueError: The payload carries no such identifier, so this ``once_per`` value
            names nothing the event names. Normally unreachable: :class:`PlatformEvent`
            validation binds ``data`` to the payload model registered for ``type``, and
            only ``once_per`` values that model supports are registered in the
            descriptor.
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


def _session_id(event: PlatformEvent) -> str:
    return _subject_id(event, "session_id")


def _annotation_event_id(event: PlatformEvent) -> str:
    return _subject_id(event, "event_id")


SubjectProjection = typing.Callable[[PlatformEvent], RobotoUri]
"""The CloudEvents ``subject``: the entity an event is about, as a ``roboto://`` URI.
A pure function of the payload on the same terms as :data:`OncePerProjection` — it can
only name an entity the event already carries."""


@dataclasses.dataclass(frozen=True)
class PlatformEventDescriptor:
    """Everything the trigger system knows about one platform event type.

    Immutable. Carries the payload model the envelope validates against, the namespace
    roots the event exposes to conditions and target templates, the default root
    unqualified condition fields bind to, the entity the event is about, and the
    :class:`OncePer` values the event supports (as projections from an event to its
    dedup token value).

    Every ``once_per`` value is declared as an :data:`OncePerProjection`, a pure
    function of the event payload, so a descriptor can only offer what the payload
    itself names.
    No descriptor can resolve one event into several subjects, which is what holds
    dispatch at one per target per event.
    """

    event_type: PlatformEventType
    """The event type this descriptor describes."""

    payload_model: type[pydantic.BaseModel]
    """Model of :attr:`PlatformEvent.data` for this event type."""

    exposed_roots: frozenset[str]
    """Namespace roots (``dataset``, ``file``, ``changed``, ...) this event exposes."""

    default_root: str
    """Root that unqualified condition fields bind to. Always one of :attr:`exposed_roots`."""

    once_per_projections: collections.abc.Mapping[OncePer, OncePerProjection]
    """Supported ``once_per`` values, each mapped to the projection that yields its
    token. Key presence defines legality; every event supports :attr:`OncePer.Occurrence`."""

    subject_type: RobotoUriType
    """The kind of entity this event is about — its CloudEvents ``subject``. The payload
    carries that entity's id under ``{subject_type}_id``; everything else in it is
    context around the entity: the upload transaction a file arrived in, the files added
    to a session, the applied changeset."""

    subscribable: bool = True
    """Whether a trigger may name this type in an
    :class:`~roboto.domain.triggers.EventSubscription`. ``False`` for occurrences
    delivered to a single trigger rather than broadcast to subscribers — the schedule
    tick — which still carry a descriptor so their tokens and namespaces are built the
    same way."""

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
        """The :class:`OncePer` values this event type supports."""
        return frozenset(self.once_per_projections)

    def supports_once_per(self, once_per: OncePer) -> bool:
        """Return whether ``once_per`` is legal for this event type."""
        return once_per in self.once_per_projections

    def subject(self, event: PlatformEvent) -> RobotoUri:
        """Return the ``roboto://`` URI of the entity ``event`` is about.

        Raises:
            ValueError: ``event`` is not of this descriptor's event type.
        """
        if event.type is not self.event_type:
            raise ValueError(
                f"Cannot name the subject of a {event.type.value!r} event "
                f"with the {self.event_type.value!r} descriptor."
            )
        return RobotoUri(self.subject_type, _subject_id(event, f"{self.subject_type.value}_id"))

    def idempotency_token(self, event: PlatformEvent, once_per: OncePer) -> str:
        """Return the dedup token for ``event`` at ``once_per``.

        Two events that project onto the same token dispatch the same target of the
        same trigger at most once.

        Args:
            event: The event to project. Must be of this descriptor's type.
            once_per: What the trigger fires once per.

        Raises:
            ValueError: ``event`` is of a different type, or ``once_per`` is not
                supported by this event type.
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
    """Descriptors for platform event types, looked up by type.

    Everything that varies by event type — payload model, exposed roots, default root,
    dedup projections — hangs off the :class:`PlatformEventDescriptor` objects
    registered here. :data:`DEFAULT_PLATFORM_EVENT_CATALOG` registers every member of
    :class:`PlatformEventType`; a caller may build a catalog over a subset.
    """

    def __init__(self, descriptors: collections.abc.Iterable[PlatformEventDescriptor]) -> None:
        """Register ``descriptors``, rejecting duplicates.

        Args:
            descriptors: The descriptors this catalog serves, at most one per event type.

        Raises:
            ValueError: Two descriptors share an event type.
        """
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

        Raises:
            ValueError: No descriptor is registered for ``event_type``.
        """
        descriptor = self.__descriptors.get(event_type)
        if descriptor is None:
            raise ValueError(f"No descriptor registered for event type {event_type.value!r}.")
        return descriptor

    def exposed_roots(self, event_type: PlatformEventType) -> frozenset[str]:
        """Return the namespace roots ``event_type`` exposes.

        Raises:
            ValueError: No descriptor is registered for ``event_type``.
        """
        return self.descriptor(event_type).exposed_roots

    def subscribable_types(self) -> frozenset[PlatformEventType]:
        """Return the event types a trigger may subscribe to."""
        return frozenset(descriptor.event_type for descriptor in self if descriptor.subscribable)

    def namespace_roots(self) -> frozenset[str]:
        """Return the union of every registered event type's exposed roots."""
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
            # Tags are added to a dataset repeatedly over its life; a per-dataset grain
            # would fire on the first addition and swallow every later one.
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
            event_type=PlatformEventType.SessionCreated,
            payload_model=SessionCreatedPayload,
            exposed_roots=frozenset({"session"}),
            default_root="session",
            once_per_projections={
                OncePer.Occurrence: _event_id,
                OncePer.Session: _session_id,
            },
            subject_type=RobotoUriType.Session,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.SessionFilesAdded,
            payload_model=SessionFilesAddedPayload,
            exposed_roots=frozenset({"session"}),
            default_root="session",
            # Files are added to a session repeatedly; a per-session grain would fire
            # once and swallow every later addition.
            once_per_projections={
                OncePer.Occurrence: _event_id,
            },
            subject_type=RobotoUriType.Session,
        ),
        PlatformEventDescriptor(
            event_type=PlatformEventType.SessionUpdated,
            payload_model=SessionUpdatedPayload,
            exposed_roots=frozenset({"session", "changed", "tag"}),
            default_root="session",
            # A session is updated repeatedly; a per-session grain would fire once and
            # swallow every later update.
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
            event_type=PlatformEventType.ScheduleFired,
            payload_model=ScheduleFiredPayload,
            exposed_roots=frozenset({"schedule"}),
            default_root="schedule",
            # The scheduler vends the occurrence id deterministically from (trigger,
            # scheduled minute), so once per occurrence dedupes a re-delivered tick.
            once_per_projections={
                OncePer.Occurrence: _event_id,
            },
            subject_type=RobotoUriType.Trigger,
            subscribable=False,
        ),
    ]
)
"""The catalog of every :class:`PlatformEventType`, used wherever a caller does not
supply its own (envelope payload binding, trigger validation, evaluation)."""


def event_catalog_manifest(catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG) -> dict[str, typing.Any]:
    """The catalog as the web UI's TypeScript mirror reads it: per event type, its roots,
    default root, supported grains, subject type, and whether a trigger may subscribe.

    ``event_catalog.json`` in this package is this function's output, written by
    ``scripts/gen_trigger_manifests.py`` and drift-checked by a test on each side.
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
    "DEFAULT_PLATFORM_EVENT_CATALOG",
    "ENVELOPE_ROOT",
    "OncePerProjection",
    "PlatformEventCatalog",
    "PlatformEventDescriptor",
    "RESERVED_ROOTS",
    "TRIGGER_ROOT",
    "event_catalog_manifest",
]
