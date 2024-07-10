# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from collections.abc import Generator
import typing

from roboto.exceptions import (
    RobotoHttpExceptionParse,
)
from roboto.http import (
    HttpClient,
    PaginatedList,
    roboto_headers,
)
from roboto.waiters import wait_for

from .api import (
    QueryRecord,
    QueryStatus,
    SubmitRoboqlQueryRequest,
    SubmitStructuredQueryRequest,
)

Model = typing.TypeVar("Model")


class QueryClient:
    __http_client: HttpClient
    __roboto_service_endpoint: str

    def __init__(self, http_client: HttpClient, roboto_service_endpoint: str):
        self.__http_client = http_client
        self.__roboto_service_endpoint = roboto_service_endpoint

    def submit_structured(
        self, request: SubmitStructuredQueryRequest, org_id: str
    ) -> QueryRecord:
        with RobotoHttpExceptionParse():
            url = f"{self.__roboto_service_endpoint}/v1/query/submit/structured"
            result = self.__http_client.post(
                url=url,
                data=request.model_dump(mode="json"),
                headers=roboto_headers(resource_owner_id=org_id),
            )

            return QueryRecord.model_validate(result.to_dict(json_path=["data"]))

    def submit_roboql(
        self, request: SubmitRoboqlQueryRequest, org_id: str
    ) -> QueryRecord:
        with RobotoHttpExceptionParse():
            url = f"{self.__roboto_service_endpoint}/v1/query/submit/roboql"
            result = self.__http_client.post(
                url=url,
                data=request.model_dump(mode="json"),
                headers=roboto_headers(resource_owner_id=org_id),
            )

            return QueryRecord.model_validate(result.to_dict(json_path=["data"]))

    def get_query_record(self, query_id: str) -> QueryRecord:
        with RobotoHttpExceptionParse():
            url = f"{self.__roboto_service_endpoint}/v1/query/id/{query_id}"
            return QueryRecord.model_validate(
                self.__http_client.get(url=url).to_dict(json_path=["data"])
            )

    def check_query_is_complete(self, query_id: str) -> bool:
        return self.get_query_record(query_id).status == QueryStatus.Completed

    def get_query_results(self, query_id: str) -> PaginatedList[dict[str, typing.Any]]:
        with RobotoHttpExceptionParse():
            url = f"{self.__roboto_service_endpoint}/v1/query/id/{query_id}/results"
            unmarshalled = self.__http_client.get(url=url).to_dict(json_path=["data"])
            return PaginatedList(
                items=unmarshalled["items"], next_token=unmarshalled.get("next_token")
            )

    def submit_structured_and_await_results(
        self,
        request: SubmitStructuredQueryRequest,
        org_id: str,
        timeout_seconds: float = 30,
    ) -> Generator[dict[str, typing.Any], None, None]:
        query = self.submit_structured(request, org_id)

        wait_for(
            self.check_query_is_complete,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        for result in self.get_query_results(query.query_id).items:
            yield result

    def submit_roboql_and_await_results(
        self,
        request: SubmitRoboqlQueryRequest,
        org_id: str,
        timeout_seconds: float = 30,
    ) -> Generator[dict[str, typing.Any], None, None]:
        query = self.submit_roboql(request, org_id)

        wait_for(
            self.check_query_is_complete,
            args=[query.query_id],
            timeout=timeout_seconds,
            interval=2,
        )

        for result in self.get_query_results(query.query_id).items:
            yield result
