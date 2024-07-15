# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...exceptions import RobotoDomainException
from ...http import RobotoClient
from .operations import CreateTokenRequest
from .record import TokenRecord


class Token:
    """
    A token allows users and devices to authenticate requests to Roboto.

    When a token is generated, a secret value is created which is shared with the user exactly once. This value is
    required for authentication, if lost a token can be deleted and a new token can be generated.
    """

    __roboto_client: RobotoClient
    __record: TokenRecord

    @classmethod
    def create(
        cls,
        name: str,
        description: typing.Optional[str] = None,
        expiry_days: int = 30,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple["Token", str]:
        """
        This returns a tuple of the token and the one-time generated secret. After creation, you'll never be able
        to retrieve the secret again, so you should save it!
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateTokenRequest(
            name=name, description=description, expiry_days=expiry_days
        )

        record = roboto_client.post("v1/tokens", data=request).to_record(TokenRecord)

        if record.secret is None:
            raise RobotoDomainException(
                "Token was generated without returning secret value, this renders it unusable."
            )

        return cls(record=record, roboto_client=roboto_client), record.secret

    @classmethod
    def from_id(
        cls, token_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "Token":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/tokens/id/{token_id}").to_record(TokenRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_self(
        cls, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Collection["Token"]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get("v1/tokens").to_record_list(TokenRecord)

        return [cls(record=record, roboto_client=roboto_client) for record in records]

    def __init__(
        self, record: TokenRecord, roboto_client: typing.Optional[RobotoClient] = None
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def record(self) -> TokenRecord:
        return self.__record

    @property
    def token_id(self) -> str:
        if self.__record.context is None:
            raise ValueError("Token record did not contain a token_id: " + str(self))

        return self.__record.context.token_id

    @property
    def user_id(self) -> str:
        if self.__record.user_id is None:
            raise ValueError("Token record did not contain a user_id: " + str(self))

        return self.__record.user_id

    def delete(self) -> None:
        self.__roboto_client.delete(f"v1/tokens/id/{self.token_id}")

    def disable(self) -> "Token":
        self.__roboto_client.post(f"v1/tokens/id/{self.token_id}/disable")
        return self

    def enable(self) -> "Token":
        self.__roboto_client.post(f"v1/tokens/id/{self.token_id}/enable")
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")
