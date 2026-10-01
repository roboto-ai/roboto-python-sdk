# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import getpass
import typing
import webbrowser

# What the user may type, in any letter case, at a question whose default is yes. An empty answer takes the default.
YES_ANSWERS = ("", "y", "yes")
NO_ANSWERS = ("n", "no")


@dataclasses.dataclass(frozen=True)
class Prompts:
    """How ``roboto setup`` asks the user at the keyboard for input.

    Setup is given one only when somebody is there to answer. A test supplies its own answers through it.
    """

    ask: collections.abc.Callable[[str], str]
    """Print a question and return the line typed in answer. Raises ``EOFError`` when input ends, as it does when the
    user presses Ctrl-D."""

    ask_hidden: collections.abc.Callable[[str], str]
    """Like ``ask``, without showing what is typed."""

    open_browser: typing.Optional[collections.abc.Callable[[str], bool]]
    """Open a URL in the user's browser and return whether one opened. ``None`` where no browser on this machine would
    be in front of the user: over SSH, or on Linux with no display."""

    @classmethod
    def for_terminal(cls, env: collections.abc.Mapping[str, str], platform: str) -> Prompts:
        """Ask through the terminal the process is attached to.

        Args:
            env: Environment variables, read to tell whether a browser can be opened for the user.
            platform: The value of :py:data:`sys.platform`.
        """
        no_browser = bool(env.get("SSH_CONNECTION") or env.get("SSH_TTY")) or (
            platform.startswith("linux") and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
        )
        return cls(ask=input, ask_hidden=getpass.getpass, open_browser=None if no_browser else _open_browser)


class InputEnded(Exception):
    """The user ended the terminal's input at a question, as Ctrl-D does. Setup stops there, as it does for Ctrl-C,
    and takes no answer as given."""


def answer_to(prompts: Prompts, question: str) -> str:
    """Ask ``question`` and return the answer without surrounding whitespace.

    Raises:
        InputEnded: Input ended before an answer was given.
    """
    try:
        return prompts.ask(question).strip()
    except EOFError:
        raise InputEnded() from None


def hidden_answer_to(prompts: Prompts, question: str) -> str:
    """Like :py:func:`answer_to`, without showing what is typed."""
    try:
        return prompts.ask_hidden(question).strip()
    except EOFError:
        raise InputEnded() from None


def confirm(prompts: Prompts, question: str) -> bool:
    """Ask a yes-or-no ``question`` whose default is yes, and return whether the answer was yes.

    Enter takes the default. Anything other than a form of yes or no is asked again.

    Raises:
        InputEnded: Input ended before an answer was given.
    """
    while True:
        answer = answer_to(prompts, f"{question} [Y/n] ").lower()
        if answer in YES_ANSWERS:
            return True
        if answer in NO_ANSWERS:
            return False


def _open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False
