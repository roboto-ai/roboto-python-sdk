# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
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


class S3BucketHealthCheck(pydantic.BaseModel):
    """Result of a health check, in which Roboto tests that it can reach an organization's S3 bucket.

    Holds no bucket name, role Amazon Resource Name (ARN), AWS account ID, secret, or AWS error message, so it is safe
    to display; the record that carries it holds the bucket's identifiers. Carried in
    ``S3BucketIntegrationRecord.last_health_check``.
    """

    reason_code: str
    """Classification of the result.

    One of ``ok``, ``role_not_assumable``, ``permission_denied``, ``bucket_not_found``, ``region_mismatch``,
    ``encryption_denied``, ``throttled`` or ``roboto_error``.
    """

    aws_error_code: str | None = None
    """AWS error code behind the result, such as ``AccessDenied``, or ``None`` if no AWS error caused it."""

    message: str
    """Human-readable explanation of the result, safe to display."""

    probes: dict[str, str] = pydantic.Field(default_factory=dict)
    """Outcome of each request Roboto tried, keyed by request.

    The keys are ``assume_role``, ``location``, ``list``, ``put``, ``get`` and ``delete``. Each outcome is ``ok``,
    ``denied``, ``error`` or ``skipped``. Roboto stops at the first request that fails and skips the rest, and on a
    read-only bucket it skips ``put``, ``get`` and ``delete``.
    """


class S3BucketIntegrationRecord(pydantic.BaseModel):
    """Data record of an S3 bucket integration, as ``GET /v1/integrations/storage/s3/buckets`` returns it.

    ``POST /v1/integrations/storage/s3/buckets/{bucket}/healthcheck`` also returns it, after checking the bucket.
    An S3 bucket integration is an S3 bucket in a customer's own AWS account that an organization has registered
    with Roboto, so that Roboto reads and stores the organization's files there.
    """

    bucket_name: str
    """Name of the S3 bucket."""

    org_id: str
    """ID of the organization that registered the bucket."""

    aws_region: str
    """AWS region the bucket is in, such as ``us-west-2``."""

    readonly: bool
    """Whether Roboto has read-only access to the bucket."""

    status: str
    """Result of the most recent health check.

    One of ``healthy``, ``unhealthy`` when the check found a problem to fix, ``unknown`` when it reached no verdict,
    such as when AWS throttled it, or ``unverified`` if the bucket has never been checked.
    """

    created: datetime.datetime
    """Time the bucket was registered."""

    modified: datetime.datetime
    """Time the integration's configuration was last modified. Health checks do not change it."""

    status_last_updated: datetime.datetime | None = None
    """Time ``status`` was last set.

    This is when the most recent health check ran, or when the bucket was registered if it has never been checked.
    """

    last_health_check: S3BucketHealthCheck | None = None
    """Result of the most recent health check, or ``None`` if the bucket has never been checked."""


class RegisterS3IntegrationRequest(pydantic.BaseModel):
    """Request body for ``S3IntegrationService.register_bucket``."""

    account_id: str
    """ID of the AWS account that owns the bucket."""

    aws_region: str
    """AWS region the bucket is in, such as ``us-west-2``."""

    bucket_name: str
    """Name of the S3 bucket to register."""

    org_id: str
    """ID of the organization to register the bucket with."""

    transfer_accelerated: bool = False
    """Whether the bucket uses S3 Transfer Acceleration. Roboto records the value; it does not turn acceleration on."""

    readonly: bool = False
    """Whether to grant Roboto read-only access to the bucket.

    ``False`` grants read-write access and makes the bucket the organization's default bucket for new datasets' files.
    Only a Roboto administrator can register a read-only bucket.
    """


