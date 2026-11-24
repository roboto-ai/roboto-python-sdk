# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import http
import json
import typing
import urllib.error


class HttpError(Exception):
    """Base class of the exceptions the SDK raises when an HTTP response has an error status.

    The request methods of :py:class:`~roboto.http.HttpClient` (``get``, ``post``, ``put``, ``patch`` and ``delete``)
    raise ``ClientError`` for a 4xx status, ``ServerError`` for a status of 500 or above, and this class for any other
    error status, once their retries are spent. You do not construct it directly.

    :py:class:`~roboto.http.RobotoClient`, which the SDK's domain classes use, converts one with status 400, 401, 403,
    404, 409 or 5xx into the matching :py:class:`~roboto.exceptions.RobotoDomainException`, as
    :py:meth:`~roboto.exceptions.RobotoDomainException.from_client_error` describes. Any other standard error status,
    such as 429, reaches its callers as this exception unchanged.
    """

    __http_exc: urllib.error.HTTPError
    __msg: typing.Any = None
    __status: typing.Optional[http.HTTPStatus] = None

    def __init__(self, exc: urllib.error.HTTPError) -> None:
        super().__init__()
        self.__http_exc = exc

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.msg!r}, {self.status!r})"

    def __str__(self) -> str:
        return f"{self.msg!r}"

    @property
    def status(self) -> typing.Optional[http.HTTPStatus]:
        """HTTP status of the response, or ``None`` if ``http.HTTPStatus`` defines no member for its code."""
        if self.__status is None:
            try:
                self.__status = http.HTTPStatus(int(self.__http_exc.code))
            except ValueError:
                self.__status = None
        return self.__status

    @property
    def msg(self) -> typing.Any:
        """Body of the response, decoded as UTF-8 and parsed as JSON, or the decoded text when it is not JSON.

        A body that is not valid UTF-8 raises ``UnicodeDecodeError`` when this is read.
        """
        if self.__msg is None:
            decoded = self.__http_exc.read().decode("utf-8")
            try:
                self.__msg = json.loads(decoded)
            except json.JSONDecodeError:
                self.__msg = decoded
        return self.__msg

    @property
    def headers(self) -> dict:
        """Headers of the response. A header sent more than once keeps its last value."""
        return dict(self.__http_exc.headers.items())


class ClientError(HttpError):
    """The server rejected the request and responded with a 4xx status.

    Raised by the request methods of :py:class:`~roboto.http.HttpClient`. ``HttpError`` says which statuses
    :py:class:`~roboto.http.RobotoClient` converts into Roboto exceptions instead.
    """


class ServerError(HttpError):
    """The server failed to handle the request and responded with a status of 500 or above.

    Raised by the request methods of :py:class:`~roboto.http.HttpClient`. ``HttpError`` says which statuses
    :py:class:`~roboto.http.RobotoClient` converts into Roboto exceptions instead.
    """
