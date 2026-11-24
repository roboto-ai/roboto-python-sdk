# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import typing

from .request import HttpRequest

RetryPredicate = typing.Callable[[HttpRequest, BaseException], bool]
"""Function that decides whether to retry a failed request, and returns ``True`` to retry it.

It is called with the request and the exception the failed attempt raised. ``HttpRetryOptions.predicate`` holds one."""


def never_retry(_request: HttpRequest, _exc: BaseException) -> bool:
    """Return ``False`` to decline every retry, so the client attempts each request once.

    Use it for a request whose effect must not happen twice, such as sending a chat message or an email, when the
    server cannot recognize a repeated request: a retry after a timeout could deliver the message a second time.

    Examples:
        >>> from roboto.http import HttpClient, HttpClientOptions, HttpRetryOptions, never_retry
        >>> client = HttpClient(options=HttpClientOptions(retry=HttpRetryOptions(predicate=never_retry)))
    """
    return False


@dataclasses.dataclass(frozen=True)
class HttpLoggingOptions:
    """Logging settings of an :py:class:`~roboto.http.HttpClient`: which parts of a request it hides in its logs."""

    scrub_headers: typing.Sequence[str] = ()
    """Names of headers whose values the client replaces with ``*`` when it logs a request.

    Names are compared case-insensitively. The ``Authorization`` header's value is always replaced, whether or not it
    is listed here."""

    log_only_method_and_origin: bool = False
    """Whether the client's debug log names each request by its method and its URL's origin only.

    The origin is the URL's scheme, host and port. When ``True``, the log leaves out the URL's path and query, the
    request headers, and the body. A response's line gives only its status, and a failed request's line gives only an
    HTTP error's status or the exception's class, with no message or traceback. The ``ConnectionRefusedError`` the
    client raises names only the origin. Turn it on for a client whose request URLs or bodies hold secrets or personal
    data, such as one that posts to a Slack incoming webhook."""


@dataclasses.dataclass(frozen=True)
class HttpRetryOptions:
    """Retry settings of an :py:class:`~roboto.http.HttpClient`: which failed requests it retries and how many times."""

    predicate: typing.Optional[RetryPredicate] = None
    """Function called with the request and the exception a failed attempt raised; ``True`` retries the request.

    ``None`` uses :py:func:`~roboto.http.is_expected_to_be_transient`, which retries a failed DNS lookup and HTTP 429,
    502 and 503 on any request, and connection errors, timeouts, and HTTP 408, 500 and 504 only on a request marked
    ``idempotent``. ``never_retry`` retries nothing."""

    max_attempts: int = 10
    """Maximum number of attempts per request, the first included.

    A value below 1 behaves as 1: the first attempt always runs."""


@dataclasses.dataclass(frozen=True)
class HttpClientOptions:
    """Settings of an :py:class:`~roboto.http.HttpClient` that apply to every request it makes."""

    logging: HttpLoggingOptions = HttpLoggingOptions()
    """Settings for how the client logs requests."""

    retry: HttpRetryOptions = HttpRetryOptions()
    """Settings for when the client retries a failed request."""
