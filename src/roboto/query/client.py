# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ..config import RobotoConfig
from ..http import RobotoClient
from ..waiters import wait_for
from .api import (
    QueryRecord,
    QueryStatus,
    QueryTarget,
    SubmitRoboqlQueryRequest,
    SubmitStructuredQueryRequest,
)
from .specification import QuerySpecification

RoboQLQuery: typing.TypeAlias = str
Query: typing.TypeAlias = typing.Union[RoboQLQuery, QuerySpecification]


class QueryClient:
    """
    A low-level Roboto query client. Prefer :py:class:`~roboto.query.roboto_search.RobotoSearch` for a simpler,
    more curated query interface.
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
        return self.__roboto_client

    def is_query_completed(self, query_id: str) -> bool:
        return self.get_query_record(query_id).status == QueryStatus.Completed

    def get_query_record(self, query_id: str) -> QueryRecord:
        response = self.__roboto_client.get(
            f"v1/query/id/{query_id}",
        )
        return response.to_record(QueryRecord)

    def get_query_results(
        self, query_id: str
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        query_params: dict[str, str] = {}
        while True:
            response = self.__roboto_client.get(
                f"v1/query/id/{query_id}/results", query=query_params
            )
            response_data = response.to_dict(json_path=["data"])
            for record in response_data["items"]:
                yield record

            if "next_token" in response_data and response_data["next_token"]:
                query_params["page_token"] = response_data["next_token"]
            else:
                break

    def submit_query(
        self,
        query: typing.Optional[Query],
        target: QueryTarget,
        timeout_seconds: float,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        if query is None:
            query = QuerySpecification()

        if isinstance(query, QuerySpecification):
            return self.submit_structured_and_await_results(
                request=SubmitStructuredQueryRequest(query=query, target=target),
                timeout_seconds=timeout_seconds,
            )

        return self.submit_roboql_and_await_results(
            request=SubmitRoboqlQueryRequest(query=query, target=target),
            timeout_seconds=timeout_seconds,
        )

    def submit_roboql(self, request: SubmitRoboqlQueryRequest) -> QueryRecord:
        response = self.__roboto_client.post(
            "v1/query/submit/roboql",
            data=request,
            owner_org_id=self.__owner_org_id,
        )
        return response.to_record(QueryRecord)

    def submit_roboql_and_await_results(
        self,
        request: SubmitRoboqlQueryRequest,
        timeout_seconds: float,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        query = self.submit_roboql(request)

        wait_for(
            self.is_query_completed,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        yield from self.get_query_results(query.query_id)

    def submit_structured(self, request: SubmitStructuredQueryRequest) -> QueryRecord:
        response = self.__roboto_client.post(
            "v1/query/submit/structured",
            data=request,
            owner_org_id=self.__owner_org_id,
        )
        return response.to_record(QueryRecord)

    def submit_structured_and_await_results(
        self,
        request: SubmitStructuredQueryRequest,
        timeout_seconds: float,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        query = self.submit_structured(request)

        wait_for(
            self.is_query_completed,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        yield from self.get_query_results(query.query_id)
