# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import shlex
import sys
import typing

from ..compat import StrEnum


class AnsiColor(StrEnum):
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    BLUE = "\033[0;34m"
    END = "\033[0m"


_ANSI_COLOR_CODE = re.compile(r"\x1b\[[0-9;]*m")


# Besides whitespace, the characters that end an unquoted argument, or change it, in cmd.exe or PowerShell.
_WINDOWS_SHELL_SPECIAL_CHARACTERS = frozenset("&|<>^();,'\"`{}$@#")


def quote_for_shell(argument: str) -> str:
    """Quote ``argument`` so that it pastes into a command in the platform's usual shell as one argument, unchanged.

    On Windows, an argument with no whitespace and none of the characters that cmd.exe or PowerShell treat specially is
    left as it is; any other goes in double quotes. Both shells read double-quoted text literally, with these
    exceptions:

    - cmd.exe expands ``%NAME%``.
    - PowerShell expands ``$`` expressions such as ``$name``, and reads a backtick as an escape.
    - A double quote inside ``argument`` ends the quoted text in both shells.

    PowerShell reads a quoted first word of a command as a string rather than a program to run, so a quoted program
    path runs there only after the call operator ``&``, which cmd.exe rejects.

    Elsewhere, the argument is quoted for a POSIX shell.
    """
    if sys.platform != "win32":
        return shlex.quote(argument)
    if argument and not any(c.isspace() or c in _WINDOWS_SHELL_SPECIAL_CHARACTERS for c in argument):
        return argument
    return f'"{argument}"'


def print_list_item(prefix: str, text: str) -> None:
    """Print ``text`` after ``prefix``, with each further line of ``text`` indented to line up under its first.

    Color codes in ``prefix`` take up no columns on screen, so they don't count toward the indent.
    """
    indent = " " * len(_ANSI_COLOR_CODE.sub("", prefix))
    print(prefix + text.replace("\n", "\n" + indent))


def print_error_and_exit(msg: typing.Union[str, list[str]]) -> typing.NoReturn:
    if isinstance(msg, list):
        for line in msg:
            print(f"{AnsiColor.RED}[error]{AnsiColor.END} {line}", file=sys.stderr)
    else:
        print(f"{AnsiColor.RED}[error]{AnsiColor.END} {msg}", file=sys.stderr)
    sys.exit(1)
