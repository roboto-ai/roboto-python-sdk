# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import re
import typing

from ...collection_utils import get_by_path
from ...query import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionType,
    Field,
)
from ..platform_events import (
    DEFAULT_PLATFORM_EVENT_CATALOG,
    RESERVED_ROOTS,
)
from .namespace import EventNamespace

UNSTRIPPED_ROOTS: frozenset[str] = (DEFAULT_PLATFORM_EVENT_CATALOG.namespace_roots() | RESERVED_ROOTS) - frozenset(
    {"dataset", "file"}
)
"""Roots of trigger condition fields that :py:class:`~roboto.query.Field` keeps in the field's lookup path.

The field parser strips the ``dataset.`` and ``file.`` prefixes, so ``dataset.x`` looks up ``x``, but keeps any other
root, so ``changed.vehicle_id`` is looked up whole. The set holds every root an event type in the default platform event
catalog exposes, plus ``envelope`` and ``trigger``, minus ``dataset`` and ``file``."""


def iter_leaf_conditions(condition: ConditionType) -> collections.abc.Iterator[Condition]:
    """Yield every leaf :py:class:`~roboto.query.Condition` in a condition tree, depth-first.

    Roboto calls this when a trigger is created or updated, to check each leaf of its condition, and when it evaluates
    a trigger's condition against a platform event, including in a dry run. A :py:class:`~roboto.query.ConditionGroup`
    is never yielded itself, whatever its operator; the conditions inside it are.

    Args:
        condition: Condition tree to walk. A single leaf is yielded alone.

    Yields:
        Each leaf condition, in the order it appears in the tree.
    """
    if isinstance(condition, Condition):
        yield condition
    elif isinstance(condition, ConditionGroup):
        for inner in condition.conditions:
            yield from iter_leaf_conditions(inner)


def explicit_root(condition: Condition) -> typing.Optional[str]:
    """Return the root a condition leaf's field names, or ``None`` if the field names no root.

    Roboto calls this when a trigger is created or updated, through
    :py:meth:`~roboto.domain.triggers.TriggerValidator.validate`, to check that the trigger's condition reads only
    roots every subscribed platform event exposes, and when it evaluates a trigger's condition against a platform
    event, to read each leaf from the right record. A field names a root when it starts with ``dataset.``, ``file.``,
    ``topic.`` or ``msgpath.``, which return ``"dataset"``, ``"file"``, ``"topic"`` and ``"message_path"``, or when its
    first segment is in ``UNSTRIPPED_ROOTS``, such as ``changed`` in ``changed.vehicle_id``. A field that names no root
    reads from the subscribed event type's default root.

    Args:
        condition: Condition leaf whose field to read the root of.

    Returns:
        Root the field names, such as ``"dataset"`` or ``"changed"``, or ``None`` when it names none.
    """
    if condition.targets_dataset():
        return "dataset"
    if condition.targets_file():
        return "file"
    if condition.targets_topic():
        return "topic"
    if condition.targets_message_path():
        return "message_path"
    first_segment = condition.field.split(".", 1)[0]
    if first_segment in UNSTRIPPED_ROOTS:
        return first_segment
    return None


