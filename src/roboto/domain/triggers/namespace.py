# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

from ...updates import MetadataChangeset
from ..platform_events import (
    ENVELOPE_ROOT,
    TRIGGER_ROOT,
    PlatformEvent,
)
from .record import TriggerRecord
from .sources import Schedule

# The ``trigger`` root is served only by a namespace bound to a trigger (see
# EventNamespace.bound_to); an unbound namespace resolves it to nothing, the same as
# any root the event does not expose. Both reserved roots are declared beside the
# catalog so no event type can claim them.

CHANGED_ROOT = "changed"
"""Delta root: the metadata fields an update event put, keyed by field name."""

TAG_ROOT = "tag"
"""Delta root: the tags an event added and removed."""

SCHEDULE_ROOT = "schedule"
"""Occurrence root for schedule firings: the scheduled minute, plus the bound trigger's
cron expression. Served from the occurrence itself and never touches the source."""


@typing.runtime_checkable
class NamespaceSource(typing.Protocol):
    """Lazily hydrates entity-backed namespace roots for an event."""

    def record_for_root(self, root: str, event: PlatformEvent) -> typing.Optional[typing.Mapping[str, typing.Any]]:
        """Load the entity for namespace ``root`` as a JSON-able mapping.

        Args:
            root: The namespace root to hydrate (``"dataset"``, ``"file"``,
                ``"invocation"``, ``"event"``, ...). Never a delta or reserved root:
                the namespace serves ``envelope``, ``trigger``, ``schedule``,
                ``changed`` and ``tag`` itself.
            event: The event whose subject identifies the entity to load.

        Returns:
            The entity as a mapping, or ``None`` when ``event`` cannot resolve it
            (no such root for this event type, or the entity was deleted between
            emit and evaluation).
        """
        ...


