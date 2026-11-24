# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import functools
import http
import http.client
import logging
import socket
import typing
import urllib.error
import urllib.request

import tenacity
import tenacity.wait

from ..env import Timeout
from ..exceptions import (
    ClientError,
    HttpError,
    ServerError,
)
from ..logging import LOGGER_NAME
from ..sentinels import NotSet, is_set
from .options import HttpClientOptions
from .request import (
    HttpRequest,
    HttpRequestDecorator,
    RetryWaitFn,
)
from .requester import (
    ROBOTO_REQUESTER_HEADER,
    RobotoRequester,
)
from .response import HttpResponse
from .tls import https_ssl_context

logger = logging.getLogger(LOGGER_NAME)


def is_expected_to_be_transient(request: HttpRequest, exc: BaseException) -> bool:
    """Return whether a failed attempt at a request is expected to succeed if tried again.

    ``HttpClient`` retries with this predicate unless :py:attr:`~roboto.http.HttpRetryOptions.predicate` names another.
    A predicate of your own can call it to keep these rules and add to them. It retries:

    - A host name that fails to resolve, for any request, since the request never reached the server.
    - A 429, 502 or 503 status, for any request.
    - A 408, 500 or 504 status, a connection that fails or closes, or a timeout, only when ``request.idempotent`` is
      ``True``, since the server may have received and acted on the request.

    Nothing else is retried.

    Args:
        request: Request whose attempt failed.
        exc: Exception the failed attempt raised.
    """
    # HTTPError subclasses URLError, so it is checked before the URLError unwrapping below.
    if isinstance(exc, urllib.error.HTTPError):
        return _is_transient_http_status(request, exc)

    # urllib wraps an OSError raised while sending the request in a URLError (see AbstractHTTPHandler.do_open in
    # urllib.request), but lets one raised while reading the response propagate unwrapped. Unwrapping classifies the
    # same error the same way in both cases.
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        exc = exc.reason

    # The host name did not resolve, so the request never reached the server.
    if isinstance(exc, socket.gaierror):
        return True

    # ConnectionError covers ConnectionResetError (including http.client.RemoteDisconnected), ConnectionRefusedError,
    # ConnectionAbortedError and BrokenPipeError.
    if isinstance(exc, ConnectionError):
        if isinstance(exc, http.client.RemoteDisconnected):
            logger.warning("Remote host closed connection", exc_info=exc)
        return request.idempotent is True

    # socket.timeout is an alias of TimeoutError, so this covers socket timeouts too.
    if isinstance(exc, TimeoutError):
        return request.idempotent is True

    return False


def _is_transient_http_status(request: HttpRequest, exc: urllib.error.HTTPError) -> bool:
    try:
        status_code = http.HTTPStatus(int(exc.code))
    except ValueError:
        return False

    if request.idempotent is not True:
        # The server may have received and acted on a request that drew one of these statuses.
        if status_code in (
            http.HTTPStatus.REQUEST_TIMEOUT,
            http.HTTPStatus.INTERNAL_SERVER_ERROR,
            http.HTTPStatus.GATEWAY_TIMEOUT,
        ):
            return False

    return status_code in (
        http.HTTPStatus.REQUEST_TIMEOUT,
        http.HTTPStatus.INTERNAL_SERVER_ERROR,
        http.HTTPStatus.TOO_MANY_REQUESTS,
        http.HTTPStatus.BAD_GATEWAY,
        http.HTTPStatus.SERVICE_UNAVAILABLE,
        http.HTTPStatus.GATEWAY_TIMEOUT,
    )


