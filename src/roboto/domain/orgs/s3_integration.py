# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import typing

import boto3
import botocore.exceptions
import pydantic

from ...exceptions import (
    RobotoInvalidRequestException,
)
from ...http import RobotoClient
from ...logging import default_logger

logger = default_logger()


class RegisterS3IntegrationRequest(pydantic.BaseModel):
    account_id: str
    aws_region: str
    bucket_name: str
    org_id: str
    transfer_accelerated: bool = False


class RegisterS3IntegrationResponse(pydantic.BaseModel):
    iam_role_name: str
    iam_role_policy: dict[str, typing.Any]
    iam_role_trust_relationship: dict[str, typing.Any]
    s3_bucket_cors_policy: list[dict[str, typing.Any]]


class S3IntegrationService:
    __roboto_client: RobotoClient
    __s3_client: typing.Any  # boto3.client("s3")
    __sts_client: typing.Any  # boto3.client("sts")
    __iam_client: typing.Any  # boto3.client("iam")

    def __init__(
        self,
        roboto_client: RobotoClient,
        sts_client: typing.Optional[typing.Any] = None,
        s3_client: typing.Optional[typing.Any] = None,
        iam_client: typing.Optional[typing.Any] = None,
    ):
        self.__s3_client = s3_client or boto3.client("s3")
        self.__sts_client = sts_client or boto3.client("sts")
        self.__iam_client = iam_client or boto3.client("iam")
        self.__roboto_client = roboto_client

    def register_bucket(
        self,
        org_id: str,
        account_id: str,
        bucket_name: str,
        transfer_accelerated: bool = False,
    ):
        logger.info("Checking that you have access to the specified account and bucket")

        try:
            available_account_id = self.__sts_client.get_caller_identity().get(
                "Account"
            )
        except botocore.exceptions.ClientError:
            raise RobotoInvalidRequestException("Couldn't get caller ID from AWS")

        if available_account_id != account_id:
            raise RobotoInvalidRequestException(
                f"Account ID mismatch: you're trying to add a bucket to account {account_id}, "
                + f"but your current credentials are for {available_account_id}"
            )

        buckets = self.__s3_client.list_buckets().get("Buckets", [])
        bucket_names = {bucket["Name"] for bucket in buckets}

        if bucket_name not in bucket_names:
            raise ValueError(f"Account {account_id} does not own bucket {bucket_name}")

        aws_region = self.__s3_client.get_bucket_location(Bucket=bucket_name)[
            "LocationConstraint"
        ]

        response = self.__roboto_client.post(
            "v1/integrations/storage/s3/register",
            data=RegisterS3IntegrationRequest(
                account_id=account_id,
                bucket_name=bucket_name,
                org_id=org_id,
                aws_region=aws_region,
                transfer_accelerated=transfer_accelerated,
            ),
        ).to_record(RegisterS3IntegrationResponse)

        self.__iam_client.create_role(
            RoleName=response.iam_role_name,
            AssumeRolePolicyDocument=json.dumps(response.iam_role_trust_relationship),
            Description=f"Cross-account role which grants Roboto read/write access to the bucket '{bucket_name}'.",
        )

        self.__iam_client.put_role_policy(
            RoleName=response.iam_role_name,
            # Policy name limit is 128 characters, we'll cap at a couple characters short of that.
            PolicyName=f"RobotoS3Access-{bucket_name[:110]}",
            PolicyDocument=json.dumps(response.iam_role_policy),
        )

        self.__s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration={"CORSRules": response.s3_bucket_cors_policy},
        )