class EventNamespace:
    """Resolves dotted variable paths against a platform event.

    The one namespace with three consumers: condition evaluation (whole records via
    :meth:`record`), target template substitution (single paths via :meth:`resolve`,
    satisfying the :class:`~roboto.templating.VariableResolver` protocol), and
    idempotency projections. Entity-backed roots hydrate through the
    :class:`NamespaceSource` at most once each and are cached for the namespace's
    lifetime — including ``None`` results. The ``envelope``, ``changed``, and ``tag``
    roots are served from the event itself and never touch the source; ``trigger``
    is served from the bound trigger (see :meth:`bound_to`) and is otherwise absent.
    """

    def __init__(
        self,
        event: PlatformEvent,
        source: NamespaceSource,
        *,
        trigger: typing.Optional[TriggerRecord] = None,
        _records: typing.Optional[dict[str, typing.Optional[typing.Mapping[str, typing.Any]]]] = None,
    ) -> None:
        """Bind the namespace to one event and one hydration source.

        Args:
            event: The event whose entities and deltas this namespace serves.
            source: Loader for entity-backed roots; consulted lazily, once per root.
            trigger: The trigger this namespace is evaluated for, when known; makes
                the ``trigger`` root resolvable. Prefer :meth:`bound_to` over passing
                it here, so the hydration cache is shared with the unbound namespace.
            _records: Hydration cache to share; :meth:`bound_to` passes its own so a
                bound view never re-fetches what the event-wide namespace already has.
        """
        self.__event = event
        self.__source = source
        self.__trigger = trigger
        self.__records: dict[str, typing.Optional[typing.Mapping[str, typing.Any]]] = (
            _records if _records is not None else {}
        )

    def bound_to(self, trigger: TriggerRecord) -> "EventNamespace":
        """A view of this namespace for one trigger, in which ``trigger.*`` resolves.

        One namespace is shared across every trigger evaluated for an event so each
        entity hydrates once; the trigger being evaluated is per-trigger state, so it
        lives on a view rather than on the shared object. The view delegates every
        other root to the same hydration cache -- reading ``dataset.name`` through it
        and through the parent costs one fetch in total.

        Args:
            trigger: The trigger whose templates and condition are being evaluated.
        """
        return EventNamespace(self.__event, self.__source, trigger=trigger, _records=self.__records)

    def record(self, root: str) -> typing.Optional[typing.Mapping[str, typing.Any]]:
        """Return the whole record for namespace ``root``, hydrating it at most once.

        Args:
            root: Namespace root to fetch. ``envelope`` yields the envelope fields;
                ``changed`` yields the changeset's put fields; ``tag`` yields
                ``{"added": [...], "removed": [...]}``; any other root delegates to
                the cached :class:`NamespaceSource`.

        Returns:
            The record as a mapping, or ``None`` when the source cannot resolve the root.
        """
        if root == ENVELOPE_ROOT:
            return {
                "id": self.__event.id,
                "source": self.__event.source,
                "subject": self.__event.subject,
                "type": self.__event.type.value,
                "time": self.__event.time,
                "org_id": self.__event.org_id,
            }
        if root == TRIGGER_ROOT:
            return _trigger_record(self.__trigger) if self.__trigger is not None else None
        if root == CHANGED_ROOT:
            # put_fields is keyed by top-level field name, so a flattened dotted key
            # (e.g. "metadata.vehicle_id") stays one literal key here and won't resolve
            # through the dotted-path walk in get().
            changeset = self.__changeset()
            return dict(changeset.put_fields or {}) if changeset is not None else {}
        if root == TAG_ROOT:
            return self.__tag_record()
        if root == SCHEDULE_ROOT:
            return self.__schedule_record()
        if root not in self.__records:
            self.__records[root] = self.__source.record_for_root(root, self.__event)
        return self.__records[root]

    def get(self, path: str) -> typing.Any:
        """Return the value at dotted ``path`` (e.g. ``dataset.metadata.vehicle_id``), or ``None``.

        The first path segment names the root; the rest walk nested mappings. Any
        missing segment yields ``None``.
        """
        root, _, subpath = path.partition(".")
        record = self.record(root)
        if record is None:
            return None
        if not subpath:
            return record
        return _walk_path(record, subpath)

    def resolve(self, name: str) -> typing.Optional[str]:
        """Return the string form of the value at ``name`` for template substitution, or ``None``."""
        value = self.get(name)
        return None if value is None else str(value)

    def __schedule_record(self) -> typing.Optional[typing.Mapping[str, typing.Any]]:
        scheduled_for = getattr(self.__event.data, "scheduled_for", None)
        if scheduled_for is None:
            return None
        record: dict[str, typing.Any] = {"scheduled_for": scheduled_for}
        if self.__trigger is not None and isinstance(self.__trigger.fires_on, Schedule):
            record["cron"] = self.__trigger.fires_on.cron
        return record

    def __changeset(self) -> typing.Optional[MetadataChangeset]:
        return getattr(self.__event.data, "changeset", None)

    def __tag_record(self) -> typing.Mapping[str, typing.Any]:
        tags_added = getattr(self.__event.data, "tags_added", None)
        if tags_added is not None:
            return {"added": list(tags_added), "removed": []}
        changeset = self.__changeset()
        if changeset is None:
            return {"added": [], "removed": []}
        return {
            "added": list(changeset.put_tags or []),
            "removed": list(changeset.remove_tags or []),
        }


def _trigger_record(trigger: TriggerRecord) -> typing.Mapping[str, typing.Any]:
    """What a template may say about the trigger itself.

    The identifying and lifecycle fields only: neither the condition, which has already
    decided this evaluation, nor the targets, which a target's own template would be
    naming itself in. Enum-valued fields are given as their values, matching how the
    entity roots read.
    """
    return {
        "trigger_id": trigger.trigger_id,
        "name": trigger.name,
        "org_id": trigger.org_id,
        "enabled": trigger.enabled,
        "fires_on": trigger.fires_on.model_dump(mode="json"),
        "engine": trigger.engine,
        "created": trigger.created,
        "created_by": trigger.created_by,
        "modified": trigger.modified,
        "modified_by": trigger.modified_by,
    }


def _walk_path(record: typing.Mapping[str, typing.Any], subpath: str) -> typing.Any:
    current: typing.Any = record
    for part in subpath.split("."):
        if isinstance(current, typing.Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


__all__ = [
    "CHANGED_ROOT",
    "ENVELOPE_ROOT",
    "TAG_ROOT",
    "TRIGGER_ROOT",
    "EventNamespace",
    "NamespaceSource",
]
