# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

from ...experimental import events as experimental_events
from ...updates import MetadataChangeset
from ..platform_events import (
    ENVELOPE_ROOT,
    TRIGGER_ROOT,
    PlatformEvent,
)
from .record import TriggerRecord
from .sources import Schedule

CHANGED_ROOT = "changed"
"""Root of the trigger condition and template fields that read the metadata fields a metadata update set.

The fields are keyed by field name, with their new values.
"""

TAG_ROOT = "tag"
"""Root of the trigger condition and template fields that read the tags a platform event added and removed.

The tags are given as ``{"added": [...], "removed": [...]}``. Both lists are empty for an event that changed no tags.
"""

SCHEDULE_ROOT = "schedule"
"""Root of the trigger condition and template fields that read a schedule firing.

It holds ``scheduled_for``, the minute the firing is for, and ``cron``, the cron expression of the schedule trigger
being evaluated.
"""


def session_event_root(record: experimental_events.EventRecord) -> dict[str, typing.Any]:
    """Build the ``event`` root a trigger reads when an event is created on a session.

    Roboto calls this when a trigger's condition or target templates read the ``event`` root of a
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.SessionEventCreated` platform event.
    :py:func:`~roboto.domain.triggers.platform_event_sample` builds that platform event's sample through it, so most
    code never calls it. The root holds the event's record, plus the names and IDs of the topics the event is about as
    ``topic_names`` and ``topic_ids``. A condition walks only nested mappings, so it cannot read into the record's
    ``topics`` list; the two flat lists let ``event.topic_names CONTAINS "/imu"`` match an event about ``/imu``. Both
    are empty for an event about all of its session's data.

    Args:
        record: Record of the event, a ``roboto.experimental.events.EventRecord``.

    Returns:
        The root, as a dictionary of JSON-compatible values.
    """
    return {
        **record.model_dump(mode="json"),
        "topic_names": [topic.topic_name for topic in record.topics],
        "topic_ids": [topic.topic_id for topic in record.topics],
    }


@typing.runtime_checkable
class NamespaceSource(typing.Protocol):
    """Loader of the entity records a platform event's roots name, such as ``dataset`` and ``file``.

    ``EventNamespace`` calls it the first time a condition or template reads such a root. Roboto supplies one that
    reads Roboto's records, and :py:class:`~roboto.domain.triggers.SampleNamespaceSource` serves sample records.
    """

    def record_for_root(self, root: str, event: PlatformEvent) -> typing.Optional[typing.Mapping[str, typing.Any]]:
        """Load the record of the entity ``root`` names for ``event``, as a mapping of JSON-compatible values.

        Args:
            root: Root to load, such as ``"dataset"``, ``"file"``, ``"invocation"`` or ``"event"``. Never
                ``envelope``, ``trigger``, ``schedule``, ``changed`` or ``tag``, which ``EventNamespace`` reads from
                the event or the trigger itself.
            event: Platform event whose payload identifies the entity.

        Returns:
            The entity's record, or ``None`` when the event type has no such root or the entity was deleted between
            the event and its evaluation.
        """
        ...


