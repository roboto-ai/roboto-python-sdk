# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import random
import typing

import tenacity.wait

RetryWaitFn = typing.Callable[[tenacity.RetryCallState, typing.Optional[BaseException]], float]
"""Function that chooses how long to wait before the next attempt of a request, and returns that wait in milliseconds.

It takes the ``tenacity.RetryCallState`` of the request and an exception, which
:py:class:`~roboto.http.HttpClient` always passes as ``None``.
"""


def default_retry_wait_ms(retry_state: tenacity.RetryCallState, _exc: typing.Optional[BaseException]) -> float:
    """Return a random wait before the next attempt of a request, in milliseconds.

    :py:class:`~roboto.http.HttpRequest` uses this when it is built without a ``retry_wait``. The wait is up to 1
    second after the first attempt, and that limit doubles after each attempt, up to 30 seconds. Choosing the wait at
    random keeps clients whose requests failed at the same moment from retrying at the same moment. This is the "full
    jitter" backoff described at https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/.

    Args:
        retry_state: Retry state of the request. Its ``attempt_number`` counts the attempts made so far, from 1.

    Returns:
        Milliseconds to wait, from 0 to 30,000.
    """
    base = 500
    cap = 30_000

    exponential_wait = min(cap, pow(2, retry_state.attempt_number) * base)
    jittered = random.uniform(0, exponential_wait)
    return jittered
