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
                + "newer token format. Please create a new token via https://app.roboto.ai/settings?tab=2."
            )

        self.__auth_header = f"Bearer {token}"

    def __call__(self, request: HttpRequest) -> HttpRequest:
        if request.headers is None:
            request.headers = {}

        request.headers["Authorization"] = self.__auth_header
        return request


class SigV4AuthDecorator:
    __credentials: ReadOnlyCredentials
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
        self.__credentials = (
            credentials if credentials else SigV4AuthDecorator.lookup_credentials()
        )
        self.__region = region if region else SigV4AuthDecorator.lookup_region()
        self.__service = service

    def __call__(self, request: HttpRequest) -> HttpRequest:
        if "Host" not in request.headers:
            request.append_headers({"Host": request.hostname})

        aws_request = AWSRequest(
            method=request.method.upper(), url=request.url, data=request.body
        )
        aws_request.context["payload_signing_enabled"] = True
        SigV4Auth(self.__credentials, self.__service, self.__region).add_auth(
            aws_request
        )
        request.append_headers(dict(aws_request.headers.items()))
        return request
