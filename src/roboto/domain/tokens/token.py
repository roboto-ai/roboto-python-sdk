# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...auth.scope import ApiScope
from ...exceptions import RobotoDomainException
from ...http import RobotoClient
from .operations import CreateTokenRequest
from .record import TokenRecord


class Token:
    """A personal access token: a credential that authenticates requests to Roboto as the user who owns it.

    Create a personal access token with ``create``, and a device's token with
    :py:meth:`~roboto.domain.devices.Device.create_token`. Creating a token returns its secret, the value that
    authenticates requests, once; Roboto does not store it, so a lost secret cannot be recovered. Delete the token and
    create another.

    Get an existing ``Token`` from ``from_id`` or ``for_self``. To wrap a
    :py:class:`~roboto.domain.tokens.TokenRecord` already fetched from Roboto, build a ``Token`` from it directly.

    Args:
        record: Record of the token.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
    """

    __roboto_client: RobotoClient
    __record: TokenRecord

    @classmethod
    def create(
        cls,
        name: str,
        description: typing.Optional[str] = None,
        expiry_days: int = 30,
        api_scopes: typing.Optional[set[ApiScope]] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple["Token", str]:
        """Create a personal access token for the caller.

        The token authenticates requests as the calling user. Roboto rejects the request when a device or an action's
        invocation makes it.

        Args:
            name: Human-readable name of the token.
            description: Human-readable description of the token.
            expiry_days: Number of days the token stays valid, counted from its creation.
            api_scopes: API scopes the token is limited to. ``None`` or an empty set grants every scope.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            ``(token, secret)``: the new token and its secret. Roboto returns the secret only in this response, so save
            it now.

        Raises:
            RobotoUnauthorizedException: The token would hold a scope the credential making the request does not.
                ``None`` asks for every scope, so a token limited to some scopes must name the scopes when it creates
                another.

        Examples:
            Create a token that expires in 90 days, and keep its secret:

            >>> token, secret = Token.create(name="ci-uploads", expiry_days=90)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateTokenRequest(
            name=name,
            description=description,
            expiry_days=expiry_days,
            api_scopes=api_scopes,
        )

        record = roboto_client.post("v1/tokens", data=request).to_record(TokenRecord)

        if record.secret is None:
            raise RobotoDomainException("Token was generated without returning secret value, this renders it unusable.")

        return cls(record=record, roboto_client=roboto_client), record.secret

    @classmethod
    def from_id(cls, token_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> "Token":
        """Fetch a token by its ID.

        The token returned carries no secret.

        Args:
            token_id: Unique ID of the token, beginning with ``to_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No token has this ID.

        Examples:
            >>> token = Token.from_id("to_12345")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/tokens/id/{token_id}").to_record(TokenRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_self(cls, roboto_client: typing.Optional[RobotoClient] = None) -> collections.abc.Collection["Token"]:
        """List the tokens that authenticate as the calling user.

        The tokens returned carry no secret.

        Args:
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            Print the name and expiry of each of your tokens:

            >>> for token in Token.for_self():
            ...     print(token.record.context.name, token.record.context.expires)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get("v1/tokens").to_record_list(TokenRecord)

        return [cls(record=record, roboto_client=roboto_client) for record in records]

    def __init__(self, record: TokenRecord, roboto_client: typing.Optional[RobotoClient] = None):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def record(self) -> TokenRecord:
        """Record of the token that this instance holds."""
        return self.__record

    @property
    def token_id(self) -> str:
        """Unique ID of the token, beginning with ``to_``.

        It returns :py:attr:`~roboto.domain.tokens.TokenContext.token_id` from the record. Reading it raises
        ``ValueError`` when the record has no ``context``. Roboto sets it in every response, so this happens only for a
        record built some other way.
        """
        if self.__record.context is None:
            raise ValueError("Token record did not contain a token_id: " + str(self))

        return self.__record.context.token_id

    @property
    def user_id(self) -> str:
        """ID of the user who owns the token, which for a person is their email address.

        It returns :py:attr:`~roboto.domain.tokens.TokenRecord.user_id`. Reading it raises ``ValueError`` when the
        record has no ``user_id``. Roboto sets it in every response, so this happens only for a record built some other
        way.
        """
        if self.__record.user_id is None:
            raise ValueError("Token record did not contain a user_id: " + str(self))

        return self.__record.user_id

    def delete(self) -> None:
        """Delete the token, so its secret no longer authenticates requests.

        Deleting a token that no longer exists succeeds and changes nothing.

        Examples:
            >>> Token.from_id("to_12345").delete()
        """
        self.__roboto_client.delete(f"v1/tokens/id/{self.token_id}")

    def disable(self) -> "Token":
        """Disable the token, so Roboto rejects requests made with it until it is enabled again.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Examples:
            >>> token = Token.from_id("to_12345").disable()
        """
        self.__roboto_client.post(f"v1/tokens/id/{self.token_id}/disable")
        return self

    def enable(self) -> "Token":
        """Enable a disabled token, so it authenticates requests again until it expires.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Examples:
            >>> token = Token.from_id("to_12345").enable()
        """
        self.__roboto_client.post(f"v1/tokens/id/{self.token_id}/enable")
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the token's record as a JSON-compatible dictionary.

        Returns:
            :py:class:`~roboto.domain.tokens.TokenRecord` of the token, as a JSON-compatible dictionary.

        Examples:
            >>> token_dict = Token.from_id("to_12345").to_dict()
        """
        return self.__record.model_dump(mode="json")
