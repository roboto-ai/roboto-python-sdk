# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...templating import PLACEHOLDER_RE

QUERY_FIELD = "query"
"""Name of the selector field that holds a RoboQL query.

It is the one field of an invocation input whose text is read as query syntax rather than taken as a value.
"""

_UNESCAPABLE = frozenset({"\r", "\n"})
"""Characters a RoboQL string literal cannot contain, escaped or not."""


class QueryPlaceholder(typing.NamedTuple):
    """One ``{{<name>}}`` placeholder found in a RoboQL query, with the string literal that encloses it.

    ``scan_placeholders`` returns one for each placeholder it finds.
    """

    name: str
    """Dotted name of the placeholder, without the braces, such as ``file.relative_path``."""

    quote: typing.Optional[str] = None
    """Quote character of the string literal the placeholder sits in, or ``None`` when it sits outside every literal.

    A placeholder inside a comment counts as outside, because a substituted value could close the comment.
    """

    start: int = 0
    """Index of the placeholder's first character in the query."""

    end: int = 0
    """Index one past the placeholder's last character in the query."""


def scan_placeholders(query: str) -> list[QueryPlaceholder]:
    """Return every ``{{<name>}}`` placeholder in a RoboQL query, with the string literal enclosing each.

    Roboto calls this when a trigger is saved, through ``placeholders_outside_string_literals``, and when the trigger
    invokes an action, through ``substitute_query_template``. It scans by the RoboQL lexer's rules:

    - A single or double quote opens a string literal, which the same quote closes.
    - A backslash inside a literal escapes the character after it.
    - A ``//`` comment runs to the end of its line, and a ``/*`` comment runs to the next ``*/``.

    Args:
        query: RoboQL query that may contain ``{{<name>}}`` placeholders.

    Returns:
        Placeholders, in the order they appear in ``query``.
    """
    placeholders = [
        QueryPlaceholder(name=match.group(1), start=match.start(), end=match.end())
        for match in PLACEHOLDER_RE.finditer(query)
    ]
    if not placeholders:
        return []

    # Record the quote enclosing every character in one pass, so each placeholder's quote is read at its start index.
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
        # Characters in a comment keep None, so a placeholder in one counts as outside any literal.
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
    """Return the names of the placeholders in a RoboQL query that sit outside every string literal.

    Roboto calls this when a trigger is saved, through :py:meth:`~roboto.domain.triggers.TriggerValidator.validate`,
    on each query in an action target's ``invocation_input``, and rejects the trigger if any placeholder is returned.
    A value substituted inside a literal is escaped for it, by ``escape_string_literal``, so it stays data. A value
    substituted anywhere else, a comment included, becomes query syntax: a tag or path containing an operator would
    change the query it was meant to be compared in.

    Args:
        query: RoboQL query that may contain ``{{<name>}}`` placeholders.

    Returns:
        Names of those placeholders, in the order they appear in ``query``.
    """
    return [placeholder.name for placeholder in scan_placeholders(query) if placeholder.quote is None]


def escape_string_literal(value: str, quote: str) -> str:
    """Return ``value`` escaped for use inside a RoboQL string literal delimited by ``quote``.

    Roboto calls this when a trigger invokes an action, through ``substitute_query_template``, on each value it
    substitutes. It puts a backslash before each backslash and each ``quote`` character; the other quote character
    needs no escape.

    Args:
        value: Text to place inside the literal.
        quote: Quote character that delimits the literal, ``"`` or ``'``.

    Raises:
        ValueError: ``value`` contains a carriage return or a newline, which a RoboQL string literal cannot contain
            under any escape.
    """
    unescapable = sorted(_UNESCAPABLE & set(value))
    if unescapable:
        raise ValueError(
            f"A RoboQL string literal cannot carry {', '.join(repr(character) for character in unescapable)}, "
            f"so {value!r} cannot be spliced into one."
        )
    return value.replace("\\", "\\\\").replace(quote, f"\\{quote}")


def substitute_query_template(query: str, resolve: collections.abc.Callable[[str], str]) -> str:
    """Return a RoboQL query with each placeholder replaced by its value, escaped for the string literal it sits in.

    Roboto calls this when a trigger invokes an action, on each query in the target's ``invocation_input``. The query
    is substituted in one pass, so a value that itself contains ``{{<name>}}`` or a quote stays data and is never
    substituted again.

    Args:
        query: RoboQL query that contains ``{{<name>}}`` placeholders.
        resolve: Called with each placeholder's dotted name; returns the value to substitute. An exception it raises
            propagates.

    Raises:
        ValueError: A placeholder sits outside every string literal, or a value contains a carriage return or a
            newline, which no RoboQL string literal can contain.
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
    """Return a copy of an invocation input with ``transform`` applied to each selector's RoboQL query.

    Roboto calls this when a trigger invokes an action, to replace each query in the target's ``invocation_input``
    with its substituted form. ``transform`` is called once per query, in the order ``iter_query_templates`` yields
    them.

    Args:
        invocation_input: :py:class:`~roboto.domain.actions.InvocationInput` as a JSON-compatible dictionary, from
            ``model_dump(mode="json")``, whose top-level values are selectors or lists of selectors.
        transform: Called with each selector's query; its return value replaces the query.

    Returns:
        A new dictionary with new lists and selector dictionaries. Values nested inside a selector are shared with
        ``invocation_input``.
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
    """Yield the RoboQL query of each selector in an invocation input, in the order the selectors appear.

    Roboto calls this when a trigger is saved, to check each query, and when the trigger invokes an action, to
    substitute each query. Selectors without a query are skipped.

    Args:
        invocation_input: :py:class:`~roboto.domain.actions.InvocationInput` as a JSON-compatible dictionary, from
            ``model_dump(mode="json")``, whose top-level values are selectors or lists of selectors.
    """
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