class RegisterS3IntegrationResponse(pydantic.BaseModel):
    """Response body of ``S3IntegrationService.register_bucket``.

    Holds the IAM role and CORS rules that the bucket's AWS account needs before Roboto can reach the bucket;
    ``register_bucket`` creates them.
    """

    iam_role_name: str
    """Name of the IAM role to create in the bucket's AWS account, which Roboto assumes to reach the bucket."""

    iam_role_policy: dict[str, typing.Any]
    """Inline policy document to attach to the role, granting the S3 actions Roboto needs on the bucket."""

    iam_role_trust_relationship: dict[str, typing.Any]
    """Trust policy document for the role, which lets Roboto's AWS account assume it.

    Roboto's account must present an external ID unique to this registration to assume the role.
    """

    s3_bucket_cors_policy: list[dict[str, typing.Any]]
    """CORS rules to set on the bucket, so that the Roboto web app can read and write the bucket's objects."""


class S3IntegrationService:
    """Client that registers an S3 bucket in the caller's own AWS account with a Roboto organization.

    Calls AWS with the caller's AWS credentials to grant Roboto access to the bucket. To register a bucket from the
    command line, use ``roboto orgs register-bucket``.

    Args:
        roboto_client: Client to make requests to Roboto with.
        sts_client: boto3 STS client to make AWS requests with. ``None`` creates one from the environment's AWS
            credentials and configuration.
        s3_client: boto3 S3 client to make AWS requests with. ``None`` creates one the same way.
        iam_client: boto3 IAM client to make AWS requests with. ``None`` creates one the same way.
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
        """Register an S3 bucket with an organization and grant Roboto access to it.

        Uses the environment's AWS credentials, which must belong to ``account_id`` and be allowed to create IAM roles
        and set the bucket's CORS configuration. In order, it:

        1. Checks that the credentials belong to ``account_id`` and that the account owns the bucket.
        2. Registers the bucket with Roboto, which returns the IAM role and CORS rules Roboto needs.
        3. Creates the IAM role in the account and attaches its inline policy.
        4. Sets the bucket's CORS rules.

        Only a member of the organization can call it, and only a Roboto administrator can register a read-only
        bucket.

        Args:
            org_id: ID of the organization to register the bucket with.
            account_id: ID of the AWS account that owns the bucket.
            bucket_name: Name of the S3 bucket to register.
            transfer_accelerated: Whether the bucket uses S3 Transfer Acceleration. Roboto records the value; this
                method does not turn acceleration on.
            readonly: Whether to grant Roboto read-only access to the bucket. ``False`` grants read-write access and
                makes the bucket the organization's default bucket for new datasets' files.

        Raises:
            RobotoInvalidRequestException: AWS cannot identify the credentials, or they belong to an account other
                than ``account_id``.
            ValueError: The account does not own a bucket named ``bucket_name``.
            RobotoUnauthorizedException: The organization is not on the premium tier, or the caller is not allowed to
                register the bucket.
            RobotoConflictException: The organization has already registered the bucket.
            botocore.exceptions.ClientError: An AWS request fails, such as when the credentials cannot create IAM roles
                or a role with the same name already exists.

        Note:
            Step 4 replaces any CORS rules the bucket already has. If step 3 or 4 fails, the bucket stays registered
            with Roboto, so calling this method again raises ``RobotoConflictException``.

        Examples:
            Register a bucket for read-write access:

            >>> from roboto import RobotoClient
            >>> from roboto.domain.orgs.s3_integration import S3IntegrationService
            >>> service = S3IntegrationService(RobotoClient.from_env())
            >>> service.register_bucket(org_id="og_12345", account_id="123456789012", bucket_name="my-data-bucket")

            Register a bucket with read-only access:

            >>> service.register_bucket(
            ...     org_id="og_12345", account_id="123456789012", bucket_name="my-readonly-bucket", readonly=True
            ... )
        """
        logger.info("Checking that you have access to the specified account and bucket")

        try:
            available_account_id = self.__sts_client.get_caller_identity().get("Account")
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

        aws_region = self.__s3_client.get_bucket_location(Bucket=bucket_name)["LocationConstraint"]

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
            # IAM limits policy names to 128 characters; the 15-character prefix plus 110 of the bucket name fits.
            PolicyName=f"RobotoS3Access-{bucket_name[:110]}",
            PolicyDocument=json.dumps(response.iam_role_policy),
        )

        self.__s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration={"CORSRules": response.s3_bucket_cors_policy},
        )
