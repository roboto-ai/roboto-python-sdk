# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import time
import typing

Condition = typing.Callable[..., bool]
Interval = typing.Union[int, typing.Callable[[int], int]]


class TimeoutError(Exception):
    msg: str

    def __init__(self, msg: str, *args) -> None:
        super().__init__(*args)
        self.msg = msg


def wait_for(
    condition: Condition,
    args: typing.Optional[collections.abc.Sequence[typing.Any]] = None,
    timeout: float = 60 * 5,
    interval: Interval = 5,
    timeout_msg: str = "wait_for timed out",
) -> None:
    """
    Wait for a condition to be truthy.

    Args:
        condition: The condition to wait for. This should be a callable that returns a boolean.
        args: The arguments to pass to the condition callable on each iteration.
        timeout: The maximum amount of time to wait for the condition to be truthy.
        interval: The amount of time to wait between iterations. This can be an integer or a callable.
            If it is a callable, it will be called with the iteration number and should return an integer.
        timeout_msg: The message to include in the TimeoutError if the timeout is reached.

    Raises:
        TimeoutError: If the timeout is reached before the condition is truthy.

    Returns:
        None
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
