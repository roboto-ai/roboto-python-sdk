# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import builtins
import collections.abc
import time
import typing

Condition = typing.Callable[..., bool]
Interval = typing.Union[int, typing.Callable[[int], int]]
"""Time to sleep between ``wait_for``'s calls of its condition, in the form its ``interval`` argument describes."""


class TimeoutError(builtins.TimeoutError):
    """A wait gave up before its condition was met.

    ``wait_for`` raises it, and so do the SDK methods that wait through it: the ``find_*`` methods of
    :py:class:`~roboto.roboto_search.RobotoSearch`, the ``submit_*_and_await_results`` methods of
    :py:class:`~roboto.query.QueryClient`, :py:meth:`~roboto.domain.actions.Invocation.wait_for_terminal_status`,
    :py:meth:`~roboto.domain.actions.Trigger.wait_for_evaluations_to_complete`,
    :py:meth:`~roboto.domain.custom_fields.CustomField.wait_to_be_ready` and
    :py:meth:`~roboto.domain.custom_fields.CustomField.wait_to_be_deleted`.

    Subclasses the built-in ``TimeoutError``, so ``except TimeoutError`` catches it whether or not the caller
    imported this class.
    """

    msg: str
    """What was being waited for, and where it stood when the wait gave up."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.msg = msg


def wait_for(
    condition: Condition,
    args: typing.Optional[collections.abc.Sequence[typing.Any]] = None,
    timeout: float = 60 * 5,
    interval: Interval = 5,
    timeout_msg: str = "wait_for timed out",
) -> None:
    """Call ``condition`` until it returns a truthy value, or raise once ``timeout`` seconds have passed.

    The first call happens at once, and each later call follows a sleep of ``interval``. Time spent sleeping and in
    ``condition`` counts toward ``timeout``. The deadline is checked only before a sleep, so the last call can end up
    to one interval plus one call after ``timeout``. A ``timeout`` of zero or less raises without calling
    ``condition``. An exception ``condition`` raises propagates and ends the wait.

    Args:
        args:Positional arguments to pass to ``condition`` on every call. ``None`` passes none.
        timeout: Maximum time to wait, in seconds.
        interval: Seconds to sleep before each call after the first, or a function that takes the number of calls
            made so far and returns the seconds to sleep before the next.
        timeout_msg: Message of the ``TimeoutError`` raised when ``timeout`` passes.

    Raises:
        roboto.waiters.TimeoutError: ``condition`` returned no truthy value within ``timeout``.
    """
    time_remaining = timeout
    args = args if args is not None else []
    iteration = 0
    while time_remaining > 0:
        iteration_start = time.monotonic()
        if iteration > 0:
            if callable(interval):
                time.sleep(interval(iteration))
            else:
                time.sleep(interval)
        if condition(*args):
            return

        iteration_duration = time.monotonic() - iteration_start
        time_remaining -= iteration_duration
        iteration += 1

    raise TimeoutError(timeout_msg)
