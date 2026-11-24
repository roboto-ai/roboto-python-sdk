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
    """A user: a person, or a service user Roboto runs automated work as, who acts in the organizations it belongs to.

    A user's ID is unique across Roboto, and a person's ID is their email address in lowercase. Roboto creates a
    person's user when they sign up.

    Get a ``User`` from ``for_self`` or ``from_id``. To wrap a :py:class:`~roboto.domain.users.UserRecord` already
    fetched from Roboto, build a ``User`` from it directly. Each instance holds a copy of the user's record, which
    ``update`` replaces with Roboto's response.

    Args:
        record: Record of the user.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
    """

    __record: UserRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        request: CreateUserRequest,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "User":
        """Create a user.

        Only a Roboto administrator may call it. Roboto creates a person's user when they sign up without calling this
        method.

        Args:
            request: The user to create.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new user.

        Raises:
            RobotoUnauthorizedException: The caller is not a Roboto administrator.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post("v1/users", data=request).to_record(UserRecord)
        return cls(record, roboto_client)

    @classmethod
    def for_self(cls, roboto_client: typing.Optional[RobotoClient] = None) -> "User":
        """Fetch the caller's own user.

        Args:
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            >>> from roboto import User
            >>> user = User.for_self()
            >>> print(user.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get("v1/users").to_record(UserRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(cls, user_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> "User":
        """Fetch a user by ID.

        A caller can fetch its own user and any user that shares an organization with it. A Roboto administrator can
        fetch any user.

        Args:
            user_id: ID of the user, which for a person is their email address.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoUnauthorizedException: No user has this ID, or the user shares no organization with the caller.
            RobotoNotFoundException: No user has this ID, and the caller is a Roboto administrator.

        Examples:
            >>> from roboto import User
            >>> user = User.from_id("alice@example.com")
            >>> print(user.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/users/id/{urllib.parse.quote_plus(user_id)}").to_record(UserRecord)
        return cls(record=record, roboto_client=roboto_client)

    def __init__(self, record: UserRecord, roboto_client: typing.Optional[RobotoClient] = None):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def user_id(self) -> str:
        """Unique ID of the user, which for a person is their email address in lowercase."""
        return self.__record.user_id

    @property
    def name(self) -> Optional[str]:
        """Human-readable display name of the user, or ``None`` if it has none."""
        return self.__record.name

    @property
    def record(self) -> UserRecord:
        """Record of the user that this instance holds."""
        return self.__record

    def delete(self) -> None:
        """Delete this user, along with its sign-in account, organization memberships, and personal access tokens.

        Deleting a user cannot be undone. A caller can delete only its own user, unless it is a Roboto administrator.

        Raises:
            RobotoInvalidRequestException: The user is the only owner of one of its organizations.
            RobotoNotFoundException: No user has this ID, as when it was already deleted.
            RobotoUnauthorizedException: This is not the caller's own user and the caller is not a Roboto
                administrator, or the call runs inside an action invocation.

        Examples:
            >>> from roboto import User
            >>> user = User.for_self()
            >>> user.delete()
        """
        self.__roboto_client.delete("v1/users", headers=roboto_headers(user_id=self.user_id))

    def to_dict(self) -> dict[str, Any]:
        """Return the user's record as a JSON-compatible dictionary.

        Examples:
            >>> from roboto import User
            >>> user = User.for_self()
            >>> print(user.to_dict()["user_id"])
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        name: Optional[str] = None,
        picture_url: Optional[str] = None,
        notification_channels_enabled: Optional[dict[NotificationChannel, bool]] = None,
        notification_types_enabled: Optional[dict[NotificationType, bool]] = None,
    ) -> "User":
        """Update the user's name, profile picture, or notification settings.

        A caller can update only its own user, unless it is a Roboto administrator.

        Args:
            name: Human-readable name to set on the user. ``None`` leaves it unchanged.
            picture_url: URL of the profile picture to set on the user. ``None`` leaves it unchanged.
            notification_channels_enabled: Whether each notification channel is enabled for the user. Replaces the
                user's whole mapping, so a channel left out is disabled. ``None`` or an empty mapping leaves it
                unchanged.
            notification_types_enabled: Whether each notification type is enabled for the user. Replaces the user's
                whole mapping, so a type left out is disabled. ``None`` or an empty mapping leaves it unchanged.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            pydantic.ValidationError: ``name`` or ``picture_url`` is an empty string.
            RobotoUnauthorizedException: This is not the caller's own user and the caller is not a Roboto
                administrator, or the call runs inside an action invocation.

        Examples:
            Set the user's name:

            >>> from roboto import User
            >>> user = User.for_self()
            >>> user = user.update(name="Alice Smith")

            Turn off email notifications and keep notifications in the Roboto web app:

            >>> from roboto.notifications import NotificationChannel
            >>> user = user.update(
            ...     notification_channels_enabled={NotificationChannel.Email: False, NotificationChannel.WebUi: True}
            ... )
        """
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