class HttpClient:
    """HTTP client that sends each request with the same headers, authentication, timeout and retry rules.

    :py:class:`~roboto.http.RobotoClient` sends the SDK's requests to Roboto through one of these, and converts the
    errors it raises into Roboto exceptions (see :py:class:`~roboto.exceptions.HttpError`).

    For each request, the client:

    1. Passes the request through ``default_auth``, when set.
    2. Sends the base headers, then the headers ``extra_headers_provider`` returns, then the request's own, each
       replacing any earlier header of the same name.
    3. Sends the request. When an attempt raises, attempts remain, and the retry predicate in ``options`` accepts the
       exception, it waits the request's ``retry_wait`` and tries again. Otherwise the method raises.

    A request body (``data``) of bytes or a string is sent as given, a pydantic model as JSON holding the fields that
    were set, and any other value as the output of ``json.dumps``. A pydantic model or a dictionary also sets
    ``Content-Type: application/json``.

    Args:
        base_headers: Headers to send with every request. ``None`` sends none.
        default_endpoint: Base URL that ``url`` appends paths to. ``None`` leaves the client without one, and ``url``
            then raises ``ValueError``.
        default_auth: Function applied to every request before it is sent, such as
            :py:class:`~roboto.http.BearerTokenDecorator`, which adds an access token. ``None`` sends requests as
            given.
        requester: Tool sending the requests, reported in every request's ``X-Roboto-Requester`` header, as
            ``set_requester`` sets it. ``None`` sends no such header.
        extra_headers_provider: Function called before every request, whose headers are added to the base headers.
            They stay there, so a header it stops returning keeps its last value. ``None`` adds none.
        default_timeout: Timeout in seconds for requests that pass no ``timeout``. It limits each wait to connect or
            to receive data, not the request as a whole. ``None`` waits indefinitely.
        options: Logging and retry behavior for every request. ``None`` uses the defaults of
            :py:class:`~roboto.http.HttpClientOptions`.
    """

    __base_headers: dict[str, str]
    __default_auth: typing.Optional[HttpRequestDecorator]
    __default_endpoint: typing.Optional[str]
    __extra_headers_provider: typing.Optional[typing.Callable[[], dict[str, str]]]
    __default_timeout: typing.Optional[float]
    __options: HttpClientOptions

    def __init__(
        self,
        base_headers: typing.Optional[dict[str, str]] = None,
        default_endpoint: typing.Optional[str] = None,
        default_auth: typing.Optional[HttpRequestDecorator] = None,
        requester: typing.Optional[RobotoRequester] = None,
        extra_headers_provider: typing.Optional[typing.Callable[[], dict[str, str]]] = None,
        default_timeout: typing.Optional[float] = None,
        options: typing.Optional[HttpClientOptions] = None,
    ):
        self.__base_headers = base_headers if base_headers is not None else {}
        self.__extra_headers_provider = extra_headers_provider

        if requester is not None:
            self.set_requester(requester)

        self.__default_auth = default_auth
        self.__default_endpoint = default_endpoint
        self.__default_timeout = default_timeout
        self.__options = options if options is not None else HttpClientOptions()

    def delete(
        self,
        url: str,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a DELETE request to ``url`` and return its response.

        Args:
            url: Full URL to send the request to. The ``url`` method builds one from the client's ``default_endpoint``.
            data: Body of the request, encoded as ``HttpClient`` describes. ``None`` sends no body.
            headers: Headers for this request only. Each replaces a client header of the same name.
            idempotent: Whether sending the request more than once has the same effect as sending it once. The default
                retry predicate retries a timeout, a failed connection, or a 408, 500 or 504 status only for an
                idempotent request.
            retry_wait: Function that returns how many milliseconds to wait before the next attempt. ``None`` waits a
                random time up to a limit that starts at 1 second and doubles after each attempt, to at most 30
                seconds.
            timeout: Timeout in seconds for each wait to connect or to receive data. ``None`` waits indefinitely.
                Left unset, the client's ``default_timeout`` applies.

        Raises:
            ClientError: The last attempt's response has a 4xx status.
            ServerError: The last attempt's response has a status of 500 or above.
            HttpError: The last attempt's response has any other error status.
            ConnectionRefusedError: The server refused the connection on the last attempt.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: The server sent no response within ``timeout`` on the last attempt.
        """
        request = HttpRequest(
            url=url,
            method="DELETE",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        timeout = self.__resolve_timeout(timeout)
        return self.__request(request, timeout=timeout)

    def get(
        self,
        url: str,
        headers: typing.Optional[dict] = None,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        idempotent: bool = True,
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a GET request to ``url`` and return its response.

        Args:
            url: Full URL to send the request to. The ``url`` method builds one from the client's ``default_endpoint``.
            headers: Headers for this request only. Each replaces a client header of the same name.
            retry_wait: Function that returns how many milliseconds to wait before the next attempt. ``None`` waits a
                random time up to a limit that starts at 1 second and doubles after each attempt, to at most 30
                seconds.
            idempotent: Whether sending the request more than once has the same effect as sending it once. The default
                retry predicate retries a timeout, a failed connection, or a 408, 500 or 504 status only for an
                idempotent request.
            timeout: Timeout in seconds for each wait to connect or to receive data. ``None`` waits indefinitely.
                Left unset, the client's ``default_timeout`` applies.

        Raises:
            ClientError: The last attempt's response has a 4xx status.
            ServerError: The last attempt's response has a status of 500 or above.
            HttpError: The last attempt's response has any other error status.
            ConnectionRefusedError: The server refused the connection on the last attempt.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: The server sent no response within ``timeout`` on the last attempt.
        """
        request = HttpRequest(
            url=url,
            method="GET",
            headers=headers,
            retry_wait=retry_wait,
            idempotent=idempotent,
        )
        timeout = self.__resolve_timeout(timeout)
        return self.__request(request, timeout=timeout)

    def post(
        self,
        url: str,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = False,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a POST request to ``url`` and return its response.

        Args:
            url: Full URL to send the request to. The ``url`` method builds one from the client's ``default_endpoint``.
            data: Body of the request, encoded as ``HttpClient`` describes. ``None`` sends no body.
            headers: Headers for this request only. Each replaces a client header of the same name.
            idempotent: Whether sending the request more than once has the same effect as sending it once. The default
                retry predicate retries a timeout, a failed connection, or a 408, 500 or 504 status only for an
                idempotent request.
            retry_wait: Function that returns how many milliseconds to wait before the next attempt. ``None`` waits a
                random time up to a limit that starts at 1 second and doubles after each attempt, to at most 30
                seconds.
            timeout: Timeout in seconds for each wait to connect or to receive data. ``None`` waits indefinitely.
                Left unset, the client's ``default_timeout`` applies.

        Raises:
            ClientError: The last attempt's response has a 4xx status.
            ServerError: The last attempt's response has a status of 500 or above.
            HttpError: The last attempt's response has any other error status.
            ConnectionRefusedError: The server refused the connection on the last attempt.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: The server sent no response within ``timeout`` on the last attempt.
        """
        request = HttpRequest(
            url=url,
            method="POST",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        timeout = self.__resolve_timeout(timeout)
        return self.__request(request, timeout=timeout)

    def patch(
        self,
        url: str,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a PATCH request to ``url`` and return its response.

        Args:
            url: Full URL to send the request to. The ``url`` method builds one from the client's ``default_endpoint``.
            data: Body of the request, encoded as ``HttpClient`` describes. ``None`` sends no body.
            headers: Headers for this request only. Each replaces a client header of the same name.
            idempotent: Whether sending the request more than once has the same effect as sending it once. The default
                retry predicate retries a timeout, a failed connection, or a 408, 500 or 504 status only for an
                idempotent request.
            retry_wait: Function that returns how many milliseconds to wait before the next attempt. ``None`` waits a
                random time up to a limit that starts at 1 second and doubles after each attempt, to at most 30
                seconds.
            timeout: Timeout in seconds for each wait to connect or to receive data. ``None`` waits indefinitely.
                Left unset, the client's ``default_timeout`` applies.

        Raises:
            ClientError: The last attempt's response has a 4xx status.
            ServerError: The last attempt's response has a status of 500 or above.
            HttpError: The last attempt's response has any other error status.
            ConnectionRefusedError: The server refused the connection on the last attempt.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: The server sent no response within ``timeout`` on the last attempt.
        """
        request = HttpRequest(
            url=url,
            method="PATCH",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        timeout = self.__resolve_timeout(timeout)
        return self.__request(request, timeout=timeout)

    def put(
        self,
        url: str,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a PUT request to ``url`` and return its response.

        Args:
            url: Full URL to send the request to. The ``url`` method builds one from the client's ``default_endpoint``.
            data: Body of the request, encoded as ``HttpClient`` describes. ``None`` sends no body.
            headers: Headers for this request only. Each replaces a client header of the same name.
            idempotent: Whether sending the request more than once has the same effect as sending it once. The default
                retry predicate retries a timeout, a failed connection, or a 408, 500 or 504 status only for an
                idempotent request.
            retry_wait: Function that returns how many milliseconds to wait before the next attempt. ``None`` waits a
                random time up to a limit that starts at 1 second and doubles after each attempt, to at most 30
                seconds.
            timeout: Timeout in seconds for each wait to connect or to receive data. ``None`` waits indefinitely.
                Left unset, the client's ``default_timeout`` applies.

        Raises:
            ClientError: The last attempt's response has a 4xx status.
            ServerError: The last attempt's response has a status of 500 or above.
            HttpError: The last attempt's response has any other error status.
            ConnectionRefusedError: The server refused the connection on the last attempt.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: The server sent no response within ``timeout`` on the last attempt.
        """
        request = HttpRequest(
            url=url,
            method="PUT",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        timeout = self.__resolve_timeout(timeout)
        return self.__request(request, timeout=timeout)

    def set_requester(self, requester: RobotoRequester):
        """Set the tool reported in the ``X-Roboto-Requester`` header of every later request.

        Args:
            requester: Tool, version and platform sending the requests. Fields left ``None`` are left out of the
                header.
        """
        self.__base_headers[ROBOTO_REQUESTER_HEADER] = requester.model_dump_json(exclude_none=True)

    def url(self, path: str) -> str:
        """Return the URL of ``path`` under the client's ``default_endpoint``.

        Args:
            path: Path to append to the endpoint, without a leading slash.

        Raises:
            ValueError: The client has no ``default_endpoint``.
        """
        if self.__default_endpoint is None:
            raise ValueError("HttpClient.url called for client with no default endpoint.")
        return f"{self.__default_endpoint}/{path}"

    @property
    def auth_decorator(self) -> typing.Optional[HttpRequestDecorator]:
        """Function the client applies to every request before sending it, or ``None`` if it sends them as given."""
        return self.__default_auth

    def __resolve_timeout(self, timeout: Timeout) -> typing.Optional[float]:
        return timeout if is_set(timeout) else self.__default_timeout

    def __request_headers(self, request_ctx: HttpRequest) -> dict[str, str]:
        if self.__extra_headers_provider is not None:
            self.__base_headers.update(self.__extra_headers_provider())

        headers = self.__base_headers.copy()

        if request_ctx.headers:
            headers.update(request_ctx.headers)

        return headers

    def __request(self, request_ctx: HttpRequest, timeout: typing.Optional[float]) -> HttpResponse:
        if self.__default_auth is not None:
            request_ctx = self.__default_auth(request_ctx)

        logging_options = self.__options.logging
        only_method_and_origin = logging_options.log_only_method_and_origin
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                request_ctx.describe(
                    scrub_headers=logging_options.scrub_headers, only_method_and_origin=only_method_and_origin
                )
            )

        headers = self.__request_headers(request_ctx)

        retry = self.__options.retry
        predicate = retry.predicate if retry.predicate is not None else is_expected_to_be_transient

        try:
            for attempt in tenacity.Retrying(
                retry=tenacity.retry_if_exception(functools.partial(predicate, request_ctx)),
                stop=tenacity.stop_after_attempt(retry.max_attempts),
                reraise=True,
                wait=self.__wait(request_ctx.retry_wait),
            ):
                with attempt:
                    # S310 flags urlopen because it also opens file: URLs. Callers build the URL from a configured
                    # endpoint, not from end-user input.
                    request = urllib.request.Request(request_ctx.url, method=request_ctx.method)  # noqa: S310

                    req_body = request_ctx.body
                    if req_body is not None:
                        request.data = req_body

                    for key, value in headers.items():
                        request.add_header(key, value)

                    response = HttpResponse(
                        urllib.request.urlopen(request, timeout=timeout, context=https_ssl_context())  # noqa: S310
                    )
                    if only_method_and_origin:
                        logger.debug("Response: %s", response.status)
                    else:
                        logger.debug("Response: %s %s", response.status, response.headers)
                    return response
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            if only_method_and_origin:
                logger.debug("HTTPError: %s", status_code)
            else:
                logger.debug("HTTPError: %s", exc, exc_info=True)
            if 400 <= status_code < 500:
                raise ClientError(exc) from None
            elif status_code >= 500:
                raise ServerError(exc) from None
            else:
                raise HttpError(exc) from None
        except urllib.error.URLError as exc:
            if only_method_and_origin:
                # The reason is the OSError urllib wrapped, whose class is logged, or a message string, which is not.
                reason_class = type(exc.reason).__name__ if isinstance(exc.reason, BaseException) else ""
                logger.debug("URLError: %s", reason_class)
            else:
                logger.debug("URLError: %s", exc, exc_info=True)
            if isinstance(exc.reason, ConnectionRefusedError):
                # urllib's message for a refused connection does not name the endpoint.
                endpoint = request_ctx.origin if only_method_and_origin else request_ctx.url
                raise ConnectionRefusedError(f"Couldn't connect to endpoint {endpoint}") from None
            else:
                raise
        except Exception as exc:
            if only_method_and_origin:
                logger.debug("Catchall Exception: %s", type(exc).__name__)
            else:
                logger.debug("Catchall Exception", exc_info=True)
            raise

        raise RuntimeError("Unreachable")

    def __wait(self, waiter: RetryWaitFn) -> tenacity.wait.wait_base:
        class Waiter(tenacity.wait.wait_base):
            def __call__(self, retry_state: tenacity.RetryCallState) -> float:
                # RetryWaitFn returns milliseconds; tenacity waits in seconds.
                return waiter(retry_state, None) / 1000

        return Waiter()
