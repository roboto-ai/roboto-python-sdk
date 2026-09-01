# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
from typing import Optional

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import (
    ReadOnlyCredentials,
)

from ..exceptions import RobotoDeprecatedException
from ..logging import default_logger
from .request import HttpRequest

logger = default_logger()


class BearerTokenDecorator:
    """
    Decorates requests with a static, unchanging bearer token.
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
    __credentials: Optional[ReadOnlyCredentials]
    """Explicitly supplied credentials, or ``None`` to resolve them per request.

    ``None`` is the important case for a long-lived process. Role credentials -- a Fargate
    task's, an EC2 instance's -- are temporary and rotate; a snapshot taken once at
    construction goes stale after a few hours, and every request signed with it is then
    rejected as expired until the process restarts. Resolving per request lets botocore hand
    over whatever is current.
    """

    __session: Optional[boto3.Session]
    __region: str
    __service: str

    @staticmethod
    def lookup_credentials() -> ReadOnlyCredentials:
        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials found")

        return creds.get_frozen_credentials()

    @staticmethod
    def lookup_region() -> str:
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
        credentials: Optional[ReadOnlyCredentials] = None,
        region: Optional[str] = None,
    ):
        self.__credentials = credentials
        # One session, reused: it owns botocore's credential resolver, which refreshes role
        # credentials in the background. A new session per request would re-resolve from
        # scratch every time and lose that caching.
        self.__session = None if credentials else boto3.Session()
        self.__region = region if region else SigV4AuthDecorator.lookup_region()
        self.__service = service

        if self.__session is not None:
            # Fail at construction, not at the first request: a process with no credentials at
            # all is misconfigured, and finding that out here is far easier to diagnose.
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
        """The credentials to sign this request with.

        Explicit ones are returned as given -- a caller that supplied credentials owns their
        lifetime. Otherwise the session is asked afresh, which is what picks up a rotation.
        """
        if self.__credentials is not None:
            return self.__credentials

        if self.__session is None:
            raise RuntimeError("No AWS credentials found")

        creds = self.__session.get_credentials()
        if creds is None:
            # Reachable despite the construction-time check: credentials can be withdrawn from
            # under a running process, and signing with nothing would fail less legibly.
            raise RuntimeError("No AWS credentials found")

        return creds.get_frozen_credentials()
