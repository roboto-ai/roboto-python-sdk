# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import typing

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")
"""Recognizes ``{{name}}`` placeholders. Names start with a letter or underscore;
dots are allowed so dotted names (``{{dataset.id}}``, ``{{action.name}}``) work as
a namespace convention for entity-bound expansion by a :class:`VariableResolver`.
The engine treats the full dotted string as one opaque key — the resolver decides
what, if anything, it expands to."""

VARIABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
"""Mirrors :data:`PLACEHOLDER_RE` so every declared variable name is referenceable
by ``{{name}}``."""


@typing.runtime_checkable
class VariableResolver(typing.Protocol):
    """Decides what each ``{{name}}`` placeholder expands to during substitution.

    Implementations bind placeholders to a source of values — a flat mapping for
    agent launch, or a lazily-hydrated event namespace for triggers — keeping the
    substitution engine itself agnostic to where values come from.
    """

    def resolve(self, name: str) -> typing.Optional[str]:
        """Return the substitution string for placeholder ``name``, or ``None``.

        Args:
            name: The placeholder name written between ``{{`` and ``}}``, dots
                included (e.g. ``dataset.id``).

        Returns:
            The string to splice in, or ``None`` to leave the literal ``{{name}}``
            in place.
        """
        ...


class MappingResolver:
    """A :class:`VariableResolver` backed by a flat ``name -> value`` mapping.

    Values are coerced to ``str`` on access; a missing key or a ``None`` value
    resolves to ``None`` (leaving the placeholder unexpanded).
    """

    def __init__(self, values: typing.Mapping[str, typing.Any]) -> None:
        self._values = values

    def resolve(self, name: str) -> typing.Optional[str]:
        value = self._values.get(name)
        return None if value is None else str(value)


def collect_placeholders(node: typing.Any) -> set[str]:
    """Return every ``{{name}}`` placeholder found in the string leaves of ``node``.

    ``node`` is the JSON form of a template (nested dicts, lists, scalars). Only
    string *values* are scanned; placeholder syntax in dict keys is rejected so a
    templated key can't silently collapse two entries into one.

    Raises:
        ValueError: A dict key contains ``{{...}}`` placeholder syntax.
    """
    found: set[str] = set()
    _collect(node, found)
    return found


def _collect(node: typing.Any, sink: set[str]) -> None:
    if isinstance(node, str):
        for match in PLACEHOLDER_RE.finditer(node):
            sink.add(match.group(1))
    elif isinstance(node, list):
        for item in node:
            _collect(item, sink)
    elif isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and PLACEHOLDER_RE.search(key):
                raise ValueError(
                    f"Placeholder syntax is not permitted in dict keys: found {key!r}. "
                    "Move the {{...}} placeholder into the value or rename the key."
                )
            _collect(value, sink)


def substitute(node: typing.Any, resolver: VariableResolver) -> typing.Any:
    """Return a copy of ``node`` with each ``{{name}}`` in a string leaf expanded via ``resolver``.

    Embedded and repeated placeholders within one string are supported. A name the
    resolver returns ``None`` for is left as the literal ``{{name}}``; callers that
    require full resolution validate the placeholder set up front with
    :func:`collect_placeholders`.
    """
    if isinstance(node, str):
        return PLACEHOLDER_RE.sub(lambda match: _expand(match, resolver), node)
    if isinstance(node, list):
        return [substitute(item, resolver) for item in node]
    if isinstance(node, dict):
        return {key: substitute(value, resolver) for key, value in node.items()}
    return node


def _expand(match: "re.Match[str]", resolver: VariableResolver) -> str:
    resolved = resolver.resolve(match.group(1))
    return match.group(0) if resolved is None else resolved


__all__ = [
    "MappingResolver",
    "PLACEHOLDER_RE",
    "VARIABLE_NAME_RE",
    "VariableResolver",
    "collect_placeholders",
    "substitute",
]
