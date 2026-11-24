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
"""Response a ``StubRobotoClient`` expectation answers a request with.

A pydantic model is returned in its JSON form and any other value as is, each as the ``data`` field of the response
body. An exception is raised instead of returning a response.
"""

RequestBodyMatcher = typing.Callable[[typing.Any], bool]
"""Function that takes a request's body, and returns whether the request matches an expectation.

See the ``request_body_matcher`` argument of ``StubRobotoClient.expect_post``.
"""


@dataclasses.dataclass
class _Expectation:
    """Request a test expects, and the response to answer it with. A condition left ``None`` matches any value."""

    method: str
    path: str
    response: StubResponse
    query: typing.Optional[dict[str, typing.Any]] = None
    request_body_matcher: typing.Optional[RequestBodyMatcher] = None
    owner_org_id: typing.Optional[str] = None
    caller_org_id: typing.Optional[str] = None

    def describe(self) -> str:
        parts = [self.method, self.path]
        if self.caller_org_id is not None:
            parts.append(f"caller_org_id={self.caller_org_id}")
        if self.owner_org_id is not None:
            parts.append(f"owner_org_id={self.owner_org_id}")
        return " ".join(parts)


class StubRobotoClient(RobotoClient):
    """Client that answers SDK requests with responses a test registers, in place of Roboto.

    Pass it as the ``roboto_client`` of the SDK methods under test; it sends nothing over the network. Register each
    request you expect, and the response to answer it with, by calling ``expect_get``, ``expect_post``, ``expect_put``,
    ``expect_patch`` or ``expect_delete``. Each request the client receives then:

    - takes the first registered expectation that matches it, which no later request can match again;
    - raises ``AssertionError`` when none matches, naming the request and the expectations still pending.

    An expectation matches a request with the same method and path that also meets each condition the expectation
    sets: the same ``query``, ``caller_org_id`` or ``owner_org_id``, and a body its ``request_body_matcher`` accepts.

    Used as a context manager, the client calls ``verify_no_pending_expectations`` when the ``with`` block ends, unless
    the block raised.
    """

    __expectations: list[_Expectation]

    def __init__(self) -> None:
        super().__init__(endpoint="https://stub.roboto.test", auth_decorator=None)
        self.__expectations = []

    def __enter__(self) -> StubRobotoClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # When the block raised (for example, on an unexpected request), skip the check so the test reports that
        # error instead of the pending expectations it left behind.
        if exc_type is None:
            self.verify_no_pending_expectations()

    def expect_get(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        owner_org_id: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> StubRobotoClient:
        """Register an expected GET request and the response to answer it with.

        Args:
            path: Route the request is sent to, such as ``"v1/datasets/ds_12345"``. A leading ``/`` is optional.
            response: Value to return as the ``data`` field of the response body, or an exception to raise instead.
                A pydantic model is returned in its JSON form.
            query: Query parameters the request must pass, compared as a whole dictionary. ``None`` matches any.
            owner_org_id: Organization ID the request must pass as ``owner_org_id``. ``None`` matches any, including
                none.
            caller_org_id: Organization ID the request must pass as ``caller_org_id``. ``None`` matches any,
                including none.

        Returns:
            This client, so that calls can be chained.

        Examples:
            Answer the request :py:meth:`~roboto.domain.datasets.Dataset.from_id` sends:

            >>> from roboto.domain.datasets import Dataset, DatasetRecord
            >>> from roboto.testing import StubRobotoClient
            >>> from roboto.time import utcnow
            >>> record = DatasetRecord(
            ...     dataset_id="ds_12345",
            ...     created=utcnow(),
            ...     created_by="user:test@example.com",
            ...     modified=utcnow(),
            ...     modified_by="user:test@example.com",
            ...     org_id="og_12345",
            ... )
            >>> client = StubRobotoClient().expect_get("v1/datasets/ds_12345", response=record)
            >>> with client:
            ...     dataset = Dataset.from_id("ds_12345", roboto_client=client)
            >>> dataset.dataset_id
            'ds_12345'
        """
        self.__expectations.append(
            _Expectation("GET", path, response, query, owner_org_id=owner_org_id, caller_org_id=caller_org_id)
        )
        return self

    def expect_post(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> StubRobotoClient:
        """Register an expected POST request and the response to answer it with.

        Args:
            path: Route the request is sent to, such as ``"v1/datasets"``. A leading ``/`` is optional.
            response: Value to return as the ``data`` field of the response body, or an exception to raise instead.
                A pydantic model is returned in its JSON form.
            query: Query parameters the request must pass, compared as a whole dictionary. ``None`` matches any.
            request_body_matcher: Function called with the request's body, as the SDK method passed it (such as a
                pydantic request model), that returns whether the request matches. ``None`` matches any body.
            caller_org_id: Organization ID the request must pass as ``caller_org_id``. ``None`` matches any,
                including none.

        Returns:
            This client, so that calls can be chained.
        """
        self.__expectations.append(
            _Expectation("POST", path, response, query, request_body_matcher, caller_org_id=caller_org_id)
        )
        return self

    def expect_put(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> StubRobotoClient:
        """Register an expected PUT request and the response to answer it with.

        Args:
            path: Route the request is sent to, such as ``"v1/datasets"``. A leading ``/`` is optional.
            response: Value to return as the ``data`` field of the response body, or an exception to raise instead.
                A pydantic model is returned in its JSON form.
            query: Query parameters the request must pass, compared as a whole dictionary. ``None`` matches any.
            request_body_matcher: Function called with the request's body, as the SDK method passed it (such as a
                pydantic request model), that returns whether the request matches. ``None`` matches any body.
            caller_org_id: Organization ID the request must pass as ``caller_org_id``. ``None`` matches any,
                including none.

        Returns:
            This client, so that calls can be chained.
        """
        self.__expectations.append(
            _Expectation("PUT", path, response, query, request_body_matcher, caller_org_id=caller_org_id)
        )
        return self

    def expect_patch(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> StubRobotoClient:
        """Register an expected PATCH request and the response to answer it with.

        Args:
            path: Route the request is sent to, such as ``"v1/datasets"``. A leading ``/`` is optional.
            response: Value to return as the ``data`` field of the response body, or an exception to raise instead.
                A pydantic model is returned in its JSON form.
            query: Query parameters the request must pass, compared as a whole dictionary. ``None`` matches any.
            request_body_matcher: Function called with the request's body, as the SDK method passed it (such as a
                pydantic request model), that returns whether the request matches. ``None`` matches any body.
            caller_org_id: Organization ID the request must pass as ``caller_org_id``. ``None`` matches any,
                including none.

        Returns:
            This client, so that calls can be chained.
        """
        self.__expectations.append(
            _Expectation("PATCH", path, response, query, request_body_matcher, caller_org_id=caller_org_id)
        )
        return self

    def expect_delete(
        self,
        path: str,
        response: StubResponse,
        query: typing.Optional[dict[str, typing.Any]] = None,
        request_body_matcher: typing.Optional[RequestBodyMatcher] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> StubRobotoClient:
        """Register an expected DELETE request and the response to answer it with.

        Args:
            path: Route the request is sent to, such as ``"v1/datasets"``. A leading ``/`` is optional.
            response: Value to return as the ``data`` field of the response body, or an exception to raise instead.
                A pydantic model is returned in its JSON form.
            query: Query parameters the request must pass, compared as a whole dictionary. ``None`` matches any.
            request_body_matcher: Function called with the request's body, as the SDK method passed it (such as a
                pydantic request model), that returns whether the request matches. ``None`` matches any body.
            caller_org_id: Organization ID the request must pass as ``caller_org_id``. ``None`` matches any,
                including none.

        Returns:
            This client, so that calls can be chained.
        """
        self.__expectations.append(
            _Expectation("DELETE", path, response, query, request_body_matcher, caller_org_id=caller_org_id)
        )
        return self

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
        """Answer a GET request from the first registered expectation that matches it, without sending it.

        The SDK's own code uses it; to choose the response to a GET request, use ``expect_get`` instead.

        Args:
            path: Route of the request, as a string or as segments joined with ``/``.
            caller_org_id: Organization ID matched against each expectation's ``caller_org_id``.
            headers: Ignored.
            idempotent: Ignored.
            owner_org_id: Organization ID matched against each expectation's ``owner_org_id``.
            query: Query parameters matched against each expectation's ``query``.
            retry_wait_fn: Ignored.
            timeout: Ignored.

        Returns:
            Response with status 200 whose JSON body holds the expectation's response in its ``data`` field.

        Raises:
            AssertionError: No pending expectation matches the request.
            Exception: The response registered for the matching expectation, when it is an exception.
        """
        return self.__consume_expectation(
            "GET", path, query, None, owner_org_id=owner_org_id, caller_org_id=caller_org_id
        )

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
        """Answer a POST request from the first registered expectation that matches it, without sending it.

        The SDK's own code uses it; to choose the response to a POST request, use ``expect_post`` instead.

        Args:
            path: Route of the request, as a string or as segments joined with ``/``.
            caller_org_id: Organization ID matched against each expectation's ``caller_org_id``.
            data: Request body, passed to each expectation's ``request_body_matcher``.
            headers: Ignored.
            idempotent: Ignored.
            owner_org_id: Organization ID matched against each expectation's ``owner_org_id``.
            query: Query parameters matched against each expectation's ``query``.
            retry_wait_fn: Ignored.
            timeout: Ignored.

        Returns:
            Response with status 200 whose JSON body holds the expectation's response in its ``data`` field.

        Raises:
            AssertionError: No pending expectation matches the request.
            Exception: The response registered for the matching expectation, when it is an exception.
        """
        return self.__consume_expectation(
            "POST", path, query, data, owner_org_id=owner_org_id, caller_org_id=caller_org_id
        )

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
        """Answer a PUT request from the first registered expectation that matches it, without sending it.

        The SDK's own code uses it; to choose the response to a PUT request, use ``expect_put`` instead.

        Args:
            path: Route of the request, as a string or as segments joined with ``/``.
            caller_org_id: Organization ID matched against each expectation's ``caller_org_id``.
            data: Request body, passed to each expectation's ``request_body_matcher``.
            headers: Ignored.
            idempotent: Ignored.
            owner_org_id: Organization ID matched against each expectation's ``owner_org_id``.
            query: Query parameters matched against each expectation's ``query``.
            retry_wait_fn: Ignored.
            timeout: Ignored.

        Returns:
            Response with status 200 whose JSON body holds the expectation's response in its ``data`` field.

        Raises:
            AssertionError: No pending expectation matches the request.
            Exception: The response registered for the matching expectation, when it is an exception.
        """
        return self.__consume_expectation(
            "PUT", path, query, data, owner_org_id=owner_org_id, caller_org_id=caller_org_id
        )

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
        """Answer a PATCH request from the first registered expectation that matches it, without sending it.

        The SDK's own code uses it; to choose the response to a PATCH request, use ``expect_patch`` instead.

        Args:
            path: Route of the request, as a string or as segments joined with ``/``.
            caller_org_id: Organization ID matched against each expectation's ``caller_org_id``.
            data: Request body, passed to each expectation's ``request_body_matcher``.
            headers: Ignored.
            idempotent: Ignored.
            owner_org_id: Organization ID matched against each expectation's ``owner_org_id``.
            query: Query parameters matched against each expectation's ``query``.
            retry_wait_fn: Ignored.
            timeout: Ignored.

        Returns:
            Response with status 200 whose JSON body holds the expectation's response in its ``data`` field.

        Raises:
            AssertionError: No pending expectation matches the request.
            Exception: The response registered for the matching expectation, when it is an exception.
        """
        return self.__consume_expectation(
            "PATCH", path, query, data, owner_org_id=owner_org_id, caller_org_id=caller_org_id
        )

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
        """Answer a DELETE request from the first registered expectation that matches it, without sending it.

        The SDK's own code uses it; to choose the response to a DELETE request, use ``expect_delete`` instead.

        Args:
            path: Route of the request, as a string or as segments joined with ``/``.
            caller_org_id: Organization ID matched against each expectation's ``caller_org_id``.
            data: Request body, passed to each expectation's ``request_body_matcher``.
            headers: Ignored.
            idempotent: Ignored.
            owner_org_id: Organization ID matched against each expectation's ``owner_org_id``.
            query: Query parameters matched against each expectation's ``query``.
            retry_wait_fn: Ignored.
            timeout: Ignored.

        Returns:
            Response with status 200 whose JSON body holds the expectation's response in its ``data`` field.

        Raises:
            AssertionError: No pending expectation matches the request.
            Exception: The response registered for the matching expectation, when it is an exception.
        """
        return self.__consume_expectation(
            "DELETE", path, query, data, owner_org_id=owner_org_id, caller_org_id=caller_org_id
        )

    def verify_no_pending_expectations(self) -> None:
        """Check that every registered expectation has answered a request.

        Raises:
            AssertionError: An expectation has answered no request. The message lists each such expectation's method
                and path.
        """
        if self.__expectations:
            pending = [e.describe() for e in self.__expectations]
            raise AssertionError(f"Pending expectations were not consumed: {pending}")

    def __consume_expectation(
        self,
        method: str,
        path: collections.abc.Sequence[str] | str,
        query: typing.Optional[dict[str, typing.Any]],
        body: typing.Any,
        owner_org_id: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> HttpResponse:
        """Answer a request from the first matching expectation, and remove that expectation."""
        normalized_path = self.__normalize_path(path)

        for i, expectation in enumerate(self.__expectations):
            if expectation.method != method:
                continue
            if self.__normalize_path(expectation.path) != normalized_path:
                continue
            if expectation.query is not None and expectation.query != query:
                continue
            if expectation.owner_org_id is not None and expectation.owner_org_id != owner_org_id:
                continue
            if expectation.caller_org_id is not None and expectation.caller_org_id != caller_org_id:
                continue
            if expectation.request_body_matcher and not expectation.request_body_matcher(body):
                continue

            self.__expectations.pop(i)
            if isinstance(expectation.response, Exception):
                raise expectation.response

            return self.__build_response(expectation.response)

        raise AssertionError(
            f"Unexpected request: {method} {normalized_path}\n"
            f"Caller org: {caller_org_id}, owner org: {owner_org_id}\n"
            f"Query: {query}\n"
            f"Body: {body}\n"
            f"Pending expectations: {[e.describe() for e in self.__expectations]}"
        )

    def __normalize_path(self, path: typing.Union[str, collections.abc.Iterable[str]]) -> str:
        """Join a path given as segments with ``/`` and give it one leading ``/``, so equivalent paths compare equal."""
        if isinstance(path, str):
            normalized = path
        else:
            normalized = "/".join(path)
        return f"/{normalized.lstrip('/')}"

    def __build_response(self, response: StubResponse) -> HttpResponse:
        """Build a status 200 JSON response whose body is ``{"data": <response>}``."""
        response_data: typing.Any
        if isinstance(response, pydantic.BaseModel):
            response_data = response.model_dump(mode="json")
        else:
            response_data = response

        # SDK methods read their result from the data field of Roboto's response body.
        wrapped: dict[str, typing.Any] = {"data": response_data}

        headers = email.message.Message()
        headers.add_header("Content-Type", "application/json")
        data = io.BytesIO(json.dumps(wrapped).encode())
        urllib_response = urllib.response.addinfourl(data, headers, "https://stub.roboto.test", 200)
        return HttpResponse(urllib_response)
