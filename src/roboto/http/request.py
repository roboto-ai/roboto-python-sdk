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

ALWAYS_SCRUBBED_HEADERS = frozenset({"authorization"})
"""Header names, lowercase, whose values are always scrubbed from rendered requests."""


class HttpRequest:
    url: str
    method: str
    headers: dict
    retry_wait: RetryWaitFn
    data: typing.Any = None
    idempotent: bool = False

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

    def describe(self, scrub_headers: typing.Collection[str] = ()) -> str:
        """Render the request for logging, with sensitive header values replaced by ``*``.

        Args:
            scrub_headers: Header names, compared case-insensitively, to scrub in addition to
                :py:data:`ALWAYS_SCRUBBED_HEADERS`.
        """
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
        parsed_url = urllib.parse.urlparse(self.url)
        return parsed_url.hostname if parsed_url.hostname is not None else parsed_url.netloc

    def append_headers(self, headers: dict[str, str]) -> None:
        self.headers.update(headers)


HttpRequestDecorator = typing.Callable[[HttpRequest], HttpRequest]


class BatchRequest(pydantic.BaseModel, typing.Generic[Model]):
    """Batched HTTP requests"""

    requests: list[Model]
