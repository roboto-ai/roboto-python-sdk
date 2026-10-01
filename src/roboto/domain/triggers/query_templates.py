# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...templating import PLACEHOLDER_RE

QUERY_FIELD = "query"
"""Selector field holding a RoboQL query, the one field of an invocation input whose value
is an expression rather than a value the expression compares against."""

_UNESCAPABLE = frozenset({"\r", "\n"})
"""Characters a RoboQL string literal has no spelling for, escaped or otherwise."""


class QueryPlaceholder(typing.NamedTuple):
    """One ``{{placeholder}}`` found in a RoboQL query, and the literal enclosing it."""

    name: str
    """The placeholder's dotted name, without the braces."""

    quote: typing.Optional[str] = None
    """The quote character of the string literal the placeholder sits in, or ``None`` when it
    sits in expression text (a comment counts as expression text: a value could close it)."""

    start: int = 0
    """Index of the placeholder's first character in the query."""

    end: int = 0
    """Index one past the placeholder's last character."""


def scan_placeholders(query: str) -> list[QueryPlaceholder]:
    """Return every ``{{placeholder}}`` in ``query``, each with the literal enclosing it.

    Follows the lexical rules of the RoboQL grammar: both quote characters open a string
    literal, a backslash inside one escapes the next character, and ``//`` and slash-star
    comments run to their terminator.

    Args:
        query: A RoboQL query, possibly carrying ``{{placeholder}}`` templates.
    """
    placeholders = [
        QueryPlaceholder(name=match.group(1), start=match.start(), end=match.end())
        for match in PLACEHOLDER_RE.finditer(query)
    ]
    if not placeholders:
        return []

    # The quote enclosing each character, filled by one pass over the query, so a
    # placeholder's enclosure is a lookup at its first character.
    enclosing: list[typing.Optional[str]] = [None] * len(query)
    position = 0
    quote: typing.Optional[str] = None
    while position < len(query):
        character = query[position]
        if quote is not None:
            enclosing[position] = quote
            if character == "\\":
                if position + 1 < len(query):
                    enclosing[position + 1] = quote
                position += 2
                continue
            if character == quote:
                quote = None
            position += 1
            continue
        if character in ("'", '"'):
            quote = character
            position += 1
            continue
        if query.startswith("//", position):
            end_of_line = query.find("\n", position)
            position = len(query) if end_of_line == -1 else end_of_line
            continue
        if query.startswith("/*", position):
            end_of_comment = query.find("*/", position + 2)
            position = len(query) if end_of_comment == -1 else end_of_comment + 2
            continue
        position += 1

    return [placeholder._replace(quote=enclosing[placeholder.start]) for placeholder in placeholders]


def placeholders_outside_string_literals(query: str) -> list[str]:
    """Return the placeholders in ``query`` that do not sit inside a string literal.

    A value spliced inside a literal can be escaped into it (see :func:`escape_string_literal`),
    so it can only ever be data. A value spliced anywhere else becomes query syntax: a tag or
    path carrying an operator would rewrite the query it was meant to be compared against.

    Args:
        query: A RoboQL query, possibly carrying ``{{placeholder}}`` templates.

    Returns:
        The names of those placeholders, in the order they appear.
    """
    return [placeholder.name for placeholder in scan_placeholders(query) if placeholder.quote is None]


def escape_string_literal(value: str, quote: str) -> str:
    """Return ``value`` escaped for splicing inside a ``quote``-delimited RoboQL string literal.

    Args:
        value: The value to splice.
        quote: The literal's delimiter, ``"`` or ``'``.

    Raises:
        ValueError: ``value`` holds a character the literal cannot carry under any escape,
            namely a carriage return or a newline.
    """
    unescapable = sorted(_UNESCAPABLE & set(value))
    if unescapable:
        raise ValueError(
            f"A RoboQL string literal cannot carry {', '.join(repr(character) for character in unescapable)}, "
            f"so {value!r} cannot be spliced into one."
        )
    return value.replace("\\", "\\\\").replace(quote, f"\\{quote}")


def substitute_query_template(query: str, resolve: collections.abc.Callable[[str], str]) -> str:
    """Return ``query`` with each placeholder replaced by ``resolve``'s value for it, escaped in place.

    Each placeholder is substituted exactly once, and a value is escaped for the literal that
    encloses it, so a value that itself looks like a template or carries a quote stays data.

    Args:
        query: A RoboQL query carrying ``{{placeholder}}`` templates.
        resolve: Returns the value for a placeholder name.

    Raises:
        ValueError: A placeholder sits outside a string literal, or a value cannot be escaped
            into the literal it lands in.
    """
    rendered: list[str] = []
    consumed = 0
    for placeholder in scan_placeholders(query):
        if placeholder.quote is None:
            raise ValueError(
                f"Placeholder {{{{{placeholder.name}}}}} sits outside a quoted value in the query {query!r}, "
                "where its value would be read as query syntax."
            )
        rendered.append(query[consumed : placeholder.start])
        rendered.append(escape_string_literal(resolve(placeholder.name), placeholder.quote))
        consumed = placeholder.end
    rendered.append(query[consumed:])
    return "".join(rendered)


def map_query_templates(
    invocation_input: collections.abc.Mapping[str, typing.Any],
    transform: collections.abc.Callable[[str], str],
) -> dict[str, typing.Any]:
    """Return ``invocation_input`` with ``transform`` applied to every RoboQL query it holds.

    Args:
        invocation_input: An :class:`~roboto.domain.actions.InvocationInput` in its JSON form,
            whose top-level values are selectors or lists of them.
        transform: Called with each selector's query; its result replaces that query.

    Returns:
        A copy, shallow below the selectors it rewrites.
    """
    mapped: dict[str, typing.Any] = {}
    for field, selectors in invocation_input.items():
        if isinstance(selectors, list):
            mapped[field] = [_map_selector(selector, transform) for selector in selectors]
        else:
            mapped[field] = _map_selector(selectors, transform)
    return mapped


def iter_query_templates(
    invocation_input: collections.abc.Mapping[str, typing.Any],
) -> collections.abc.Iterator[str]:
    """Yield every RoboQL query in ``invocation_input``, in document order."""
    for selectors in invocation_input.values():
        for selector in selectors if isinstance(selectors, list) else [selectors]:
            if isinstance(selector, collections.abc.Mapping):
                query = selector.get(QUERY_FIELD)
                if isinstance(query, str):
                    yield query


def _map_selector(selector: typing.Any, transform: collections.abc.Callable[[str], str]) -> typing.Any:
    if not isinstance(selector, collections.abc.Mapping):
        return selector
    query = selector.get(QUERY_FIELD)
    if not isinstance(query, str):
        return dict(selector)
    return {**selector, QUERY_FIELD: transform(query)}


__all__ = [
    "QUERY_FIELD",
    "QueryPlaceholder",
    "escape_string_literal",
    "iter_query_templates",
    "map_query_templates",
    "placeholders_outside_string_literals",
    "scan_placeholders",
    "substitute_query_template",
]
