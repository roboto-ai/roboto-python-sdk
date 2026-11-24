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
from ..env import Timeout
from ..exceptions import RobotoHttpExceptionParse
from ..logging import LOGGER_NAME
from ..sentinels import NotSet, is_set
from .headers import roboto_headers
from .http_client import HttpClient
from .request import HttpRequestDecorator
from .request_decorators import (
    BearerTokenDecorator,
)
from .requester import RobotoRequester, RobotoTool
from .response import HttpResponse
from .retry import RetryWaitFn

logger = logging.getLogger(LOGGER_NAME)

ApiRelativePath = typing.Union[str, collections.abc.Sequence[str]]
"""Route of the Roboto API, relative to the endpoint: a string such as ``"v1/datasets"``, or a sequence of segments.

``RobotoClient`` joins a sequence with ``/`` without escaping its segments, and drops any leading ``/``.
"""

DEFAULT_HTTP_TIMEOUT = 30.0
"""Seconds a client from ``RobotoClient.from_config`` waits on each request by default.

This default applies when the config's ``default_http_timeout`` is ``NotSet``.
"""


class RobotoClient:
    """Client that sends requests to one Roboto API endpoint with one set of credentials.

    SDK methods that take a ``roboto_client`` send their requests through it. You can also call any Roboto API route
    with its request methods. Each request:

    - names the newest API version this SDK knows, and the organizations its ``caller_org_id`` and ``owner_org_id``
      arguments give;
    - is retried, up to 10 attempts in all, when it fails in a way
      :py:func:`~roboto.http.is_expected_to_be_transient` judges transient. The ``options`` in
      ``http_client_kwargs`` can change both.

    Args:
        endpoint: URL of the Roboto API to send requests to, such as ``https://api.roboto.ai``.
        auth_decorator: Decorator that adds credentials to each request, such as a
            :py:class:`~roboto.http.BearerTokenDecorator`. ``None`` sends requests without credentials.
        http_client_kwargs: Keyword arguments for the :py:class:`~roboto.http.HttpClient` that sends the requests,
            such as ``default_timeout`` or ``options``. ``None`` passes none, so requests wait indefinitely.
    """

    __endpoint: str
    __from_env_instance: typing.ClassVar[typing.Optional["RobotoClient"]] = None
    __http_client: HttpClient

    @classmethod
    def for_profile(cls, profile: str) -> "RobotoClient":
        """Build a client from a profile in the Roboto config file.

        An access token in ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` takes precedence over the profile, as
        :py:meth:`~roboto.config.RobotoConfig.from_env` describes. Each call builds a new client.

        Args:
            profile: Name of the config file profile to read.

        Raises:
            FileNotFoundError: No access token is set and the config file does not exist.
            OSError: The config file exists but cannot be read.
            ValueError: The config file is not a JSON object, holds no valid profile, or has no profile by this name.
            RobotoDeprecatedException: The access token begins with ``robo_pat``, a format Roboto retired in March
                2024.

        Examples:
            >>> from roboto.domain.datasets import Dataset
            >>> roboto_client = RobotoClient.for_profile("prod")
            >>> dataset = Dataset.from_id("ds_12345", roboto_client=roboto_client)
        """
        return RobotoClient.from_config(RobotoConfig.from_env(profile_override=profile))

    @classmethod
    def from_config(cls, config: RobotoConfig) -> "RobotoClient":
        """Build a client that sends requests to the config's endpoint with its access token.

        Each request waits up to the config's ``default_http_timeout``: ``None`` waits indefinitely, and ``NotSet``
        waits 30 seconds (``DEFAULT_HTTP_TIMEOUT``).

        Args:
            config: Endpoint, access token and default timeout to use.

        Raises:
            RobotoDeprecatedException: The config's access token begins with ``robo_pat``, a format Roboto retired in
                March 2024.
        """
        auth_decorator = BearerTokenDecorator(token=config.api_key)
        default_timeout = config.default_http_timeout if is_set(config.default_http_timeout) else DEFAULT_HTTP_TIMEOUT
        return RobotoClient(
            endpoint=config.endpoint,
            auth_decorator=auth_decorator,
            http_client_kwargs={"default_timeout": default_timeout},
        )

    @classmethod
    def from_env(cls) -> "RobotoClient":
        """Return the client configured from the environment, building it on the first call.

        The first call builds the client from :py:meth:`~roboto.config.RobotoConfig.from_env`, and every later call
        in the process returns that same client, so changes to the environment or config file after the first call do
        not apply to it.

        Raises:
            FileNotFoundError: On the first call, no access token is set and the config file does not exist.
            OSError: On the first call, the config file exists but cannot be read.
            ValueError: On the first call, the config file is not a JSON object, holds no valid profile, or has no
                profile by the chosen name.
            RobotoDeprecatedException: On the first call, the access token begins with ``robo_pat``, a format Roboto
                retired in March 2024.
        """
        if cls.__from_env_instance is None:
            cls.__from_env_instance = RobotoClient.from_config(RobotoConfig.from_env())

            # Requests through this client come from the SDK. The upload agent sets its own requester on it, and the
            # CLI builds its own client with make_cli_client.
            cls.__from_env_instance.http_client.set_requester(RobotoRequester.for_tool(RobotoTool.Sdk))

        return cls.__from_env_instance

    @classmethod
    def defaulted(cls, client: typing.Optional["RobotoClient"] = None) -> "RobotoClient":
        """Return ``client``, or the client ``from_env`` returns when it is ``None``.

        The SDK's own code uses it; to get the client configured from the environment, use ``from_env`` instead. When
        ``client`` is ``None``, the failures of ``from_env`` also apply.

        Args:
            client: Client to return. ``None`` returns the client configured from the environment.
        """
        return client or RobotoClient.from_env()

    def __init__(
        self,
        endpoint: str,
        auth_decorator: typing.Optional[HttpRequestDecorator],
        http_client_kwargs: typing.Optional[dict[str, typing.Any]] = None,
    ):
        self.__endpoint = endpoint
        defaulted_http_client_kwargs = http_client_kwargs if http_client_kwargs else {}
        self.__http_client = HttpClient(
            default_endpoint=endpoint,
            default_auth=auth_decorator,
            **defaulted_http_client_kwargs,
        )

    @property
    def http_client(self) -> HttpClient:
        """HTTP client that sends this client's requests, with its credentials, retry options and default timeout."""
        return self.__http_client

    @property
    def endpoint(self) -> str:
        """URL of the Roboto API this client sends requests to, such as ``https://api.roboto.ai``."""
        return self.__endpoint

    @property
    def frontend_endpoint(self) -> str:
        """URL of the Roboto web app for this client's endpoint, made by replacing each ``api`` in it with ``app``."""
        return self.__endpoint.replace("api", "app")

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
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a DELETE request to a Roboto API route and return Roboto's response.

        Args:
            path: Route to send the request to, relative to the endpoint, such as ``"v1/datasets"``.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            data: Request body. A pydantic model or a dictionary is sent as JSON;
                :py:attr:`~roboto.http.HttpRequest.body` says how each type is encoded. ``None`` sends no body.
            headers: Further headers to send. One with the name of the API version or an organization header replaces
                the value the client would send.
            idempotent: Whether sending the request more than once has the same effect as sending it once. Only an
                idempotent request is retried after a connection error, a timeout, or status 408, 500 or 504.
            owner_org_id: Organization that owns the resource the request reads or changes. ``None`` leaves Roboto to
                use the organization the request acts in.
            query: Query parameters to add to the URL, encoded by ``urllib.parse.urlencode``, so a list value is sent
                as its string form rather than as repeated parameters. ``None`` adds none.
            retry_wait_fn: Function that returns how long to wait before the next attempt, in milliseconds, given the
                ``tenacity.RetryCallState`` of the request. ``None`` waits a random time of up to 1 second after the
                first attempt, doubling that limit after each attempt up to 30 seconds.
            timeout: Seconds each attempt waits on the connection before it times out. ``None`` waits indefinitely,
                and ``NotSet`` uses the client's default.

        Raises:
            RobotoDomainException: Roboto responded with status 400, 401, 403, 404, 409 or 5xx, after any retries. The
                exception is the subclass for the status, such as ``RobotoNotFoundException`` for 404.
            HttpError: Roboto responded with any other error status, such as 429, after any retries.
            ConnectionRefusedError: Nothing at the endpoint accepted the connection.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: Roboto sent no response within ``timeout`` on the last attempt.
        """
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
                timeout=timeout,
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
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a GET request to a Roboto API route and return Roboto's response.

        Args:
            path: Route to send the request to, relative to the endpoint, such as ``"v1/datasets"``.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            headers: Further headers to send. One with the name of the API version or an organization header replaces
                the value the client would send.
            idempotent: Whether sending the request more than once has the same effect as sending it once. Only an
                idempotent request is retried after a connection error, a timeout, or status 408, 500 or 504.
            owner_org_id: Organization that owns the resource the request reads or changes. ``None`` leaves Roboto to
                use the organization the request acts in.
            query: Query parameters to add to the URL, encoded by ``urllib.parse.urlencode``, so a list value is sent
                as its string form rather than as repeated parameters. ``None`` adds none.
            retry_wait_fn: Function that returns how long to wait before the next attempt, in milliseconds, given the
                ``tenacity.RetryCallState`` of the request. ``None`` waits a random time of up to 1 second after the
                first attempt, doubling that limit after each attempt up to 30 seconds.
            timeout: Seconds each attempt waits on the connection before it times out. ``None`` waits indefinitely,
                and ``NotSet`` uses the client's default.

        Raises:
            RobotoDomainException: Roboto responded with status 400, 401, 403, 404, 409 or 5xx, after any retries. The
                exception is the subclass for the status, such as ``RobotoNotFoundException`` for 404.
            HttpError: Roboto responded with any other error status, such as 429, after any retries.
            ConnectionRefusedError: Nothing at the endpoint accepted the connection.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: Roboto sent no response within ``timeout`` on the last attempt.

        Examples:
            >>> from roboto.domain.datasets import DatasetRecord
            >>> roboto_client = RobotoClient.from_env()
            >>> record = roboto_client.get(["v1", "datasets", "ds_12345"]).to_record(DatasetRecord)
        """
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
                timeout=timeout,
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
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a PATCH request to a Roboto API route and return Roboto's response.

        Args:
            path: Route to send the request to, relative to the endpoint, such as ``"v1/datasets"``.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            data: Request body. A pydantic model or a dictionary is sent as JSON;
                :py:attr:`~roboto.http.HttpRequest.body` says how each type is encoded. ``None`` sends no body.
            headers: Further headers to send. One with the name of the API version or an organization header replaces
                the value the client would send.
            idempotent: Whether sending the request more than once has the same effect as sending it once. Only an
                idempotent request is retried after a connection error, a timeout, or status 408, 500 or 504.
            owner_org_id: Organization that owns the resource the request reads or changes. ``None`` leaves Roboto to
                use the organization the request acts in.
            query: Query parameters to add to the URL, encoded by ``urllib.parse.urlencode``, so a list value is sent
                as its string form rather than as repeated parameters. ``None`` adds none.
            retry_wait_fn: Function that returns how long to wait before the next attempt, in milliseconds, given the
                ``tenacity.RetryCallState`` of the request. ``None`` waits a random time of up to 1 second after the
                first attempt, doubling that limit after each attempt up to 30 seconds.
            timeout: Seconds each attempt waits on the connection before it times out. ``None`` waits indefinitely,
                and ``NotSet`` uses the client's default.

        Raises:
            RobotoDomainException: Roboto responded with status 400, 401, 403, 404, 409 or 5xx, after any retries. The
                exception is the subclass for the status, such as ``RobotoNotFoundException`` for 404.
            HttpError: Roboto responded with any other error status, such as 429, after any retries.
            ConnectionRefusedError: Nothing at the endpoint accepted the connection.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: Roboto sent no response within ``timeout`` on the last attempt.
        """
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
                timeout=timeout,
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
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a POST request to a Roboto API route and return Roboto's response.

        Args:
            path: Route to send the request to, relative to the endpoint, such as ``"v1/datasets"``.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            data: Request body. A pydantic model or a dictionary is sent as JSON;
                :py:attr:`~roboto.http.HttpRequest.body` says how each type is encoded. ``None`` sends no body.
            headers: Further headers to send. One with the name of the API version or an organization header replaces
                the value the client would send.
            idempotent: Whether sending the request more than once has the same effect as sending it once. Only an
                idempotent request is retried after a connection error, a timeout, or status 408, 500 or 504.
                Defaults to ``True``; pass ``False`` for a request that must not take effect twice.
            owner_org_id: Organization that owns the resource the request reads or changes. ``None`` leaves Roboto to
                use the organization the request acts in.
            query: Query parameters to add to the URL, encoded by ``urllib.parse.urlencode``, so a list value is sent
                as its string form rather than as repeated parameters. ``None`` adds none.
            retry_wait_fn: Function that returns how long to wait before the next attempt, in milliseconds, given the
                ``tenacity.RetryCallState`` of the request. ``None`` waits a random time of up to 1 second after the
                first attempt, doubling that limit after each attempt up to 30 seconds.
            timeout: Seconds each attempt waits on the connection before it times out. ``None`` waits indefinitely,
                and ``NotSet`` uses the client's default.

        Raises:
            RobotoDomainException: Roboto responded with status 400, 401, 403, 404, 409 or 5xx, after any retries. The
                exception is the subclass for the status, such as ``RobotoNotFoundException`` for 404.
            HttpError: Roboto responded with any other error status, such as 429, after any retries.
            ConnectionRefusedError: Nothing at the endpoint accepted the connection.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: Roboto sent no response within ``timeout`` on the last attempt.
        """
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
                timeout=timeout,
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
        timeout: Timeout = NotSet,
    ) -> HttpResponse:
        """Send a PUT request to a Roboto API route and return Roboto's response.

        Args:
            path: Route to send the request to, relative to the endpoint, such as ``"v1/datasets"``.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            data: Request body. A pydantic model or a dictionary is sent as JSON;
                :py:attr:`~roboto.http.HttpRequest.body` says how each type is encoded. ``None`` sends no body.
            headers: Further headers to send. One with the name of the API version or an organization header replaces
                the value the client would send.
            idempotent: Whether sending the request more than once has the same effect as sending it once. Only an
                idempotent request is retried after a connection error, a timeout, or status 408, 500 or 504.
            owner_org_id: Organization that owns the resource the request reads or changes. ``None`` leaves Roboto to
                use the organization the request acts in.
            query: Query parameters to add to the URL, encoded by ``urllib.parse.urlencode``, so a list value is sent
                as its string form rather than as repeated parameters. ``None`` adds none.
            retry_wait_fn: Function that returns how long to wait before the next attempt, in milliseconds, given the
                ``tenacity.RetryCallState`` of the request. ``None`` waits a random time of up to 1 second after the
                first attempt, doubling that limit after each attempt up to 30 seconds.
            timeout: Seconds each attempt waits on the connection before it times out. ``None`` waits indefinitely,
                and ``NotSet`` uses the client's default.

        Raises:
            RobotoDomainException: Roboto responded with status 400, 401, 403, 404, 409 or 5xx, after any retries. The
                exception is the subclass for the status, such as ``RobotoNotFoundException`` for 404.
            HttpError: Roboto responded with any other error status, such as 429, after any retries.
            ConnectionRefusedError: Nothing at the endpoint accepted the connection.
            urllib.error.URLError: The last attempt could not be sent for another reason, such as a host name that
                does not resolve.
            TimeoutError: Roboto sent no response within ``timeout`` on the last attempt.
        """
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
                timeout=timeout,
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

        if not query:
            return f"{self.__endpoint}/{normalized_path}"
        else:
            return f"{self.__endpoint}/{normalized_path}?{urllib.parse.urlencode(query)}"
