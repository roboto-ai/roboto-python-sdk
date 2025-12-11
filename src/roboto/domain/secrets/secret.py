# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import re
import typing

import boto3
import pydantic

from ...http import RobotoClient
from . import AwsSecretsManagerAccessCreds
from .record import (
    CreateSecretRequest,
    GetSecretAccessCredsResponse,
    SecretRecord,
    SecretStoreType,
)

SECRET_URI_REGEX = re.compile(r"(roboto-secret://)([^@]+)(@(\w+))?")


@dataclasses.dataclass(frozen=True)
class ParsedSecretName:
    name: str
    org_id: typing.Optional[str]


def is_secret_uri(uri: str) -> bool:
    return SECRET_URI_REGEX.match(uri) is not None


def parse_secret_uri(
    uri: str,
) -> ParsedSecretName:
    match = SECRET_URI_REGEX.match(uri)
    if not match:
        raise ValueError(f"Invalid secret URI: {uri}")
    return ParsedSecretName(name=match.group(2), org_id=match.group(4))


class Secret:
    """A secret stored in the Roboto platform's secret management system.

    Secrets provide secure storage for sensitive information like API keys, passwords,
    and other credentials that can be used by actions during execution. Each secret
    is scoped to an organization and stored in a secure backend (currently AWS Secrets Manager).
    The secret's value is never sent through Roboto's APIs, providing an additional
    layer of security.

    Secret names are unique within an organization, so a name + org_id combination
    provides a fully qualified reference to a specific secret.

    Secrets cannot be instantiated directly through the constructor. Use the class
    methods :py:meth:`create`, :py:meth:`from_name`, or :py:meth:`for_org` to
    create or retrieve secrets.
    """

    @classmethod
    def create(
        cls,
        name: str,
        caller_org_id: typing.Optional[str] = None,
        initial_value: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Secret:
        """Create a new secret in the Roboto platform.

        Creates a new secret with the specified name and optionally sets its initial value.
        The secret will be stored in the organization's secure secret store (AWS Secrets Manager).

        Args:
            name: Name of the secret to create. Must be unique within the organization.
            caller_org_id: Organization ID where the secret should be created. If not
                provided, creates the secret in the caller's organization.
            initial_value: Optional initial value to set for the secret. If provided,
                the secret's value will be set immediately after creation.
            roboto_client: HTTP client for API communication. If not provided, uses
                the default client configuration.

        Returns:
            A new Secret instance representing the created secret.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to create secrets
                in the specified organization.
            RobotoConflictException: A secret with the same name already exists in the organization.
            RobotoIllegalArgumentException: Invalid parameters provided.
            RobotoInvalidRequestException: Malformed request.

        Examples:
            Create a secret without an initial value:

            >>> secret = Secret.create(name="api_key", caller_org_id="org_123")
            >>> print(secret.name)
            'api_key'

            Create a secret with an initial value:

            >>> secret = Secret.create(
            ...     name="database_password", caller_org_id="org_123", initial_value="super_secure_password"
            ... )
            >>> print(secret.name)
            'database_password'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        record = roboto_client.post(
            "v1/secrets",
            data=CreateSecretRequest(name=name),
            caller_org_id=caller_org_id,
        ).to_record(SecretRecord)

        secret = cls(record=record, roboto_client=roboto_client)

        if initial_value is not None:
            secret.update_value(initial_value)

        return secret

    @classmethod
    def for_org(
        cls,
        org_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator[Secret, None, None]:
        """Retrieve all secrets belonging to an organization.

        Returns a generator that yields all secrets owned by the specified organization.
        Results are paginated automatically to handle large numbers of secrets efficiently.

        Args:
            org_id: Organization ID whose secrets should be retrieved.
            roboto_client: HTTP client for API communication. If not provided, uses
                the default client configuration.

        Yields:
            Secret instances for each secret owned by the organization.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to list secrets
                in the specified organization.
            RobotoNotFoundException: The specified organization does not exist.

        Examples:
            List all secrets in an organization:

            >>> secrets = list(Secret.for_org(org_id="org_123"))
            >>> for secret in secrets:
            ...     print(f"Secret: {secret.name}")
            Secret: api_key
            Secret: database_password

            Process secrets one at a time without loading all into memory:

            >>> for secret in Secret.for_org(org_id="org_123"):
            ...     print(f"Processing secret: {secret.name}")
            ...     # Process each secret individually
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if next_token:
                query_params["page_token"] = str(next_token)

            results = roboto_client.get(
                "v1/secrets",
                owner_org_id=org_id,
                query=query_params,
            ).to_paginated_list(SecretRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def from_name(
        cls,
        name: str,
        org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Secret:
        """Load an existing secret by name.

        Secret names are unique within an organization, so a name + org_id combination
        provides a fully qualified reference to a specific secret.

        Args:
            name: Name of the secret to retrieve. Must be unique within the organization.
            org_id: Organization ID that owns the secret. If not provided, searches
                in the caller's organization.
            roboto_client: HTTP client for API communication. If not provided, uses
                the default client configuration.

        Returns:
            A Secret instance representing the found secret.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to access the secret.
            RobotoNotFoundException: No secret with the specified name exists in the organization.

        Examples:
            Load a secret from the caller's organization:

            >>> secret = Secret.from_name(name="api_key")
            >>> print(secret.name)
            'api_key'

            Load a secret from a specific organization:

            >>> secret = Secret.from_name(name="database_password", org_id="org_123")
            >>> print(f"{secret.name} in {secret.org_id}")
            'database_password in org_123'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        record = roboto_client.get(
            f"v1/secrets/name/{name}",
            owner_org_id=org_id,
        ).to_record(SecretRecord)

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_uri(
        cls,
        uri: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        fallback_org_id: typing.Optional[str] = None,
    ) -> Secret:
        """Load an existing secret by URI.

        Args:
            uri: URI of the secret to retrieve.
            roboto_client: HTTP client for API communication. If not provided, uses
                the default client configuration.
            fallback_org_id: Default organization ID to use if not provided in the URI.

        Returns:
            A Secret instance representing the found secret.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to access the secret.
            RobotoNotFoundException: No secret with the specified name exists in the organization.
            ValueError: The provided URI is not a valid secret URI.

        Examples:
            Load a secret from a URI:

            >>> secret = Secret.from_uri("roboto-secret://api_key@org_123")
            >>> print(f"{secret.name} in {secret.org_id}")
            'api_key in org_123'

            Load a secret from a URI with a default org ID:

            >>> secret = Secret.from_uri("roboto-secret://api_key", fallback_org_id="org_123")
            >>> print(f"{secret.name} in {secret.org_id}")
            'api_key in org_123'
        """
        if not is_secret_uri(uri):
            raise ValueError(f"Invalid secret URI: {uri}")

        parsed = parse_secret_uri(uri)
        return cls.from_name(
            name=parsed.name,
            org_id=parsed.org_id or fallback_org_id,
            roboto_client=roboto_client,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return False
        return self.__record == other.__record

    def __init__(self, record: SecretRecord, roboto_client: RobotoClient):
        """Initialize a Secret instance.

        This constructor is not intended for direct use. Use the class methods
        :py:meth:`create`, :py:meth:`from_name`, or :py:meth:`for_org` instead.

        Args:
            record: The secret record containing metadata and configuration.
            roboto_client: HTTP client for API communication.
        """
        self.__record: SecretRecord = record
        self.__roboto_client: RobotoClient = roboto_client

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def name(self) -> str:
        """Name of the secret.

        Secret names are unique within an organization.
        """
        return self.__record.name

    @property
    def org_id(self) -> str:
        """Organization ID that owns this secret."""
        return self.__record.org_id

    @property
    def record(self) -> SecretRecord:
        """The secret record containing metadata and configuration."""
        return self.__record

    @property
    def store_type(self) -> SecretStoreType:
        """Type of secret store backend where this secret is stored.

        Currently, all secrets are stored in AWS Secrets Manager.
        """
        return self.__record.store_type

    @property
    def uri(self) -> str:
        """URI for this secret.

        This URI can be used to reference the secret in other API calls.
        """
        return f"roboto-secret://{self.__record.name}@{self.__record.org_id}"

    def delete(self) -> None:
        """Delete this secret from the Roboto platform.

        Permanently removes the secret and its value from the secure storage backend.
        This operation cannot be undone.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to delete this secret.
            RobotoNotFoundException: The secret no longer exists.

        Examples:
            Delete a secret:

            >>> secret = Secret.from_name("old_api_key")
            >>> secret.delete()
            # Secret is now permanently deleted
        """
        self.__roboto_client.delete(
            f"v1/secrets/name/{self.__record.name}",
            owner_org_id=self.__record.org_id,
        )

    def read_value(self) -> pydantic.SecretStr:
        """Read the value stored in this secret.

        Securely retrieves the secret's value from the underlying secret store (AWS Secrets Manager).
        The operation uses temporary, scoped credentials to ensure secure access to the secret store.

        Returns:
            The secret value as a pydantic.SecretStr.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to read this secret.
            RobotoNotFoundException: The secret no longer exists.
            NotImplementedError: The secret uses an unsupported store type.

        Examples:
            Read a secret's value:

            >>> secret = Secret.from_name("api_key")
            >>> value = secret.read_value()
            >>> print(value.get_secret_value())
            'super_secret_api_key_value'
        """
        client = self.__boto_client_for_creds()
        res = client.get_secret_value(SecretId=self.__record.location.arn)
        return pydantic.SecretStr(res["SecretString"])

    def refresh(self) -> Secret:
        """Refresh this secret's metadata from the Roboto platform.

        Updates the secret's local metadata by fetching the latest information from
        the server. This is useful to get updated timestamps or other metadata that
        may have changed since the secret was last loaded.

        Returns:
            This Secret instance with updated metadata.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to access this secret.
            RobotoNotFoundException: The secret no longer exists.

        Examples:
            Refresh a secret's metadata:

            >>> secret = Secret.from_name("api_key")
            >>> secret.refresh()
            >>> # Secret now has the latest metadata from the server
        """
        self.__record = self.__roboto_client.get(
            f"v1/secrets/name/{self.__record.name}",
            owner_org_id=self.__record.org_id,
        ).to_record(SecretRecord)
        return self

    def update_value(self, new_value: str) -> Secret:
        """Update the value stored in this secret.

        Securely updates the secret's value in the underlying secret store (AWS Secrets Manager).
        The operation uses temporary, scoped credentials to ensure secure access to the secret store.

        Args:
            new_value: The new value to store in the secret.

        Returns:
            This Secret instance for method chaining.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to update this secret.
            RobotoNotFoundException: The secret no longer exists.
            NotImplementedError: The secret uses an unsupported store type.

        Examples:
            Update a secret's value:

            >>> secret = Secret.from_name("api_key")
            >>> secret.update_value("new_secret_api_key_value")
            >>> # Secret value has been updated in the secure store

            Chain method calls:

            >>> secret = Secret.create(name="temp_key").update_value("initial_value")
            >>> print(secret.name)
            'temp_key'
        """
        client = self.__boto_client_for_creds()
        client.put_secret_value(SecretId=self.__record.location.arn, SecretString=new_value)

        return self

    def __boto_client_for_creds(self) -> typing.Any:
        res = self.__roboto_client.get(
            f"v1/secrets/name/{self.__record.name}/creds",
            owner_org_id=self.__record.org_id,
        ).to_record(GetSecretAccessCredsResponse)
        creds = res.creds

        if not isinstance(creds, AwsSecretsManagerAccessCreds):
            raise NotImplementedError(f"Unsupported secret store type: {self.__record.store_type}")

        return boto3.client(
            "secretsmanager",
            aws_access_key_id=creds.access_key_id,
            aws_secret_access_key=creds.secret_access_key,
            aws_session_token=creds.session_token,
            region_name=creds.region,
        )
