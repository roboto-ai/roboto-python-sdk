# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
import urllib.parse


class UrlBuilder:
    """Builder of URLs under one endpoint, from a path and an optional query string.

    Args:
        endpoint: Base URL every built URL starts with, such as ``https://api.roboto.ai``. Trailing slashes are removed.
    """

    __endpoint: str

    def __init__(self, endpoint: str):
        self.__endpoint = endpoint.rstrip("/")

    def build(self, path: str, query: typing.Optional[dict[str, typing.Any]] = None):
        """Build the URL of ``path`` under this builder's endpoint, with ``query`` as its query string.

        Args:
            path: Path to append to the endpoint, joined with one ``/``. Leading slashes are removed, so
                ``"/v1/datasets"`` and ``"v1/datasets"`` give the same URL.
            query: Query parameters, encoded with ``urllib.parse.urlencode``. Each value is converted with
                ``str()``, so a list is sent as one parameter, not one per item. ``None`` adds no query string; an
                empty dictionary leaves a bare ``?`` at the end of the URL.

        Examples:
            >>> UrlBuilder("https://api.roboto.ai/").build("/v1/datasets/ds_12345", query={"limit": 10})
            'https://api.roboto.ai/v1/datasets/ds_12345?limit=10'
        """
        return UrlBuilder.url(endpoint=self.__endpoint, path=path, query=query)

    @staticmethod
    def url(endpoint: str, path: str, query: typing.Optional[dict[str, typing.Any]] = None) -> str:
        """Build the URL of ``path`` under ``endpoint``, with ``query`` as its query string.

        Args:
            endpoint: Base URL to start from, used as given: an endpoint that ends in ``/`` gives a URL with ``//``
                before the path.
            path: Path to append to the endpoint, with leading slashes removed as in ``build``.
            query: Query parameters, encoded as in ``build``.
        """
        normalized_path = path.lstrip("/")

        if query is None:
            return f"{endpoint}/{normalized_path}"
        else:
            return f"{endpoint}/{normalized_path}?{urllib.parse.urlencode(query)}"
