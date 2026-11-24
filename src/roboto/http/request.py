# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import typing
import urllib.error
import urllib.parse
import urllib.request
import urllib.response

import pydantic

from .retry import (
    RetryWaitFn,
    default_retry_wait_ms,
)

Model = typing.TypeVar("Model")
"""Type of the requests a ``BatchRequest`` holds."""

ALWAYS_SCRUBBED_HEADERS = frozenset({"authorization"})
"""Header names, in lowercase, whose values ``HttpRequest.describe`` always replaces with ``*``."""


class HttpRequest:
    """An HTTP request for :py:class:`~roboto.http.HttpClient` to send, with the settings that govern its retries.

    :py:class:`~roboto.http.HttpClient` builds one for each call it makes, and passes it to its authentication
    decorator and to its retry predicate. Its constructor takes one parameter for each attribute, of the same name.
    """

    url: str
    """Absolute URL to send the request to."""

    method: str
    """HTTP method, such as ``"GET"`` or ``"POST"``."""

    headers: dict
    """Headers to send with the request.

    The request adds to the dictionary passed to its constructor in place, not to a copy. Passing ``None`` starts with
    no headers.
    """

    retry_wait: RetryWaitFn
    """Function that returns how long to wait before the next attempt, in milliseconds.

    It takes the ``tenacity.RetryCallState`` of the request and an exception, which
    :py:class:`~roboto.http.HttpClient` always passes as ``None``. Passing ``None`` to the constructor waits a random
    time of up to 1 second after the first attempt, doubling that limit after each attempt up to 30 seconds.
    """

    data: typing.Any = None
    """Request body, or ``None`` for no body.

    A pydantic model or a dictionary also sets the ``Content-Type`` header to ``application/json``. ``body`` says how
    each type is encoded.
    """

    idempotent: bool = False
    """Whether sending the request more than once has the same effect as sending it once.

    The default retry predicate, :py:func:`~roboto.http.is_expected_to_be_transient`, retries connection errors,
    timeouts, and responses with status 408, 500 or 504 only for an idempotent request.
    """

    def __init__(
        self,
        url: str,
        method: str = "GET",
        headers: typing.Optional[dict[str, str]] = None,
        data: typing.Any = None,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        idempotent: bool = False,
    ):
        self.url = url
        self.method = method
        self.headers = headers if headers is not None else {}
        self.data = data
        self.retry_wait = retry_wait if retry_wait is not None else default_retry_wait_ms
        self.idempotent = idempotent

        if isinstance(self.data, pydantic.BaseModel) or isinstance(self.data, dict):
            self.headers["Content-Type"] = "application/json"

    def __repr__(self) -> str:
        return self.describe()

    def describe(self, scrub_headers: typing.Collection[str] = (), only_method_and_origin: bool = False) -> str:
        """Render the request for logging, with sensitive header values replaced by ``*``.

        Unless ``only_method_and_origin`` is ``True``, the body is rendered in full; nothing in it is scrubbed.

        Args:
            scrub_headers: Header names, compared case-insensitively, whose values to replace in addition to
                ``ALWAYS_SCRUBBED_HEADERS``.
            only_method_and_origin: Whether to render only the method and the URL's ``origin``, leaving out the URL's
                path and query, the headers, and the body.
        """
        if only_method_and_origin:
            return f"HttpRequest(method={self.method}, origin={self.origin})"

        scrub = ALWAYS_SCRUBBED_HEADERS.union(header.lower() for header in scrub_headers)
        headers = {key: "*" if key.lower() in scrub else value for key, value in self.headers.items()}
        return (
            f"HttpRequest("
            f"url={self.url}, "
            f"method={self.method}, "
            f"headers={headers}, "
            f"data={self.data}, "
            f"idempotent={self.idempotent}"
            ")"
        )

    @property
    def body(self) -> typing.Optional[bytes]:
        """Request body as the bytes sent, or ``None`` when the request has no body.

        Each type of ``data`` is encoded as follows:

        - ``bytes`` is sent as given.
        - A string is encoded as UTF-8.
        - A pydantic model is encoded as JSON, leaving out the fields the caller never set.
        - Anything else is encoded as JSON by ``json.dumps``.

        Reading it raises ``TypeError`` when ``data`` is of a type ``json.dumps`` cannot encode.
        """
        if self.data is None:
            return None

        if isinstance(self.data, bytes):
            return self.data

        if isinstance(self.data, str):
            return self.data.encode("utf-8")

        if isinstance(self.data, pydantic.BaseModel):
            return self.data.model_dump_json(exclude_unset=True).encode("utf-8")

        return json.dumps(self.data).encode("utf-8")

    @property
    def hostname(self) -> str:
        """Host name in the request's URL, without the port.

        The URL's whole network location when no host name can be parsed from it.
        """
        parsed_url = urllib.parse.urlparse(self.url)
        return parsed_url.hostname if parsed_url.hostname is not None else parsed_url.netloc

    @property
    def origin(self) -> str:
        """Scheme, host and port of the request's URL, such as ``https://hooks.slack.com``.

        Any user name or password the URL carries is left out.
        """
        parsed_url = urllib.parse.urlparse(self.url)
        host = parsed_url.netloc.rpartition("@")[2]
        return f"{parsed_url.scheme}://{host}"

    def append_headers(self, headers: dict[str, str]) -> None:
        """Add headers to the request, replacing the value of any header with the same name, matched case-sensitively.

        Args:
            headers: Headers to add.
        """
        self.headers.update(headers)


HttpRequestDecorator = typing.Callable[[HttpRequest], HttpRequest]
"""Function that prepares a request before it is sent, such as by adding authentication headers, and returns it.

:py:class:`~roboto.http.BearerTokenDecorator` and :py:class:`~roboto.http.SigV4AuthDecorator` are two.
"""


class BatchRequest(pydantic.BaseModel, typing.Generic[Model]):
    """Request body for a route that applies several requests of one kind in one call.

    Sent by :py:meth:`~roboto.domain.files.File.import_batch` to ``POST /v1/files/import/batch``.
    """

    requests: list[Model]
    """Requests in the batch."""
