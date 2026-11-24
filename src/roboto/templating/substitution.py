# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import typing

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")
"""Regular expression that matches a ``{{name}}`` placeholder and captures its name in group 1.

Whitespace inside the braces is allowed. A name starts with a letter or underscore and continues with letters, digits,
underscores and dots. A dotted name such as ``dataset.id`` is one name: the ``VariableResolver`` decides what it
expands to.
"""

VARIABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
"""Regular expression a template variable's name must match.

It accepts the names ``PLACEHOLDER_RE`` captures, so every declared variable can be written as a ``{{name}}``
placeholder. :py:class:`~roboto.ai.agent.TemplateVariable` checks its ``name`` against it.
"""


@typing.runtime_checkable
class VariableResolver(typing.Protocol):
    """Source of the text ``{{name}}`` placeholders expand to in ``substitute``.

    ``MappingResolver`` reads the text from a dictionary, and
    :py:class:`~roboto.domain.triggers.EventNamespace` reads it from the records of a platform event.
    """

    def resolve(self, name: str) -> typing.Optional[str]:
        """Return the text a placeholder expands to, or ``None`` to leave the placeholder as written.

        Args:
            name: Name written between ``{{`` and ``}}``, dots included and surrounding whitespace removed, such as
                ``dataset.id``.
        """
        ...


class MappingResolver:
    """Variable resolver that reads each placeholder's text from a dictionary keyed by name.

    It converts each value with ``str()``. A name missing from the dictionary, or whose value is ``None``, leaves the
    placeholder as written.

    Args:
        values: Values keyed by placeholder name, dots included, such as ``{"dataset.id": "ds_12345"}``.
    """

    def __init__(self, values: typing.Mapping[str, typing.Any]) -> None:
        self._values = values

    def resolve(self, name: str) -> typing.Optional[str]:
        value = self._values.get(name)
        return None if value is None else str(value)


def collect_placeholders(node: typing.Any) -> set[str]:
    """Return the name of every ``{{name}}`` placeholder in the strings of a JSON-compatible value.

    A placeholder in a dictionary key raises instead of being collected, because expanding two keys to the same text
    would merge their entries.

    Args:
        node: Value to scan: a string, or dictionaries and lists nested to any depth. Values of other types hold no
            placeholders.

    Raises:
        ValueError: A dictionary key contains a ``{{name}}`` placeholder.
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
    """Return a copy of a JSON-compatible value with each ``{{name}}`` placeholder in its strings expanded.

    A string may hold several placeholders, the same one more than once, and other text around them. A placeholder the
    resolver returns ``None`` for stays as written, and dictionary keys are never expanded. Expanded text is not scanned
    again, so a value that itself contains ``{{name}}`` appears as written. To require every placeholder to expand,
    check the names ``collect_placeholders`` returns before calling this.

    Args:
        node: Value to expand: a string, or dictionaries and lists nested to any depth. Values of other types are
            returned unchanged.
        resolver: Resolver that supplies the text each placeholder expands to.

    Examples:
        >>> from roboto.templating import MappingResolver, substitute
        >>> resolver = MappingResolver({"dataset.id": "ds_12345"})
        >>> substitute({"prompt": "Summarize {{dataset.id}} for {{ team }}"}, resolver)
        {'prompt': 'Summarize ds_12345 for {{ team }}'}
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
