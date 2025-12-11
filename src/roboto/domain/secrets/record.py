# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum


class SecretStoreType(StrEnum):
    """
    Type of secret store.
    """

    AWS = "aws"
    """
    AWS Secrets Manager.
    """


class AwsSecretsManagerAccessCreds(pydantic.BaseModel):
    """
    Context required to update a secret in AWS Secrets Manager.
    """

    access_key_id: str
    """
    AWS access key ID.
    """
    secret_access_key: str
    """
    AWS secret access key.
    """
    session_token: str
    """
    AWS session token.
    """
    region: str
    """
    AWS region.
    """
    store_type: typing.Literal[SecretStoreType.AWS] = SecretStoreType.AWS
    """Type of secret store. Referenced here explicitly to make deserialization work better."""


SecretAccessCreds = typing.Union[AwsSecretsManagerAccessCreds]
"""Union type for all possible secret update contexts."""


class AwsSecretRetrievalLocation(pydantic.BaseModel):
    """
    Information required to retrieve a secret from AWS Secrets Manager.
    """

    store_type: typing.Literal[SecretStoreType.AWS] = SecretStoreType.AWS
    """Type of secret store. Referenced here explicitly to make deserialization work better."""

    arn: str
    """
    ARN of the secret.
    """


SecretRetrievalLocation = typing.Union[AwsSecretRetrievalLocation]
"""Union type for all possible secret retrieval locations."""


class SecretRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of a secret.
    """

    created: datetime.datetime
    """Timestamp when the secret was created."""

    created_by: str
    """RobotoPrincipal which created the secret."""

    last_used: typing.Optional[datetime.datetime] = None
    """Timestamp when the secret was last used in an action, or None if the secret has never been used."""

    location: SecretRetrievalLocation = pydantic.Field(discriminator="store_type")
    """Information required to dereference the secret in its specific secret store. This is used in combination
    with temporary hyper-downscoped access creds to update or retrieve the secret's value."""

    modified: datetime.datetime
    """Timestamp when the secret was last modified."""

    modified_by: str
    """RobotoPrincipal which last modified the secret."""

    name: str
    """Name of the secret. Secret names must be unique within an organization."""

    org_id: str
    """Organization ID that owns the secret."""

    store_type: SecretStoreType
    """Type of secret store."""


class CreateSecretRequest(pydantic.BaseModel):
    """
    Request payload for the Create Secret
    """

    name: str
    """
    Name of the secret.
    """


class GetSecretAccessCredsResponse(pydantic.BaseModel):
    """
    Response payload for the Update Secret
    """

    record: SecretRecord
    """The secret whose value is going to be updated."""

    creds: SecretAccessCreds = pydantic.Field(discriminator="store_type")
    """Creds required to update the secret in its underlying data store."""
