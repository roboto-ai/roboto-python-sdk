# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


def as_roboql_string_literal(value: str) -> str:
    r"""Render ``value`` as a double-quoted RoboQL string literal.

    A double-quoted RoboQL literal has exactly two escape sequences, ``\"`` and ``\\``. It has no ``\n``, ``\t``, or
    ``\uXXXX`` form, so every other character is emitted verbatim, non-ASCII included. ``json.dumps`` cannot stand in
    for this function: by default it renders non-ASCII characters as ``\uXXXX``, which RoboQL rejects.

    A double-quoted literal cannot hold a codepoint from U+0000 through U+001F, such as a tab or a newline. This
    function emits those characters unchanged rather than escaping or stripping them, so a value containing one yields
    a query that fails to parse.

    Args:
        value: Unquoted string to embed in a query, such as a session, topic, or file name.

    Returns:
        ``value`` wrapped in double quotes, with backslashes and double quotes escaped.

    Examples:
        Escape a double quote:

        >>> as_roboql_string_literal('a"b')
        '"a\\"b"'

        Keep a non-ASCII character as it is:

        >>> as_roboql_string_literal("café")
        '"café"'
    """
    # Escape backslashes first. The other order would double the backslash that quote-escaping just
    # inserted, leaving the quote unescaped and ending the literal early.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