class ConditionMatcher:
    """Evaluator of a trigger's condition against one platform event.

    Roboto uses it when a trigger fires, to decide whether the trigger runs its targets; to see how a trigger's
    condition evaluates against an event, use :py:meth:`~roboto.domain.triggers.Trigger.dry_run` instead.

    Each leaf of the condition reads the record of the root its field names, or of ``default_root`` when the field names
    none, and compares the value there with the comparators :py:class:`~roboto.query.Condition` uses in queries. A
    root's record is loaded only when a leaf reads it. A leaf is false, whatever its comparator, when:

    - Its field starts with ``topic.`` or ``msgpath.``. No platform event exposes topics or message paths.
    - The event has no record for its root, such as when the resource was deleted before the condition ran. So the
      :py:class:`~roboto.query.Comparator` members ``NotExists`` and ``IsNull`` do not match a deleted resource, though
      a :py:attr:`~roboto.query.ConditionOperator.Not` group over such a leaf does.

    Under ``Equals``, ``NotEquals`` and the four ordering comparators, two zoned ISO-8601 timestamps compare as instants
    rather than as text, so ``2026-09-16T15:00:00Z`` equals ``2026-09-16T15:00:00+00:00``.

    Args:
        namespace: Namespace of the platform event to evaluate the condition against.
        default_root: Root that a condition field with no root reads from: the subscribed event type's
            :py:attr:`~roboto.domain.platform_events.PlatformEventDescriptor.default_root`.
    """

    def __init__(self, namespace: EventNamespace, default_root: str) -> None:
        self.__namespace = namespace
        self.__default_root = default_root

    def matches(self, condition: typing.Optional[ConditionType]) -> bool:
        """Return whether a condition holds for the event.

        Args:
            condition: Condition tree to evaluate. ``None`` always matches.
        """
        if condition is None:
            return True
        return self.__visit(condition)

    def __visit(self, condition: ConditionType) -> bool:
        if isinstance(condition, Condition):
            return self.__visit_leaf(condition)
        if isinstance(condition, ConditionGroup):
            return bool(condition.matches(lambda inner: self.__visit(inner)))
        raise ValueError(f"Unknown condition type: {type(condition)}")

    def __visit_leaf(self, condition: Condition) -> bool:
        # No platform event exposes a topic or message path, so these leaves are false without asking the namespace
        # for a record.
        if condition.targets_topic() or condition.targets_message_path():
            return False
        root = explicit_root(condition)
        wrap_under_root = root is not None and root in UNSTRIPPED_ROOTS
        if root is None:
            root = self.__default_root
        record = self.__namespace.record(root)
        if record is None:
            return False
        # The field parser strips dataset. and file. from the lookup path but keeps any other root, such as changed.,
        # so nest the record under its root for that first segment to resolve.
        target = {root: dict(record)} if wrap_under_root else dict(record)
        return _as_instants(condition, target).matches(target)


_ISO_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$")
"""Pattern of an ISO-8601 timestamp with a date, a time and a zone, the form a timestamp takes in a record."""

_CHRONOLOGICAL = frozenset(
    {
        Comparator.Equals,
        Comparator.NotEquals,
        Comparator.GreaterThan,
        Comparator.GreaterThanOrEqual,
        Comparator.LessThan,
        Comparator.LessThanOrEqual,
    }
)
"""Comparators under which two timestamps compare as instants rather than as text."""


def _as_instants(condition: Condition, target: dict[str, typing.Any]) -> Condition:
    """Return ``condition`` with its value parsed to a datetime when it and the record's value are both timestamps.

    Records carry timestamps as JSON strings, such as ``file.created``, and a condition's value is a string too. As
    text, ``...Z`` and ``...+00:00`` differ and offsets sort out of order. When the comparator is in
    ``_CHRONOLOGICAL`` and both values match ``_ISO_INSTANT``, the condition's value becomes a datetime, and
    :py:meth:`~roboto.query.Condition.matches` then parses the record's value to compare. Any other comparator, such as
    :py:attr:`~roboto.query.Comparator.BeginsWith` or :py:attr:`~roboto.query.Comparator.Contains`, or any value that
    is not a zoned timestamp, leaves ``condition`` unchanged.
    """
    if condition.comparator not in _CHRONOLOGICAL:
        return condition
    if not isinstance(condition.value, str) or not _ISO_INSTANT.match(condition.value):
        return condition
    actual = get_by_path(target, Field.wrap(condition.field).target.path.split("."))
    if not isinstance(actual, str) or not _ISO_INSTANT.match(actual):
        return condition
    try:
        instant = datetime.datetime.fromisoformat(condition.value.replace("Z", "+00:00"))
    except ValueError:
        return condition
    return condition.model_copy(update={"value": instant})


__all__ = [
    "UNSTRIPPED_ROOTS",
    "ConditionMatcher",
    "explicit_root",
    "iter_leaf_conditions",
]
