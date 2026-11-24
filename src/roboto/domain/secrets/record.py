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
    """Kind of secret store that holds a secret's value."""

    AWS = "aws"
    """AWS Secrets Manager."""


class AwsSecretsManagerAccessCreds(pydantic.BaseModel):
    """Short-lived AWS credentials that reach one secret's value in AWS Secrets Manager.

    Carried in ``GetSecretAccessCredsResponse.creds``. Building one with any other ``store_type`` raises
    ``pydantic.ValidationError``.
    """

    access_key_id: str
    """AWS access key ID of the credentials."""

    secret_access_key: str
    """AWS secret access key of the credentials."""

    session_token: str
    """AWS session token of the credentials."""

    region: str
    """AWS region the secret is stored in."""

    store_type: typing.Literal[SecretStoreType.AWS] = SecretStoreType.AWS
    """Kind of secret store, always ``SecretStoreType.AWS``."""


SecretAccessCreds = typing.Union[AwsSecretsManagerAccessCreds]
"""Secret access credentials of any kind: one of ``AwsSecretsManagerAccessCreds``."""


class AwsSecretRetrievalLocation(pydantic.BaseModel):
    """Location of a secret's value in AWS Secrets Manager.

    Carried in ``SecretRecord.location``. Building one with any other ``store_type`` raises
    ``pydantic.ValidationError``.
    """

    store_type: typing.Literal[SecretStoreType.AWS] = SecretStoreType.AWS
    """Kind of secret store, always ``SecretStoreType.AWS``."""

    arn: str
    """Amazon Resource Name (ARN) of the secret in AWS Secrets Manager."""


SecretRetrievalLocation = typing.Union[AwsSecretRetrievalLocation]
"""Secret value location of any kind: one of ``AwsSecretRetrievalLocation``."""


class SecretRecord(pydantic.BaseModel):
    """Data record of a secret, as the Roboto API returns it.

    A secret is sensitive information, such as an API key or password, that actions can use while they run. Its value
    is kept in a secret store and never passes through Roboto's APIs, so the record holds only where to find it.
    :py:class:`~roboto.domain.secrets.Secret` wraps this record with methods that act on the secret, and exposes it
    as :py:attr:`~roboto.domain.secrets.Secret.record`.
    """

    created: datetime.datetime
    """Time the secret was created."""

    created_by: str
    """Principal that created the secret, as ``<type>:<id>``, such as ``user:<user_id>``."""

    last_used: typing.Optional[datetime.datetime] = None
    """Time an action last used the secret, or ``None`` if none has."""

    location: SecretRetrievalLocation = pydantic.Field(discriminator="store_type")
    """Location of the secret's value in its secret store.

    Reading or updating the value takes this location together with the short-lived credentials in
    ``GetSecretAccessCredsResponse``.
    """

    modified: datetime.datetime
    """Time the secret was last modified."""

    modified_by: str
    """Principal that last modified the secret, in the same ``<type>:<id>`` form as ``created_by``."""

    name: str
    """Name of the secret, unique within its organization."""

    org_id: str
    """ID of the organization that owns the secret."""

    store_type: SecretStoreType
    """Type of secret store that holds the secret's value."""


class CreateSecretRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.secrets.Secret.create`."""

    name: str
    """Name of the secret, unique within the organization it is created in."""


class GetSecretAccessCredsResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.secrets.Secret.read_value`.

    :py:meth:`~roboto.domain.secrets.Secret.update_value` reads it too. Both send
    ``GET /v1/secrets/name/{secret_name}/creds``, then use ``creds`` to reach the secret store directly, so the value
    never passes through Roboto.
    """

    record: SecretRecord
    """Record of the secret."""

    creds: SecretAccessCreds = pydantic.Field(discriminator="store_type")
    """Short-lived credentials scoped to this one secret.

    They can always read its value, and can also overwrite it only when the caller has permission to update the
    secret.
    """
