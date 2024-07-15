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
        if self.__status is None:
            try:
                self.__status = http.HTTPStatus(int(self.__http_exc.code))
            except ValueError:
                self.__status = None
        return self.__status

    @property
    def msg(self) -> typing.Any:
        if self.__msg is None:
            decoded = self.__http_exc.read().decode("utf-8")
            try:
                self.__msg = json.loads(decoded)
            except json.JSONDecodeError:
                self.__msg = decoded
        return self.__msg

    @property
    def headers(self) -> dict:
        return dict(self.__http_exc.headers.items())


class ClientError(HttpError):
    pass


class ServerError(HttpError):
    pass
