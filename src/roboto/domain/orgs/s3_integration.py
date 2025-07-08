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
    """Request payload to integrate an S3 bucket with Roboto."""

    account_id: str
    """AWS account ID that owns the S3 bucket."""

    aws_region: str
    """AWS region where the S3 bucket is located."""

    bucket_name: str
    """Name of the S3 bucket to integrate."""

    org_id: str
    """Organization ID to associate with this S3 integration."""

    transfer_accelerated: bool = False
    """Whether to enable S3 Transfer Acceleration for faster uploads."""

    readonly: bool = False
    """Whether Roboto should have read-only access to the bucket."""


class RegisterS3IntegrationResponse(pydantic.BaseModel):
    """Response payload containing S3 integration setup instructions."""

    iam_role_name: str
    """Name of the IAM role to create for Roboto access."""

    iam_role_policy: dict[str, typing.Any]
    """IAM policy document to attach to the role."""

    iam_role_trust_relationship: dict[str, typing.Any]
    """IAM trust policy document for the role."""

    s3_bucket_cors_policy: list[dict[str, typing.Any]]
    """CORS policy to apply to the S3 bucket."""


class S3IntegrationService:
    """Service for integrating S3 buckets with Roboto organizations.

    This service handles the setup of cross-account IAM roles and S3 bucket
    policies to allow Roboto to access customer S3 buckets for data storage
    and processing.
    """

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
        """Initialize the S3 integration service.

        Args:
            roboto_client: Roboto client instance for API communication.
            sts_client: Optional boto3 STS client. If not provided, creates a default client.
            s3_client: Optional boto3 S3 client. If not provided, creates a default client.
            iam_client: Optional boto3 IAM client. If not provided, creates a default client.
        """
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
        readonly: bool = False,
    ):
        """Register an S3 bucket for use with a Roboto organization.

        This method sets up the necessary IAM roles and S3 bucket policies to allow
        Roboto to access the specified S3 bucket. The caller must have appropriate
        AWS credentials with permissions to create IAM roles and modify S3 bucket policies.

        Args:
            org_id: Organization ID to associate with this S3 integration.
            account_id: AWS account ID that owns the S3 bucket.
            bucket_name: Name of the S3 bucket to integrate.
            transfer_accelerated: Whether to enable S3 Transfer Acceleration.
            readonly: Whether Roboto should have read-only access to the bucket.

        Raises:
            RobotoInvalidRequestException: AWS credentials are invalid or account ID mismatch.
            ValueError: The specified bucket does not exist or is not owned by the account.
            botocore.exceptions.ClientError: AWS API errors during setup.

        Examples:
            Register a bucket for read-write access:

            >>> from roboto.domain.orgs import S3IntegrationService
            >>> from roboto import RobotoClient
            >>> service = S3IntegrationService(RobotoClient())
            >>> service.register_bucket(
            ...     org_id="org_12345",
            ...     account_id="123456789012",
            ...     bucket_name="my-data-bucket"
            ... )

            Register a bucket with read-only access:

            >>> service.register_bucket(
            ...     org_id="org_12345",
            ...     account_id="123456789012",
            ...     bucket_name="my-readonly-bucket",
            ...     readonly=True
            ... )
        """
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
                readonly=readonly,
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
