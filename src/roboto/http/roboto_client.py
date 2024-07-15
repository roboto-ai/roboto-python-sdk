# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import logging
import typing
import urllib.parse

from ..config import RobotoConfig
from ..exceptions import RobotoHttpExceptionParse
from ..logging import LOGGER_NAME
from .headers import roboto_headers
from .http_client import HttpClient
from .request import HttpRequestDecorator
from .request_decorators import (
    BearerTokenDecorator,
)
from .response import HttpResponse
from .retry import RetryWaitFn

logger = logging.getLogger(LOGGER_NAME)


ApiRelativePath = typing.Union[str, collections.abc.Sequence[str]]


class RobotoClient:
    """
    A client for making HTTP requests against Roboto service
    """

    __from_env_instance: typing.ClassVar[typing.Optional["RobotoClient"]] = None
    __endpoint: str
    __http_client: HttpClient

    @classmethod
    def from_env(cls) -> "RobotoClient":
        if cls.__from_env_instance:
            return cls.__from_env_instance

        cfg = RobotoConfig.from_env()

        auth_decorator = BearerTokenDecorator(token=cfg.api_key)
        cls.__from_env_instance = RobotoClient(
            endpoint=cfg.endpoint, auth_decorator=auth_decorator
        )
        return cls.__from_env_instance

    @classmethod
    def defaulted(
        cls, client: typing.Optional["RobotoClient"] = None
    ) -> "RobotoClient":
        return client or RobotoClient.from_env()

    def __init__(
        self, endpoint: str, auth_decorator: typing.Optional[HttpRequestDecorator]
    ):
        self.__endpoint = endpoint
        self.__http_client = HttpClient(
            default_endpoint=endpoint, default_auth=auth_decorator
        )

    @property
    def http_client(self) -> HttpClient:
        return self.__http_client

    @property
    def endpoint(self) -> str:
        return self.__endpoint

    def delete(
        self,
        path: ApiRelativePath,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        with RobotoHttpExceptionParse():
            return self.__http_client.delete(
                url=self.__build_url(path, query),
                data=data,
                headers=roboto_headers(
                    org_id=caller_org_id,
                    resource_owner_id=owner_org_id,
                    additional_headers=headers,
                ),
                retry_wait=retry_wait_fn,
                idempotent=idempotent,
            )

    def get(
        self,
        path: ApiRelativePath,
        caller_org_id: typing.Optional[str] = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        with RobotoHttpExceptionParse():
            return self.__http_client.get(
                url=self.__build_url(path, query),
                headers=roboto_headers(
                    org_id=caller_org_id,
                    resource_owner_id=owner_org_id,
                    additional_headers=headers,
                ),
                retry_wait=retry_wait_fn,
                idempotent=idempotent,
            )

    def patch(
        self,
        path: ApiRelativePath,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        with RobotoHttpExceptionParse():
            return self.__http_client.patch(
                url=self.__build_url(path, query),
                data=data,
                headers=roboto_headers(
                    org_id=caller_org_id,
                    resource_owner_id=owner_org_id,
                    additional_headers=headers,
                ),
                retry_wait=retry_wait_fn,
                idempotent=idempotent,
            )

    def post(
        self,
        path: ApiRelativePath,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        with RobotoHttpExceptionParse():
            return self.__http_client.post(
                url=self.__build_url(path, query),
                data=data,
                headers=roboto_headers(
                    org_id=caller_org_id,
                    resource_owner_id=owner_org_id,
                    additional_headers=headers,
                ),
                retry_wait=retry_wait_fn,
                idempotent=idempotent,
            )

    def put(
        self,
        path: ApiRelativePath,
        caller_org_id: typing.Optional[str] = None,
        data: typing.Any = None,
        headers: typing.Optional[dict[str, str]] = None,
        idempotent: bool = True,
        owner_org_id: typing.Optional[str] = None,
        query: typing.Optional[dict[str, typing.Any]] = None,
        retry_wait_fn: typing.Optional[RetryWaitFn] = None,
    ) -> HttpResponse:
        with RobotoHttpExceptionParse():
            return self.__http_client.put(
                url=self.__build_url(path, query),
                data=data,
                headers=roboto_headers(
                    org_id=caller_org_id,
                    resource_owner_id=owner_org_id,
                    additional_headers=headers,
                ),
                retry_wait=retry_wait_fn,
                idempotent=idempotent,
            )

    def __build_url(
        self,
        path: ApiRelativePath,
        query: typing.Optional[dict[str, typing.Any]] = None,
    ) -> str:
        if isinstance(path, str):
            normalized_path = path
        else:
            normalized_path = "/".join(path)

        normalized_path = normalized_path.lstrip("/")

        if query is None:
            return f"{self.__endpoint}/{normalized_path}"
        else:
            return (
                f"{self.__endpoint}/{normalized_path}?{urllib.parse.urlencode(query)}"
            )