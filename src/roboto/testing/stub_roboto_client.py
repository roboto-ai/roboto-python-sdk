# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import email.message
import io
import json
import typing
import urllib.response

import pydantic

from roboto.http import RobotoClient
from roboto.http.response import HttpResponse

# Type alias for the response
StubResponse = typing.Union[
    dict[str, typing.Any],
    list[typing.Any],
    str,
    int,
    float,
    bool,
    None,
    pydantic.BaseModel,
    Exception,
]

RequestBodyMatcher = typing.Callable[[typing.Any], bool]


@dataclasses.dataclass
class _Expectation:
    """Internal representation of an expected request/response pair."""

    method: str
    path: str
    response: StubResponse
    query: typing.Optional[dict[str, typing.Any]] = None
    request_body_matcher: typing.Optional[RequestBodyMatcher] = None


class StubRobotoClient(RobotoClient):
    """
    A stub RobotoClient for unit testing that returns pre-configured responses for expected requests.

    Example:
        >>> from roboto_test_utils import StubRobotoClient
        >>> from roboto.domain.datasets import Dataset, DatasetRecord
        >>> from roboto.time import utcnow
        >>>
        >>> client = StubRobotoClient()
        >>> client.expect_get(
        ...     "/v1/datasets/ds_123",
        ...     response=DatasetRecord(
        ...         dataset_id="ds_123",
        ...         created=utcnow(),
        ...         created_by="test@example.com",
        ...         modified=utcnow(),
        ...         modified_by="test@example.com",
        ...         org_id="og_test",
        ...     ),
        ... )
        >>>
        >>> dataset = Dataset.from_id("ds_123", roboto_client=client)
        >>> assert dataset.dataset_id == "ds_123"
    """

    __expectations: list[_Expectation]

    def __init__(self) -> None:
        super().__init__(endpoint="https://stub.roboto.test", auth_decorator=None)
        self.__expectations = []

    def __enter__(self) -> StubRobotoClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.verify_no_pending_expectations()

    def expect_get(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
    ) -> StubRobotoClient:
        self.__expectations.append(_Expectation("GET", path, response, query))
        return self

    def expect_post(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
    ) -> StubRobotoClient:
        self.__expectations.append(_Expectation("POST", path, response, query, request_body_matcher))
        return self

    def expect_put(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
    ) -> StubRobotoClient:
        self.__expectations.append(_Expectation("PUT", path, response, query, request_body_matcher))
        return self

    def expect_patch(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
    ) -> StubRobotoClient:
        self.__expectations.append(_Expectation("PATCH", path, response, query, request_body_matcher))
        return self

    def expect_delete(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
    ) -> StubRobotoClient:
        self.__expectations.append(_Expectation("DELETE", path, response, query, request_body_matcher))
        return self

    # Override HTTP methods to use expectations
    def get(
        self,
        path: collections.abc.Sequence[str] | str,
        caller_org_id: typing.Optional[str] = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[typing.Any] = None,
        timeout: typing.Any = None,
    ) -> HttpResponse:
        return self.__consume_expectation("GET", path, query, None)

    def post(
        self,
        path: collections.abc.Sequence[str] | str,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[typing.Any] = None,
        timeout: typing.Any = None,
    ) -> HttpResponse:
        return self.__consume_expectation("POST", path, query, data)

    def put(
        self,
        path: collections.abc.Sequence[str] | str,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[typing.Any] = None,
        timeout: typing.Any = None,
    ) -> HttpResponse:
        return self.__consume_expectation("PUT", path, query, data)

    def patch(
        self,
        path: collections.abc.Sequence[str] | str,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[typing.Any] = None,
        timeout: typing.Any = None,
    ) -> HttpResponse:
        return self.__consume_expectation("PATCH", path, query, data)

    def delete(
        self,
        path: collections.abc.Sequence[str] | str,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[typing.Any] = None,
        timeout: typing.Any = None,
    ) -> HttpResponse:
        return self.__consume_expectation("DELETE", path, query, data)

    def verify_no_pending_expectations(self) -> None:
        """
        Verify that all registered expectations have been consumed.

        Raises:
            AssertionError: If there are any pending expectations that were not consumed.
        """
        if self.__expectations:
            pending = [(e.method, e.path) for e in self.__expectations]
            raise AssertionError(f"Pending expectations were not consumed: {pending}")

    def __consume_expectation(
        self,
        method: str,
        path: collections.abc.Sequence[str] | str,
        query: typing.Optional[dict[str, typing.Any]],
        body: typing.Any,
    ) -> HttpResponse:
        """Find and consume a matching expectation, returning its response."""
        normalized_path = self.__normalize_path(path)

        for i, expectation in enumerate(self.__expectations):
            if expectation.method != method:
                continue
            if self.__normalize_path(expectation.path) != normalized_path:
                continue
            if expectation.query is not None and expectation.query != query:
                continue
            if expectation.request_body_matcher and not expectation.request_body_matcher(body):
                continue

            # Found a match - consume it
            self.__expectations.pop(i)

            # If response is an exception, raise it
            if isinstance(expectation.response, Exception):
                raise expectation.response

            return self.__build_response(expectation.response)

        raise AssertionError(
            f"Unexpected request: {method} {normalized_path}\n"
            f"Query: {query}\n"
            f"Body: {body}\n"
            f"Pending expectations: {[(e.method, e.path) for e in self.__expectations]}"
        )

    def __normalize_path(self, path: typing.Union[str, collections.abc.Iterable[str]]) -> str:
        """Normalize path to a string with leading slash."""
        if isinstance(path, str):
            normalized = path
        else:
            normalized = "/".join(path)
        return f"/{normalized.lstrip('/')}"

    def __build_response(self, response: StubResponse) -> HttpResponse:
        """Build an HttpResponse from the stub response data."""
        # Serialize pydantic models
        response_data: typing.Any
        if isinstance(response, pydantic.BaseModel):
            response_data = response.model_dump(mode="json")
        else:
            response_data = response

        # Wrap in {"data": ...}
        wrapped: dict[str, typing.Any] = {"data": response_data}

        # Build the HttpResponse
        headers = email.message.Message()
        headers.add_header("Content-Type", "application/json")
        data = io.BytesIO(json.dumps(wrapped).encode())
        urllib_response = urllib.response.addinfourl(data, headers, "https://stub.roboto.test", 200)
        return HttpResponse(urllib_response)
