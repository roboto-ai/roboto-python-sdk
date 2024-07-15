# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
import urllib.parse


class UrlBuilder:
    __endpoint: str

    def __init__(self, endpoint: str):
        self.__endpoint = endpoint.rstrip("/")

    def build(self, path: str, query: typing.Optional[dict[str, typing.Any]] = None):
        return UrlBuilder.url(endpoint=self.__endpoint, path=path, query=query)

    @staticmethod
    def url(
        endpoint: str, path: str, query: typing.Optional[dict[str, typing.Any]] = None
    ) -> str:
        normalized_path = path.lstrip("/")

        if query is None:
            return f"{endpoint}/{normalized_path}"
        else:
            return f"{endpoint}/{normalized_path}?{urllib.parse.urlencode(query)}"
