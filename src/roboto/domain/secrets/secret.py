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
"""Regular expression a secret URI must match: ``roboto-secret://<name>``, optionally followed by ``@<org_id>``."""


@dataclasses.dataclass(frozen=True)
class ParsedSecretName:
    """Secret name and organization ID read from a secret URI.

    ``parse_secret_uri`` returns it.
    """

    name: str
    """Name of the secret."""

    org_id: typing.Optional[str]
    """ID of the organization that owns the secret, or ``None`` if the URI names none."""


def is_secret_uri(uri: str) -> bool:
    """Return whether a string begins with a secret URI, as ``Secret.uri`` formats one.

    Roboto calls this when an action runs, to find the action parameter values that name a secret.

    Args:
        uri: String to check, such as an action parameter's value.
    """
    return SECRET_URI_REGEX.match(uri) is not None


def parse_secret_uri(
    uri: str,
) -> ParsedSecretName:
    """Return the secret name and organization ID that a secret URI names.

    Roboto calls this when an action runs, to find the secrets its parameters name. To load the secret a URI names,
    use ``Secret.from_uri``.

    Args:
        uri: Secret URI, as ``roboto-secret://<name>`` or ``roboto-secret://<name>@<org_id>``.

    Raises:
        ValueError: ``uri`` does not begin with a secret URI.
    """
    match = SECRET_URI_REGEX.match(uri)
    if not match:
        raise ValueError(f"Invalid secret URI: {uri}")
    return ParsedSecretName(name=match.group(2), org_id=match.group(4))


