# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
from typing import Any, Optional
import urllib.parse

from roboto.notifications import (
    NotificationChannel,
    NotificationType,
)

from ...http import RobotoClient, roboto_headers
from .operations import (
    CreateUserRequest,
    UpdateUserRequest,
)
from .record import UserRecord


class User:
    __record: UserRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        request: CreateUserRequest,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "User":
        """
        Creates a new user in Roboto. This API is only used by the Roboto platform itself as part of the signup
        process, any other caller will get an Unauthorized response from Roboto service.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post("v1/users", data=request).to_record(UserRecord)
        return cls(record, roboto_client)

    @classmethod
    def for_self(cls, roboto_client: typing.Optional[RobotoClient] = None) -> "User":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get("v1/users").to_record(UserRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, user_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "User":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/users/id/{urllib.parse.quote_plus(user_id)}"
        ).to_record(UserRecord)
        return cls(record=record, roboto_client=roboto_client)

    def __init__(
        self, record: UserRecord, roboto_client: typing.Optional[RobotoClient] = None
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def user_id(self) -> str:
        return self.__record.user_id

    @property
    def name(self) -> Optional[str]:
        return self.__record.name

    @property
    def record(self) -> UserRecord:
        return self.__record

    def delete(self) -> None:
        self.__roboto_client.delete(
            "v1/users", headers=roboto_headers(user_id=self.user_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        name: Optional[str] = None,
        picture_url: Optional[str] = None,
        notification_channels_enabled: Optional[dict[NotificationChannel, bool]] = None,
        notification_types_enabled: Optional[dict[NotificationType, bool]] = None,
    ) -> "User":
        request = UpdateUserRequest(
            name=name,
            picture_url=picture_url,
            notification_channels_enabled=notification_channels_enabled,
            notification_types_enabled=notification_types_enabled,
        )
        self.__record = self.__roboto_client.put(
            "v1/users", headers=roboto_headers(user_id=self.user_id), data=request
        ).to_record(UserRecord)
        return self
