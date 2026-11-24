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

from ..auth.login_flow import browser_cannot_reach_loopback, open_in_browser

YES_ANSWERS = ("", "y", "yes")
"""Answers that mean yes, in any letter case, at a question whose default is yes, so an empty answer counts as yes."""

NO_ANSWERS = ("n", "no")
"""Answers that mean no, in any letter case."""


@dataclasses.dataclass(frozen=True)
class Prompts:
    """Functions through which ``roboto setup`` asks the user at the keyboard for input.

    Setup gets one only when its input is a terminal and ``--no-input`` was not given. Tests build one that returns
    their own answers.
    """

    ask: collections.abc.Callable[[str], str]
    """Function that prints a question and returns the line typed in answer.

    It raises ``EOFError`` when input ends, as it does when the user presses Ctrl-D.
    """

    ask_hidden: collections.abc.Callable[[str], str]
    """Function like ``ask`` that does not show what is typed."""

    open_browser: typing.Optional[collections.abc.Callable[[str], bool]]
    """Function that opens a URL in the user's browser and returns whether one opened.

    ``None`` where no browser on this machine would be in front of the user: over SSH, or on Linux with no display.
    """

    @classmethod
    def for_terminal(cls, env: collections.abc.Mapping[str, str], platform: str) -> Prompts:
        """Build prompts that ask through the terminal the process is attached to.

        Args:
            env: Environment variables, read to tell whether a browser can be opened for the user.
            platform: Value of ``sys.platform``.
        """
        no_browser = browser_cannot_reach_loopback(env, platform)
        return cls(ask=input, ask_hidden=getpass.getpass, open_browser=None if no_browser else open_in_browser)


class InputEnded(Exception):
    """The user ended the terminal's input at a question, as Ctrl-D does.

    ``answer_to``, ``hidden_answer_to``, ``confirm`` and setup's question for an endpoint raise it. Setup stops there,
    as it does for Ctrl-C, rather than taking the ended input as an empty answer.
    """


def answer_to(prompts: Prompts, question: str) -> str:
    """Ask ``question`` and return the answer without surrounding whitespace.

    Args:
        question: Question to print, including any trailing space before the answer.

    Raises:
        InputEnded: Input ended before an answer was given.
    """
    try:
        return prompts.ask(question).strip()
    except EOFError:
        raise InputEnded() from None


def hidden_answer_to(prompts: Prompts, question: str) -> str:
    """Ask ``question`` without showing what is typed, and return the answer without surrounding whitespace.

    Args:
        question: Question to print, including any trailing space before the answer.

    Raises:
        InputEnded: Input ended before an answer was given.
    """
    try:
        return prompts.ask_hidden(question).strip()
    except EOFError:
        raise InputEnded() from None


def confirm(prompts: Prompts, question: str) -> bool:
    """Ask a yes-or-no ``question`` whose default is yes, and return whether the answer was yes.

    Enter takes the default. Anything other than a form of yes or no is asked again.

    Args:
        question: Question to print. ``" [Y/n] "`` is appended to it.

    Raises:
        InputEnded: Input ended before an answer was given.
    """
    while True:
        answer = answer_to(prompts, f"{question} [Y/n] ").lower()
        if answer in YES_ANSWERS:
            return True
        if answer in NO_ANSWERS:
            return False
