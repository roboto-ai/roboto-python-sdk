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
"""Namespace roots the query :class:`~roboto.query.Field` parser does not recognize as
resource prefixes, so it leaves them in the lookup path (``changed.vehicle_id`` stays
whole, unlike ``dataset.x`` which strips to ``x``). Derived from the default catalog's
exposed roots."""


def iter_leaf_conditions(condition: ConditionType) -> collections.abc.Iterator[Condition]:
    """Yield every leaf :class:`~roboto.query.Condition` in ``condition``, depth-first."""
    if isinstance(condition, Condition):
        yield condition
    elif isinstance(condition, ConditionGroup):
        for inner in condition.conditions:
            yield from iter_leaf_conditions(inner)


def explicit_root(condition: Condition) -> typing.Optional[str]:
    """Return the namespace root ``condition``'s field explicitly names, or ``None`` if unqualified.

    ``dataset.*``/``file.*``/``topic.*``/``msgpath.*`` prefixes are recognized by the
    query field parser; any other first segment counts as a root only when it is in
    :data:`UNSTRIPPED_ROOTS`. An unqualified field binds to the event's default root.
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
    """Evaluates a trigger condition tree against an event namespace.

    Reuses the query :class:`~roboto.query.Condition` comparators unchanged; only the
    value source differs. Each leaf routes to the namespace root its field targets and
    matches against that root's record, so roots hydrate lazily on first reference. A
    root whose record is missing evaluates to a non-match, so ``NOT_EXISTS`` and
    ``IS_NULL`` never match against an entity that was deleted before evaluation.
    """

    def __init__(self, namespace: EventNamespace, default_root: str) -> None:
        """Bind the matcher to one event namespace.

        Args:
            namespace: The event's variable namespace.
            default_root: Root that unqualified condition fields bind to; the
                subscribed event type's
                :attr:`~roboto.domain.platform_events.PlatformEventDescriptor.default_root`.
        """
        self.__namespace = namespace
        self.__default_root = default_root

    def matches(self, condition: typing.Optional[ConditionType]) -> bool:
        """Return whether ``condition`` holds for the event. A ``None`` condition always matches."""
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
        # No event hydrates topic/message_path roots; such leaves never match rather
        # than falling through to the default root and matching the wrong record.
        if condition.targets_topic() or condition.targets_message_path():
            return False
        root = explicit_root(condition)
        wrap_under_root = root is not None and root in UNSTRIPPED_ROOTS
        if root is None:
            root = self.__default_root
        record = self.__namespace.record(root)
        if record is None:
            return False
        # Condition.matches keeps unknown prefixes (changed./tag./invocation./...) in
        # its lookup path while stripping known ones (dataset./file.), so nest the
        # record one level under its root for the kept segment to resolve.
        target = {root: dict(record)} if wrap_under_root else dict(record)
        return _as_instants(condition, target).matches(target)


_ISO_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$")
"""An ISO-8601 timestamp with a date, a time and a zone: what a JSON-typed record carries."""

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
"""The comparators for which two timestamps mean instants, not text."""


def _as_instants(condition: Condition, target: dict[str, typing.Any]) -> Condition:
    """Return ``condition`` with its value parsed to a datetime when both sides are timestamps.

    Namespace records are JSON-typed, so ``file.created`` arrives as a string, and so
    is a condition's value; as text ``...Z`` and ``...+00:00`` differ and offsets sort
    wrongly. When the comparator is chronological and both the condition's value and
    the record's value are zoned ISO-8601 timestamps, the condition's side becomes a
    datetime and :meth:`Condition.matches` parses the record's side to match. String
    comparators (``BEGINS_WITH``, ``CONTAINS`` and the rest) and any non-timestamp
    value are left alone, so text conditions keep their text semantics.
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