class Secret:
    """A secret: sensitive information, such as an API key or password, that actions can use while they run.

    A secret belongs to one organization and has a name unique within it. Its value is kept in a secret store and
    never passes through Roboto's APIs: ``read_value`` and ``update_value`` fetch short-lived credentials scoped to the
    secret and reach the store with them directly. An action parameter whose value is the secret's ``uri`` receives
    the secret's value when the action runs.

    Get a ``Secret`` from ``create``, ``from_name``, ``from_uri``, or ``for_org``. To wrap a
    :py:class:`~roboto.domain.secrets.SecretRecord` already fetched from Roboto, build a ``Secret`` from it directly.

    Args:
        record: Record of the secret.
        roboto_client: Client to make requests to Roboto with.
    """

    @classmethod
    def create(
        cls,
        name: str,
        caller_org_id: typing.Optional[str] = None,
        initial_value: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Secret:
        """Create a secret, optionally with a value.

        Args:
            name: Name of the secret, unique within the organization it is created in.
            caller_org_id: Organization to create the secret in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            initial_value: Value to store in the secret. It is set by ``update_value`` after the secret is created.
                ``None`` leaves the placeholder value ``"INITIAL_VALUE_NOT_SET_BY_USER"`` until a value is set.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new secret.

        Raises:
            RobotoConflictException: The organization already has a secret with this name.

        Examples:
            Create a secret without a value:

            >>> secret = Secret.create(name="api_key", caller_org_id="og_12345")
            >>> print(secret.name)
            api_key

            Create a secret with a value:

            >>> secret = Secret.create(
            ...     name="database_password", caller_org_id="og_12345", initial_value="super_secure_password"
            ... )
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
        """List the secrets in an organization.

        Fetches the secrets a page at a time as the generator is consumed.

        Args:
            org_id: ID of the organization whose secrets to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each secret the organization owns.

        Examples:
            Print the name of every secret in an organization:

            >>> for secret in Secret.for_org(org_id="og_12345"):
            ...     print(secret.name)
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
        """Fetch a secret by name.

        Secret names are unique within an organization, so a name and an organization identify one secret.

        Args:
            name: Name of the secret.
            org_id: Organization that owns the secret. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no secret with this name, or the caller cannot see it.

        Examples:
            Fetch a secret from the organization the caller acts in:

            >>> secret = Secret.from_name(name="api_key")

            Fetch a secret from a specific organization:

            >>> secret = Secret.from_name(name="database_password", org_id="og_12345")
            >>> print(f"{secret.name} in {secret.org_id}")
            database_password in og_12345
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
        """Fetch the secret a secret URI names.

        Reads the name and organization from ``uri`` and fetches the secret with ``from_name``, whose failures also
        apply.

        Args:
            uri: Secret URI, as ``roboto-secret://<name>`` or ``roboto-secret://<name>@<org_id>``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            fallback_org_id: Organization that owns the secret when ``uri`` names none. ``None`` uses the organization
                the caller acts in.

        Raises:
            ValueError: ``uri`` does not begin with a secret URI.

        Examples:
            Fetch a secret from a URI that names its organization:

            >>> secret = Secret.from_uri("roboto-secret://api_key@og_12345")
            >>> print(f"{secret.name} in {secret.org_id}")
            api_key in og_12345

            Fetch a secret from a URI that names no organization:

            >>> secret = Secret.from_uri("roboto-secret://api_key", fallback_org_id="og_12345")
            >>> print(f"{secret.name} in {secret.org_id}")
            api_key in og_12345
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
        self.__record: SecretRecord = record
        self.__roboto_client: RobotoClient = roboto_client

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def name(self) -> str:
        """Name of the secret, unique within its organization."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the secret."""
        return self.__record.org_id

    @property
    def record(self) -> SecretRecord:
        """Record of the secret that this instance holds.

        ``refresh`` replaces it with the current one.
        """
        return self.__record

    @property
    def store_type(self) -> SecretStoreType:
        """Type of secret store that holds the secret's value."""
        return self.__record.store_type

    @property
    def uri(self) -> str:
        """URI that names the secret, as ``roboto-secret://<name>@<org_id>``.

        Set it as an action parameter's value to pass the secret's value to the action, or load the secret from it
        with ``from_uri``.
        """
        return f"roboto-secret://{self.__record.name}@{self.__record.org_id}"

    def delete(self) -> None:
        """Delete the secret and its value.

        Roboto removes the value from the secret store with no recovery window, so it cannot be restored.

        Raises:
            RobotoNotFoundException: The secret no longer exists.

        Examples:
            >>> secret = Secret.from_name("old_api_key")
            >>> secret.delete()
        """
        self.__roboto_client.delete(
            f"v1/secrets/name/{self.__record.name}",
            owner_org_id=self.__record.org_id,
        )

    def read_value(self) -> pydantic.SecretStr:
        """Fetch the secret's value from its secret store.

        Roboto returns short-lived credentials that can read this one secret, and the SDK reads the value from the
        secret store with them, so the value never passes through Roboto.

        Returns:
            The value, as a ``pydantic.SecretStr``, which shows ``**********`` when printed or logged.
            ``get_secret_value()`` returns the value itself.

        Raises:
            RobotoNotFoundException: The secret no longer exists.

        Examples:
            >>> secret = Secret.from_name("api_key")
            >>> api_key = secret.read_value().get_secret_value()
        """
        client = self.__boto_client_for_creds()
        res = client.get_secret_value(SecretId=self.__record.location.arn)
        return pydantic.SecretStr(res["SecretString"])

    def refresh(self) -> Secret:
        """Fetch the secret's current record from Roboto.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The secret no longer exists.

        Examples:
            >>> secret = Secret.from_name("api_key")
            >>> secret.refresh()
        """
        self.__record = self.__roboto_client.get(
            f"v1/secrets/name/{self.__record.name}",
            owner_org_id=self.__record.org_id,
        ).to_record(SecretRecord)
        return self

    def update_value(self, new_value: str) -> Secret:
        """Replace the secret's value in its secret store.

        Roboto returns short-lived credentials scoped to this one secret, and the SDK writes the value to the secret
        store with them, so the value never passes through Roboto.

        Args:
            new_value: Value to store in the secret.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Raises:
            RobotoNotFoundException: The secret no longer exists.
            botocore.exceptions.ClientError: The caller cannot update the secret, so the credentials Roboto returns can
                only read its value.

        Examples:
            >>> secret = Secret.from_name("api_key")
            >>> secret.update_value("new_secret_api_key_value")
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
