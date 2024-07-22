# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import errno
import http
import http.client
import logging
import typing
import urllib.error
import urllib.parse
import urllib.request
import urllib.response

import tenacity
import tenacity.wait

from roboto.exceptions import (
    ClientError,
    HttpError,
    ServerError,
)

from ..logging import LOGGER_NAME
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

DEFAULT_HEADERS = object()


class is_expected_to_be_transient:
    """Retry predicate that returns True if the exception is expected to be transient."""

    __request: HttpRequest

    def __init__(self, request: HttpRequest):
        self.__request = request

    def __call__(self, exc: typing.Any) -> bool:
        if isinstance(exc, http.client.RemoteDisconnected):
            logger.warning("Remote host closed connection", exc_info=exc)
            if not self.__request_expected_to_be_idempotent():
                # Request may have be processed, we don't know.
                return False

            return True

        if isinstance(exc, urllib.error.HTTPError):
            try:
                status_code = http.HTTPStatus(int(exc.code))

                if not self.__request_expected_to_be_idempotent():
                    # 500 and 504 are not safe to retry if the request is not idempotent
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
            except ValueError:
                return False

        # Must come after the isinstance check of HTTPError,
        # which is a subclass of URLError
        if isinstance(exc, urllib.error.URLError):
            # Connection reset by peer, probably transient
            conn_reset_error = (
                isinstance(exc.reason, OSError) and exc.reason.errno == errno.ECONNRESET
            ) or "Connection reset by peer" in str(exc.reason)
            if conn_reset_error and self.__request_expected_to_be_idempotent():
                return True

            # DNS error, probably transient
            return "Temporary failure in name resolution" in str(exc.reason)

        return False

    def __request_expected_to_be_idempotent(self) -> bool:
        return self.__request.idempotent is True


class HttpClient:
    __base_headers: dict[str, str]
    __default_auth: typing.Optional[HttpRequestDecorator]
    __default_endpoint: typing.Optional[str]

    def __init__(
        self,
        base_headers: typing.Optional[dict[str, str]] = None,
        default_endpoint: typing.Optional[str] = None,
        default_auth: typing.Optional[HttpRequestDecorator] = None,
        requester: typing.Optional[RobotoRequester] = None,
    ):
        self.__base_headers = base_headers if base_headers is not None else {}

        if requester is not None:
            self.set_requester(requester)

        self.__default_auth = default_auth
        self.__default_endpoint = default_endpoint

    def delete(
        self,
        url: str,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        request = HttpRequest(
            url=url,
            method="DELETE",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        return self.__request(request)

    def get(
        self,
        url: str,
        headers: typing.Optional[dict] = None,
        retry_wait: typing.Optional[RetryWaitFn] = None,
        idempotent: bool = True,
    ) -> HttpResponse:
        request = HttpRequest(
            url=url,
            method="GET",
            headers=headers,
            retry_wait=retry_wait,
            idempotent=idempotent,
        )
        return self.__request(request)

    def post(
        self,
        url,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = False,
        retry_wait: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        request = HttpRequest(
            url=url,
            method="POST",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        return self.__request(request)

    def patch(
        self,
        url,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        request = HttpRequest(
            url=url,
            method="PATCH",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        return self.__request(request)

    def put(
        self,
        url,
        data: typing.Any = None,
        headers: typing.Optional[dict] = None,
        idempotent: bool = True,
        retry_wait: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        request = HttpRequest(
            url=url,
            method="PUT",
            data=data,
            headers=headers,
            idempotent=idempotent,
            retry_wait=retry_wait,
        )
        return self.__request(request)

    def set_requester(self, requester: RobotoRequester):
        self.__base_headers[ROBOTO_REQUESTER_HEADER] = requester.model_dump_json(
            exclude_none=True
        )

    def url(self, path: str) -> str:
        if self.__default_endpoint is None:
            raise ValueError(
                "HttpClient.url called for client with no default endpoint."
            )
        return f"{self.__default_endpoint}/{path}"

    @property
    def auth_decorator(self) -> typing.Optional[HttpRequestDecorator]:
        return self.__default_auth

    def __request_headers(self, request_ctx: HttpRequest) -> dict[str, str]:
        headers = self.__base_headers.copy()

        if request_ctx.headers:
            headers.update(request_ctx.headers)

        return headers

    def __request(self, request_ctx: HttpRequest) -> HttpResponse:
        if self.__default_auth is not None:
            request_ctx = self.__default_auth(request_ctx)

        logger.debug("%s", request_ctx)

        headers = self.__request_headers(request_ctx)

        try:
            for attempt in tenacity.Retrying(
                retry=tenacity.retry_if_exception(
                    is_expected_to_be_transient(request_ctx)
                ),
                stop=tenacity.stop_after_attempt(10),
                reraise=True,
                wait=self._wait(request_ctx.retry_wait),
            ):
                with attempt:
                    request = urllib.request.Request(
                        request_ctx.url, method=request_ctx.method
                    )

                    req_body = request_ctx.body
                    if req_body is not None:
                        request.data = req_body

                    for key, value in headers.items():
                        request.add_header(key, value)

                    response = HttpResponse(urllib.request.urlopen(request))
                    logger.debug("Response: %s %s", response.status, response.headers)
                    return response
        except urllib.error.HTTPError as exc:
            logger.debug("HTTPError: %s", exc, exc_info=True)
            status_code = exc.code
            if status_code > 399 and status_code < 500:
                raise ClientError(exc) from None
            elif status_code > 499:
                raise ServerError(exc) from None
            else:
                raise HttpError(exc) from None
        except urllib.error.URLError as exc:
            logger.debug("URLError: %s", exc, exc_info=True)
            if (
                isinstance(exc.reason, OSError)
                and exc.reason.errno == errno.ECONNREFUSED
            ):
                raise ConnectionRefusedError(
                    f"Couldn't connect to endpoint {request_ctx.url}"
                ) from None
            else:
                raise
        except Exception:
            logger.debug("Catchall Exception", exc_info=True)
            raise

        raise RuntimeError("Unreachable")

    def _wait(self, waiter: RetryWaitFn) -> tenacity.wait.wait_base:
        class Waiter(tenacity.wait.wait_base):
            def __call__(self, retry_state: tenacity.RetryCallState) -> float:
                return waiter(retry_state, None) / 1000

        return Waiter()
