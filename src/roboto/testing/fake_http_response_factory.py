# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import email.message
import io
import json
import typing
import urllib.response

from ..http.http_client import HttpResponse


class FakeHttpResponseFactory:
    """Builder of fake HTTP responses, for tests that mock :py:class:`~roboto.http.HttpClient`.

    Calling an instance ignores the call's arguments and builds a new
    :py:class:`~roboto.http.response.HttpResponse` from the constructor's arguments, with its body not yet read. Set an
    instance as the ``side_effect`` of a mocked request method, as in
    ``http_client.get.side_effect = FakeHttpResponseFactory(url, {"foo": "bar"})``, and every call of that method
    returns such a response. The response is returned whatever its status: nothing raises the
    :py:class:`~roboto.exceptions.ClientError` or :py:class:`~roboto.exceptions.ServerError` that ``HttpClient`` raises
    for an error status.

    Args:
        url: URL the response reports it came from.
        response_data: Value the response body holds, encoded with ``json.dumps``. Defaults to the string ``"{}"``,
            which the body holds as a JSON string, not an empty object.
        status_code: HTTP status code of the response.
        headers: Headers of the response. ``None`` gives it none.
    """

    __headers: dict[str, str]
    __response_data: typing.Any
    __status_code: int
    __url: str

    def __init__(
        self,
        url: str = "https://test.roboto.ai",
        response_data: typing.Any = "{}",
        status_code: int = 200,
        headers: typing.Optional[dict[str, str]] = None,
    ) -> None:
        self.__status_code = status_code
        self.__headers = headers or dict()
        self.__response_data = response_data
        self.__url = url

    def __call__(self, *args, **kwargs) -> HttpResponse:
        """Build a new response from the constructor's arguments.

        Args:
            *args: Ignored.
            **kwargs: Ignored.
        """
        headers = email.message.Message()
        for k, v in self.__headers.items():
            headers.add_header(k, v)
        data = io.BytesIO(json.dumps(self.__response_data).encode())
        urllib_response = urllib.response.addinfourl(data, headers, self.__url, self.__status_code)
        return HttpResponse(urllib_response)
