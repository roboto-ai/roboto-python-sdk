# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import typing

from .request import HttpRequest

RetryPredicate = typing.Callable[[HttpRequest, BaseException], bool]
"""Decides whether the exception warrants another attempt at the request."""


def never_retry(_request: HttpRequest, _exc: BaseException) -> bool:
    """Retry predicate giving every request exactly one attempt.

    Use for calls whose side effect must not run twice and where the server offers no
    idempotency key: a retried delivery (a chat message, an email) lands as a duplicate.
    """
    return False


@dataclasses.dataclass(frozen=True)
class HttpLoggingOptions:
    """How a :py:class:`~roboto.http.HttpClient` renders requests into its logs."""

    scrub_headers: typing.Sequence[str] = ()
    """Header names, compared case-insensitively, whose values are replaced with ``*`` in every
    rendered form of a request the client produces. ``Authorization`` is always scrubbed, with
    or without an entry here."""


@dataclasses.dataclass(frozen=True)
class HttpRetryOptions:
    """Whether and how many times a :py:class:`~roboto.http.HttpClient` retries a failed request."""

    predicate: typing.Optional[RetryPredicate] = None
    """Called with the request and the exception a failed attempt raised; ``True`` means try
    again. ``None`` keeps the default, :py:func:`~roboto.http.is_expected_to_be_transient`,
    which retries failures expected to be transient: DNS resolution failures unconditionally;
    connection errors, timeouts, and retryable HTTP statuses according to the request's
    idempotency."""

    max_attempts: int = 10
    """Total attempts per request, first try included. Values below 1 behave as 1: the first
    attempt always runs."""


@dataclasses.dataclass(frozen=True)
class HttpClientOptions:
    """Behavior of a :py:class:`~roboto.http.HttpClient`, applied to every request it makes."""

    logging: HttpLoggingOptions = HttpLoggingOptions()
    retry: HttpRetryOptions = HttpRetryOptions()
