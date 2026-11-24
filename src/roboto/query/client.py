# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import math
import typing

from ..config import RobotoConfig
from ..http import RobotoClient
from ..waiters import wait_for
from .api import (
    QueryContentMode,
    QueryRecord,
    QueryStatus,
    QueryTarget,
    SubmitRoboqlQueryRequest,
    SubmitStructuredQueryRequest,
    SubmitTermQueryRequest,
)
from .specification import QuerySpecification

RoboQLQuery: typing.TypeAlias = str
"""Query written in RoboQL, such as ``"tags CONTAINS 'warehouse'"``."""

Query: typing.TypeAlias = typing.Union[RoboQLQuery, QuerySpecification]
"""Query of either form: a RoboQL string or a :py:class:`~roboto.query.QuerySpecification`."""


class QueryClient:
    """Client that submits queries to Roboto and yields each result as a dictionary.

    :py:class:`~roboto.roboto_search.RobotoSearch` runs the same queries and yields SDK objects, such as
    :py:class:`~roboto.domain.datasets.Dataset`, in place of dictionaries.

    Each method that submits a query and yields its results submits it when iteration begins, not when the method is
    called, and then checks every 2 seconds until the results are available.

    Args:
        roboto_client: Client to make requests to Roboto with. Defaults to one built from
            :py:meth:`~roboto.config.RobotoConfig.from_env` with ``roboto_profile``.
        owner_org_id: Organization to run and read queries in when a method names none. ``None`` leaves it to the
            organization the caller acts in.
        roboto_profile: Config file profile to build the default ``roboto_client`` from. Ignored when
            ``roboto_client`` is given or the environment holds an access token.

    Raises:
        FileNotFoundError: ``roboto_client`` is not given, no access token is set, and the config file does not exist.
        OSError: ``roboto_client`` is not given and the config file exists but cannot be read.
        ValueError: ``roboto_client`` is not given and the config file is not a JSON object, holds no valid profile,
            or has no profile by the chosen name.
        RobotoDeprecatedException: ``roboto_client`` is not given and the access token begins with ``robo_pat``, a
            format Roboto retired in March 2024.
    """

    __owner_org_id: typing.Optional[str] = None
    __roboto_client: RobotoClient

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_profile: typing.Optional[str] = None,
    ):
        self.__owner_org_id = owner_org_id

        if roboto_client is None:
            roboto_config = RobotoConfig.from_env(profile_override=roboto_profile)
            roboto_client = RobotoClient.from_config(roboto_config)

        self.__roboto_client = roboto_client

    @property
    def roboto_client(self) -> RobotoClient:
        """Client this query client makes requests to Roboto with."""
        return self.__roboto_client

    def are_query_results_available(self, query_id: str, owner_org_id: typing.Optional[str] = None) -> bool:
        """Fetch whether a query has finished and its results can be read.

        Returns ``False`` both while the query is scheduled and after it fails. To tell those apart, read
        :py:attr:`~roboto.query.QueryRecord.status` from ``get_query_record``.

        Args:
            query_id: ID of the query.
            owner_org_id: Organization that owns the query. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Raises:
            RobotoNotFoundException: No query has this ID.
        """
        return self.get_query_record(query_id, owner_org_id).status == QueryStatus.ResultsAvailable

    def get_query_record(self, query_id: str, owner_org_id: typing.Optional[str] = None) -> QueryRecord:
        """Fetch a query's record, which holds its status and result count.

        Args:
            query_id: ID of the query.
            owner_org_id: Organization that owns the query. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Raises:
            RobotoNotFoundException: No query has this ID.
        """
        response = self.__roboto_client.get(f"v1/query/id/{query_id}", owner_org_id=owner_org_id or self.__owner_org_id)
        return response.to_record(QueryRecord)

    def get_query_results(
        self,
        query_id: str,
        owner_org_id: typing.Optional[str] = None,
        page_size: typing.Optional[int] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Yield every result of a query, fetching one page at a time as iteration reaches it.

        Args:
            query_id: ID of a query whose results are available.
            owner_org_id: Organization that owns the query. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.
            page_size: Number of results to fetch per request, from 1 to 1000
                (:py:const:`~roboto.query.MAX_PAGE_SIZE`). ``None`` fetches 50
                (:py:const:`~roboto.query.DEFAULT_PAGE_SIZE`).

        Yields:
            Record of each matching resource, as a dictionary, in the query's sort order.

        Raises:
            RobotoIllegalArgumentException: ``page_size`` is outside 1 to 1000. It surfaces on the first iteration.
        """
        query_params: dict[str, str] = {} if page_size is None else {"page_size": str(page_size)}
        while True:
            response = self.__roboto_client.get(
                f"v1/query/id/{query_id}/results",
                query=query_params,
                owner_org_id=owner_org_id or self.__owner_org_id,
            )
            response_data = response.to_dict(json_path=["data"])
            for record in response_data["items"]:
                yield record

            if "next_token" in response_data and response_data["next_token"]:
                query_params["next_page_token"] = response_data["next_token"]
            else:
                break

    def submit_query(
        self,
        query: typing.Optional[Query],
        target: QueryTarget,
        timeout_seconds: float,
        content_mode: QueryContentMode = QueryContentMode.RecordWithMeta,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Submit a RoboQL or structured query, wait for it to finish, and yield its results.

        To cap the total number of results, set ``max_results`` on a
        :py:class:`~roboto.query.QuerySpecification`, or add ``LIMIT N`` to a RoboQL query.

        Args:
            query: RoboQL string or :py:class:`~roboto.query.QuerySpecification` to run. ``None`` matches every
                resource of the ``target`` kind.
            target: Kind of resource to search, such as :py:attr:`~roboto.query.QueryTarget.Datasets`.
            timeout_seconds: How long to wait for the query to finish, in seconds.
            content_mode: Whether each result includes the resource's metadata. See
                :py:class:`~roboto.query.QueryContentMode`.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Yields:
            Record of each matching resource, as a dictionary, in the query's sort order.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not available within ``timeout_seconds``. A
                query that fails keeps the wait going until the timeout. It surfaces on the first iteration.
        """
        if query is None:
            query = QuerySpecification()

        if isinstance(query, QuerySpecification):
            return self.submit_structured_and_await_results(
                request=SubmitStructuredQueryRequest(query=query, target=target, content_mode=content_mode),
                timeout_seconds=timeout_seconds,
                owner_org_id=owner_org_id,
            )

        return self.submit_roboql_and_await_results(
            request=SubmitRoboqlQueryRequest(query=query, target=target, content_mode=content_mode),
            timeout_seconds=timeout_seconds,
            owner_org_id=owner_org_id,
        )

    def submit_roboql(
        self,
        request: SubmitRoboqlQueryRequest,
        owner_org_id: typing.Optional[str] = None,
    ) -> QueryRecord:
        """Submit a RoboQL query and return its record without waiting for it to finish.

        Pass the record's ``query_id`` to ``get_query_results`` once ``are_query_results_available`` returns ``True``.

        Args:
            request: Query to submit, and the kind of resource it searches.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Raises:
            RobotoIllegalArgumentException: The query is not valid RoboQL.
        """
        response = self.__roboto_client.post(
            "v1/query/submit/roboql",
            data=request,
            owner_org_id=owner_org_id or self.__owner_org_id,
        )
        return response.to_record(QueryRecord)

    def submit_roboql_and_await_results(
        self,
        request: SubmitRoboqlQueryRequest,
        timeout_seconds: float,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Submit a RoboQL query, wait for it to finish, and yield its results.

        To cap the total number of results, add ``LIMIT N`` to the query.

        Args:
            request: Query to submit, and the kind of resource it searches.
            timeout_seconds: How long to wait for the query to finish, in seconds.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Yields:
            Record of each matching resource, as a dictionary, in the query's sort order.

        Raises:
            RobotoIllegalArgumentException: The query is not valid RoboQL. It surfaces on the first iteration.
            roboto.waiters.TimeoutError: The query's results were not available within ``timeout_seconds``. A
                query that fails keeps the wait going until the timeout. It surfaces on the first iteration.
        """
        query = self.submit_roboql(request, owner_org_id)

        wait_for(
            self.are_query_results_available,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        yield from self.get_query_results(query.query_id)

    def submit_structured(
        self,
        request: SubmitStructuredQueryRequest,
        owner_org_id: typing.Optional[str] = None,
    ) -> QueryRecord:
        """Submit a structured query and return its record without waiting for it to finish.

        Pass the record's ``query_id`` to ``get_query_results`` once ``are_query_results_available`` returns ``True``.

        Args:
            request: Query to submit, and the kind of resource it searches.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.
        """
        response = self.__roboto_client.post(
            "v1/query/submit/structured",
            data=request,
            owner_org_id=owner_org_id or self.__owner_org_id,
        )
        return response.to_record(QueryRecord)

    def submit_structured_and_await_results(
        self,
        request: SubmitStructuredQueryRequest,
        timeout_seconds: float,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Submit a structured query, wait for it to finish, and yield its results.

        To cap the total number of results, set ``max_results`` on the request's
        :py:class:`~roboto.query.QuerySpecification`.

        Args:
            request: Query to submit, and the kind of resource it searches.
            timeout_seconds: How long to wait for the query to finish, in seconds.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Yields:
            Record of each matching resource, as a dictionary, in the query's sort order.

        Raises:
            roboto.waiters.TimeoutError: The query's results were not available within ``timeout_seconds``. A
                query that fails keeps the wait going until the timeout. It surfaces on the first iteration.
        """
        query = self.submit_structured(request, owner_org_id)

        wait_for(
            self.are_query_results_available,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        yield from self.get_query_results(query.query_id)

    def submit_term(self, request: SubmitTermQueryRequest, owner_org_id: typing.Optional[str] = None) -> QueryRecord:
        """Submit a term query and return its record without waiting for it to finish.

        A term query matches resources whose fields contain a search term. Pass the record's ``query_id`` to
        ``get_query_results`` once ``are_query_results_available`` returns ``True``.

        Args:
            request: Term to search for, and the kind of resource to search.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.
        """
        response = self.__roboto_client.post(
            "v1/query/submit/term",
            data=request,
            owner_org_id=owner_org_id or self.__owner_org_id,
        )

        return response.to_record(QueryRecord)

    def submit_term_and_await_results(
        self,
        request: SubmitTermQueryRequest,
        timeout_seconds: float = math.inf,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Submit a term query, wait for it to finish, and yield its results.

        Args:
            request: Term to search for, and the kind of resource to search.
            timeout_seconds: How long to wait for the query to finish, in seconds. Defaults to waiting indefinitely.
            owner_org_id: Organization to run the query in. Defaults to the organization this client was built
                with, and otherwise to the organization the caller acts in.

        Yields:
            Record of each matching resource, as a dictionary, in the query's sort order.

        Raises:
            roboto.waiters.TimeoutError: The query's results were not available within ``timeout_seconds``. A
                query that fails keeps the wait going until the timeout, so with the default ``timeout_seconds``
                the first iteration never returns.
        """
        query = self.submit_term(request, owner_org_id)

        wait_for(
            self.are_query_results_available,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        yield from self.get_query_results(query.query_id)
