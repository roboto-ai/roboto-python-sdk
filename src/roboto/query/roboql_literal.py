# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


def as_roboql_string_literal(value: str) -> str:
    r"""Render ``value`` as a double-quoted RoboQL string literal.

    RoboQL's grammar admits exactly two escape sequences inside a double-quoted literal, ``\"`` and
    ``\\``. There is no ``\n``, ``\t``, or ``\uXXXX`` form, so every other character is emitted
    verbatim, non-ASCII included. ``json.dumps`` is therefore not a substitute: it defaults to
    ``ensure_ascii=True``, which renders non-ASCII characters as ``\uXXXX``, a form RoboQL rejects.

    No codepoint from U+0000 through U+001F, such as a tab or a newline, can be carried by a
    double-quoted literal. Those characters are emitted unchanged rather than escaped or stripped,
    so a value containing one yields a query that fails to parse.

    Args:
        value: Unquoted string to embed in a query, such as a session, topic, or file name.

    Returns:
        ``value`` wrapped in double quotes, with backslashes and double quotes escaped.

    Examples:
        >>> as_roboql_string_literal('a"b')
        '"a\\"b"'
        >>> as_roboql_string_literal("café")
        '"café"'
    """
    # Escape backslashes first. The other order would double the backslash that quote-escaping just
    # inserted, leaving the quote unescaped and ending the literal early.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
