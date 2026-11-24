# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
from typing import Optional, Union

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import (
    Credentials,
    ReadOnlyCredentials,
)

from ..exceptions import RobotoDeprecatedException
from ..logging import default_logger
from .request import HttpRequest

logger = default_logger()


class BearerTokenDecorator:
    """Request decorator that sends one fixed access token in each request's ``Authorization`` header.

    Pass it to :py:class:`~roboto.http.RobotoClient` as ``auth_decorator``.
    :py:meth:`~roboto.http.RobotoClient.from_config` builds one from the configured access token.

    Args:
        token: Roboto access token to send, as ``Bearer <token>``.

    Raises:
        RobotoDeprecatedException: The token is in the format Roboto issued before March 20, 2024, which begins
            with ``robo_pat``.
    """

    __auth_header: str

    def __init__(self, token: str):
        if token.startswith("robo_pat"):
            raise RobotoDeprecatedException(
                "You're using an auth token created before March 20th, 2024. These are being phased out in favor of a "
                + "newer token format. Please create a new token via https://app.roboto.ai/settings/tokens."
            )

        self.__auth_header = f"Bearer {token}"

    def __call__(self, request: HttpRequest) -> HttpRequest:
        if request.headers is None:
            request.headers = {}

        request.headers["Authorization"] = self.__auth_header
        return request


class SigV4AuthDecorator:
    """Request decorator that signs each request with AWS Signature Version 4.

    Roboto's own services use it to call Roboto with their AWS identity; to send an access token, use
    ``BearerTokenDecorator`` instead. Role credentials, such as a container's, an EC2 instance's or an assumed role's,
    are temporary and rotate. Reading them again for each request keeps a long-lived process signing with current ones
    instead of being rejected as expired until it restarts.

    Args:
        service: Signing name of the AWS service to sign for, such as ``execute-api`` for API Gateway.
        credentials: Credentials to sign with. ``botocore.credentials.ReadOnlyCredentials`` are used as given for
            every request. A ``botocore.credentials.Credentials`` object, such as
            ``botocore.credentials.RefreshableCredentials`` for an assumed role, is read again for each request, so it
            can refresh itself before it expires. ``None`` resolves this process's own credentials through boto3 for
            each request.
        region: AWS region to sign for. ``None`` uses ``lookup_region``.

    Raises:
        RuntimeError: ``credentials`` is ``None`` and boto3 finds no AWS credentials for this process.
        ValueError: ``region`` is ``None`` and no region is configured.
    """

    __credentials: Optional[Union[ReadOnlyCredentials, Credentials]]
    """Credentials the caller supplied, or ``None`` to resolve them through the session for each request."""

    __session: Optional[boto3.Session]
    __region: str
    __service: str

    @staticmethod
    def lookup_credentials() -> ReadOnlyCredentials:
        """Return this process's current AWS credentials, as a new default boto3 session resolves them.

        Building a ``SigV4AuthDecorator`` without ``credentials`` checks for them through it, so most code never
        calls it.

        Raises:
            RuntimeError: boto3 finds no AWS credentials for this process.
        """
        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials found")

        return creds.get_frozen_credentials()

    @staticmethod
    def lookup_region() -> str:
        """Return the AWS region to sign for when the constructor is given none.

        Uses the default boto3 session's region, which comes from ``AWS_DEFAULT_REGION`` or the AWS config file,
        then the ``AWS_REGION`` environment variable.

        Raises:
            ValueError: None of these sets a region.
        """
        session = boto3.Session()
        if session.region_name:
            return session.region_name

        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION"))
        if not region:
            raise ValueError("One of AWS_REGION or AWS_DEFAULT_REGION must be set.")
        return region

    def __init__(
        self,
        service: str = "execute-api",
        credentials: Optional[Union[ReadOnlyCredentials, Credentials]] = None,
        region: Optional[str] = None,
    ):
        self.__credentials = credentials
        # Reuse one session: it caches the credentials it resolves, and botocore refreshes role
        # credentials shortly before they expire. A session per request would resolve them from
        # scratch on every request.
        self.__session = None if credentials else boto3.Session()
        self.__region = region if region else SigV4AuthDecorator.lookup_region()
        self.__service = service

        if self.__session is not None:
            # Fail at construction, not at the first request, when the process has no credentials at all.
            SigV4AuthDecorator.lookup_credentials()

    def __call__(self, request: HttpRequest) -> HttpRequest:
        if "Host" not in request.headers:
            request.append_headers({"Host": request.hostname})

        aws_request = AWSRequest(method=request.method.upper(), url=request.url, data=request.body)
        aws_request.context["payload_signing_enabled"] = True
        SigV4Auth(self.__current_credentials(), self.__service, self.__region).add_auth(aws_request)
        request.append_headers(dict(aws_request.headers.items()))
        return request

    def __current_credentials(self) -> ReadOnlyCredentials:
        """Return the credentials for one request, read again on each call unless the caller supplied frozen ones."""
        if isinstance(self.__credentials, Credentials):
            return self.__credentials.get_frozen_credentials()

        if self.__credentials is not None:
            return self.__credentials

        if self.__session is None:
            raise RuntimeError("No AWS credentials found")

        creds = self.__session.get_credentials()
        if creds is None:
            # The construction-time check used a separate session, so this one can still find no
            # credentials if they disappear before the first request. Once found, the session caches them.
            raise RuntimeError("No AWS credentials found")

        return creds.get_frozen_credentials()
