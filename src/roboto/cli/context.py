# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

from ..config import RobotoConfig
from ..env import RobotoEnv, Timeout
from ..http import (
    BearerTokenDecorator,
    HttpClient,
    RobotoClient,
    RobotoRequester,
    RobotoTool,
)
from ..sentinels import NotSet, is_set


def make_cli_client(endpoint: str, token: str, default_timeout: Timeout = NotSet) -> RobotoClient:
    """Build a client that authenticates with ``token`` and tells the Roboto API its requests come from the CLI.

    Args:
        endpoint: Base URL of the Roboto API, such as ``https://api.roboto.ai``.
        token: Roboto access token.
        default_timeout: Seconds to wait for each request before giving up, as ``ROBOTO_DEFAULT_HTTP_TIMEOUT`` or
            a config file profile's ``default_http_timeout`` sets it. ``None`` or ``NotSet`` waits indefinitely.

    Raises:
        RobotoDeprecatedException: ``token`` is in the format Roboto retired in March 2024.
    """
    return RobotoClient(
        endpoint=endpoint,
        auth_decorator=BearerTokenDecorator(token),
        http_client_kwargs={
            "default_timeout": default_timeout if is_set(default_timeout) else None,
            "requester": RobotoRequester.for_tool(RobotoTool.Cli),
        },
    )


def cli_roboto_env(config_file: typing.Optional[pathlib.Path]) -> RobotoEnv:
    """Return the process's Roboto environment variables, with ``config_file`` in place of ``ROBOTO_CONFIG_FILE``.

    Args:
        config_file: The path given with the CLI's global ``--config-file`` option, or ``None`` when it wasn't given,
            which keeps ``ROBOTO_CONFIG_FILE`` as it is.
    """
    env = RobotoEnv.default()
    if config_file is None:
        return env
    return env.model_copy(update={"config_file": str(config_file)})


class CLIContext:
    __roboto_service_base_url: typing.Optional[str]
    __http: typing.Optional[HttpClient]
    extensions: dict[str, typing.Any]
    roboto_client: RobotoClient
    roboto_config: RobotoConfig

    @property
    def roboto_service_base_url(self) -> str:
        if self.__roboto_service_base_url is None:
            raise ValueError("roboto_service_base_url is unset")

        return self.__roboto_service_base_url

    @roboto_service_base_url.setter
    def roboto_service_base_url(self, roboto_service_base_url: str) -> None:
        self.__roboto_service_base_url = roboto_service_base_url

    @property
    def http_client(self) -> HttpClient:
        # The CLI's entry point sets this after parsing arguments, and only for commands that take a context.
        if self.__http is None:
            raise ValueError("Unset HTTP client!")

        return self.__http

    @http_client.setter
    def http_client(self, http: HttpClient) -> None:
        self.__http = http
