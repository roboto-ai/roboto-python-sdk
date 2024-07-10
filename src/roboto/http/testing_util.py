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

from .http_client import HttpResponse


class FakeHttpResponseFactory:
    """
    A factory for creating fake HTTP responses, for use with the roboto.http.HttpClient.

    Example:
        >>> import contextlib
        >>> import unittest.mock
        >>> from roboto.http import HttpClient, FakeHttpResponseFactory
        >>> mock_http_client = unittest.mock.create_autospec(HttpClient, instance=True)
        >>> with contextlib.ExitStack() as stack:
        ...     http_get_mock = stack.enter_context(
        ...         unittest.mock.patch.object(mock_http_client, "get")
        ...     )
        ...     http_get_mock.side_effect = FakeHttpResponseFactory(
        ...         "https://example.com",
        ...         {"foo": "bar"},
        ...         status_code=200,
        ...         headers={"Content-Type": "application/json"},
        ...     )

    """

    __headers: dict[str, str]
    __response_data: typing.Any
    __status_code: int
    __url: str

    def __init__(
        self,
        url: str = "https://iamverylazyanddonotseturls.com",
        response_data: typing.Any = "{}",
        status_code: int = 200,
        headers: typing.Optional[dict[str, str]] = None,
    ) -> None:
        self.__status_code = status_code
        self.__headers = headers or dict()
        self.__response_data = response_data
        self.__url = url

    def __call__(self, *args, **kwargs) -> HttpResponse:
        headers = email.message.Message()
        for k, v in self.__headers.items():
            headers.add_header(k, v)
        data = io.BytesIO(json.dumps(self.__response_data).encode())
        urllib_response = urllib.response.addinfourl(
            data, headers, self.__url, self.__status_code
        )
        return HttpResponse(urllib_response)
