# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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

logger = logging.getLogger(LOGGER_NAME)


class is_expected_to_be_transient:
    """Retry predicate that returns True if the exception is expected to be transient."""

    __request: HttpRequest

    def __init__(self, request: HttpRequest):
        self.__request = request

    def __call__(self, exc: typing.Any) -> bool:
        # HTTP status codes -- must come first since HTTPError is a URLError
        if isinstance(exc, urllib.error.HTTPError):
            return self.__is_transient_http_status(exc)

        # Unwrap URLError to get the underlying cause.
        # URLError wraps OSError subclasses during request sending (see CPython's
        # urllib.request.do_open), but errors during response reading propagate bare.
        # By unwrapping here, we classify the underlying error once regardless
        # of whether urllib wrapped it.
        # See: https://github.com/python/cpython/blob/3.13/Lib/urllib/request.py
        if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
            exc = exc.reason

        # DNS resolution failures -- safe to retry unconditionally
        # (request never reached the server).
        # See: https://docs.python.org/3/library/socket.html#socket.gaierror
        # Resolves: ENG-2166
        if isinstance(exc, socket.gaierror):
            return True

        # Connection-level errors -- safe to retry only for idempotent requests.
        # Covers: RemoteDisconnected (a ConnectionResetError subclass),
        #         ConnectionResetError, ConnectionRefusedError,
        #         ConnectionAbortedError, BrokenPipeError.
        # See: https://docs.python.org/3/library/exceptions.html#ConnectionError
        # See: https://docs.python.org/3/library/http.client.html#http.client.RemoteDisconnected
        if isinstance(exc, ConnectionError):
            if isinstance(exc, http.client.RemoteDisconnected):
                logger.warning("Remote host closed connection", exc_info=exc)
            return self.__request_expected_to_be_idempotent()

        # Timeouts -- safe to retry only for idempotent requests.
        # socket.timeout is an alias for TimeoutError since Python 3.3.
        if isinstance(exc, TimeoutError):
            return self.__request_expected_to_be_idempotent()

        return False

    def __is_transient_http_status(self, exc: urllib.error.HTTPError) -> bool:
        try:
            status_code = http.HTTPStatus(int(exc.code))
        except ValueError:
            return False

        if not self.__request_expected_to_be_idempotent():
            # 408, 500, and 504 are not safe to retry if the request is not idempotent --
            # the server may have received and processed the request.
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

    def __request_expected_to_be_idempotent(self) -> bool:
        return self.__request.idempotent is True


class HttpClient:
    __base_headers: dict[str, str]
    __default_auth: typing.Optional[HttpRequestDecorator]
    __default_endpoint: typing.Optional[str]
    __extra_headers_provider: typing.Optional[typing.Callable[[], dict[str, str]]]
    __default_timeout: typing.Optional[float]

    def __init__(
        self,
        base_headers: typing.Optional[dict[str, str]] = None,
        default_endpoint: typing.Optional[str] = None,
        default_auth: typing.Optional[HttpRequestDecorator] = None,
        requester: typing.Optional[RobotoRequester] = None,
        extra_headers_provider: typing.Optional[typing.Callable[[], dict[str, str]]] = None,
        default_timeout: typing.Optional[float] = None,  # None means no timeout
    ):
        self.__base_headers = base_headers if base_headers is not None else {}
        self.__extra_headers_provider = extra_headers_provider

        if requester is not None:
            self.set_requester(requester)

        self.__default_auth = default_auth
        self.__default_endpoint = default_endpoint
        self.__default_timeout = default_timeout

    def delete(
        self,
        url: str,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
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
        self.__base_headers[ROBOTO_REQUESTER_HEADER] = requester.model_dump_json(exclude_none=True)

    def url(self, path: str) -> str:
        if self.__default_endpoint is None:
            raise ValueError("HttpClient.url called for client with no default endpoint.")
        return f"{self.__default_endpoint}/{path}"

    @property
    def auth_decorator(self) -> typing.Optional[HttpRequestDecorator]:
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

        logger.debug("%s", request_ctx)

        headers = self.__request_headers(request_ctx)

        try:
            for attempt in tenacity.Retrying(
                retry=tenacity.retry_if_exception(is_expected_to_be_transient(request_ctx)),
                stop=tenacity.stop_after_attempt(10),
                reraise=True,
                wait=self.__wait(request_ctx.retry_wait),
            ):
                with attempt:
                    # S310: URL is constructed by SDK from a configured endpoint, not from user input
                    request = urllib.request.Request(request_ctx.url, method=request_ctx.method)  # noqa: S310

                    req_body = request_ctx.body
                    if req_body is not None:
                        request.data = req_body

                    for key, value in headers.items():
                        request.add_header(key, value)

                    response = HttpResponse(urllib.request.urlopen(request, timeout=timeout))  # noqa: S310
                    logger.debug("Response: %s %s", response.status, response.headers)
                    return response
        except urllib.error.HTTPError as exc:
            logger.debug("HTTPError: %s", exc, exc_info=True)
            status_code = exc.code
            if 400 <= status_code < 500:
                raise ClientError(exc) from None
            elif status_code >= 500:
                raise ServerError(exc) from None
            else:
                raise HttpError(exc) from None
        except urllib.error.URLError as exc:
            logger.debug("URLError: %s", exc, exc_info=True)
            if isinstance(exc.reason, ConnectionRefusedError):
                raise ConnectionRefusedError(f"Couldn't connect to endpoint {request_ctx.url}") from None
            else:
                raise
        except Exception:
            logger.debug("Catchall Exception", exc_info=True)
            raise

        raise RuntimeError("Unreachable")

    def __wait(self, waiter: RetryWaitFn) -> tenacity.wait.wait_base:
        class Waiter(tenacity.wait.wait_base):
            def __call__(self, retry_state: tenacity.RetryCallState) -> float:
                return waiter(retry_state, None) / 1000

        return Waiter()