class EventNamespace:
    """Namespace of the values a trigger's condition and target templates read for one platform event, by dotted path.

    Roboto builds one for each platform event it evaluates triggers on, and
    :py:func:`~roboto.domain.triggers.platform_event_sample` builds one over sample records. A path such as
    ``dataset.metadata.vehicle_id`` starts with a root, which names a record, and continues through that record's
    nested mappings. A condition reads whole records with ``record``, and a template reads single paths with
    ``resolve``, which makes the namespace a :py:class:`~roboto.templating.VariableResolver`. The roots:

    - ``envelope``: the event's own fields, with its payload under ``data``.
    - ``changed``: the metadata fields a metadata update set, with their new values. Empty for other events.
    - ``tag``: ``{"added": [...], "removed": [...]}``, the tags the event added and removed.
    - ``schedule``: on a schedule firing, ``scheduled_for``, plus ``cron`` on a namespace bound to a schedule trigger.
      ``None`` on other events.
    - ``trigger``: the trigger being evaluated, on a namespace from ``bound_to``, and ``None`` otherwise.
    - Any other root, such as ``dataset`` or ``file``: the entity's record, fetched from ``source`` the first time it
      is read and kept for the namespace's lifetime, including a ``None`` result.

    The payload is fixed when the event is published, while an entity root reads the entity as it stands when the
    trigger evaluates the event. On a :py:attr:`~roboto.domain.platform_events.PlatformEventType.FileUploaded` platform
    event, ``envelope.data.file_version`` (:py:attr:`~roboto.domain.platform_events.FileUploadedPayload.file_version`)
    is the version that fired the trigger and ``file.version`` is the file's version when the condition runs.

    Payload values are rendered as JSON, so a timestamp under ``envelope.data`` is an ISO-8601 string, while
    ``envelope.time`` and ``schedule.scheduled_for`` are ``datetime.datetime`` objects. A condition compares
    either form as an instant. A template substitutes each in its own form: ``2026-08-27T09:00:00Z`` for the string,
    ``2026-08-27 09:00:00+00:00`` for the datetime.

    Args:
        event: Platform event whose values the namespace serves.
        source: Loader of the entity roots' records. The namespace calls it at most once per root.
        trigger: Trigger being evaluated, which the ``trigger`` root reads. ``None`` leaves that root ``None``. Prefer
            ``bound_to``, which shares the fetched records with the namespace it is called on.
    """

    def __init__(
        self,
        event: PlatformEvent,
        source: NamespaceSource,
        *,
        trigger: typing.Optional[TriggerRecord] = None,
        _records: typing.Optional[dict[str, typing.Optional[typing.Mapping[str, typing.Any]]]] = None,
    ) -> None:
        self.__event = event
        self.__source = source
        self.__trigger = trigger
        self.__records: dict[str, typing.Optional[typing.Mapping[str, typing.Any]]] = (
            _records if _records is not None else {}
        )

    def bound_to(self, trigger: TriggerRecord) -> "EventNamespace":
        """Return a namespace for the same event in which the ``trigger`` root reads ``trigger``.

        The returned namespace shares this one's fetched records: reading ``dataset.name`` through both fetches the
        dataset once. Binding every trigger subscribed to an event from one namespace fetches each entity once.

        Args:
            trigger: Trigger whose condition and targets are being evaluated.
        """
        return EventNamespace(self.__event, self.__source, trigger=trigger, _records=self.__records)

    def record(self, root: str) -> typing.Optional[typing.Mapping[str, typing.Any]]:
        """Return the record ``root`` names, fetching an entity's record from the source at most once.

        Args:
            root: Root to read, such as ``"envelope"``, ``"changed"`` or ``"dataset"``. The class docstring lists what
                each root holds.

        Returns:
            The record, or ``None`` when the root does not resolve: the source has no record for it, a ``schedule``
            root on an event that is not a schedule firing, or a ``trigger`` root on a namespace not from ``bound_to``.
        """
        if root == ENVELOPE_ROOT:
            if ENVELOPE_ROOT not in self.__records:
                self.__records[ENVELOPE_ROOT] = self.__envelope_record()
            return self.__records[ENVELOPE_ROOT]
        if root == TRIGGER_ROOT:
            return _trigger_record(self.__trigger) if self.__trigger is not None else None
        if root == CHANGED_ROOT:
            # A put_fields key that contains a dot, such as "vehicle.id", stays one literal key, so
            # get("changed.vehicle.id") walks "vehicle" and then "id" and does not find it.
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
        """Return the value at a dotted path such as ``dataset.metadata.vehicle_id``, or ``None`` if it is missing.

        Args:
            path: Root, optionally followed by keys of nested mappings, joined by dots. A root alone returns its whole
                record.
        """
        root, _, subpath = path.partition(".")
        record = self.record(root)
        if record is None:
            return None
        if not subpath:
            return record
        return _walk_path(record, subpath)

    def resolve(self, name: str) -> typing.Optional[str]:
        """Return the value at dotted path ``name`` as a string, for a ``{{name}}`` template placeholder.

        Returns:
            ``str()`` of the value, or ``None`` if the path does not resolve.
        """
        value = self.get(name)
        return None if value is None else str(value)

    def __envelope_record(self) -> typing.Mapping[str, typing.Any]:
        return {
            "id": self.__event.id,
            "source": self.__event.source,
            "subject": self.__event.subject,
            "type": self.__event.type.value,
            "time": self.__event.time,
            "org_id": self.__event.org_id,
            "data": self.__event.data.model_dump(mode="json"),
        }

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
    """Build the ``trigger`` root: the trigger's identifying and lifecycle fields.

    It leaves out the condition, which has already decided the evaluation, and the targets, which a target's own
    template would be naming itself in. ``fires_on`` is given in its JSON form, as the entity roots are.
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
    "session_event_root",
]
