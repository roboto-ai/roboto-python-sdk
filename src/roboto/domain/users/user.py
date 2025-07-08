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
    """Represents an individual who has access to the Roboto platform.

    Users are the fundamental identity entities in Roboto. They can be members of
    organizations, create and manage datasets and files within those organizations,
    and execute actions. Users are created during the signup process and cannot be
    instantiated directly by SDK users.

    User IDs are globally unique across the entire Roboto platform and typically
    correspond to email addresses for human users or service identifiers for
    automated users.
    """

    __record: UserRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        request: CreateUserRequest,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "User":
        """Create a new user in Roboto.

        This API is only used by the Roboto platform itself as part of the signup
        process. Any other caller will receive an Unauthorized response from the
        Roboto service.

        Args:
            request: User creation request containing user details.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A new User instance representing the created user.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to create users.
            RobotoInvalidRequestException: The request contains invalid data.

        Examples:
            Create a new service user:

            >>> from roboto import CreateUserRequest, User
            >>> request = CreateUserRequest(
            ...     user_id="service@example.com",
            ...     name="Service User",
            ...     is_service_user=True
            ... )
            >>> user = User.create(request)  # Only works for platform itself
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post("v1/users", data=request).to_record(UserRecord)
        return cls(record, roboto_client)

    @classmethod
    def for_self(cls, roboto_client: typing.Optional[RobotoClient] = None) -> "User":
        """Retrieve the current authenticated user.

        Returns the User object for the currently authenticated user based on
        the authentication credentials in the provided or default client.

        Args:
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            User instance representing the authenticated user.

        Raises:
            RobotoUnauthorizedException: No valid authentication credentials provided.

        Examples:
            Get the current user:

            >>> from roboto import User
            >>> current_user = User.for_self()
            >>> print(f"Current user: {current_user.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get("v1/users").to_record(UserRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, user_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "User":
        """Load an existing user by their unique user ID.

        User IDs are globally unique across the Roboto platform and typically
        correspond to email addresses for human users.

        Args:
            user_id: Unique identifier for the user to retrieve.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            User instance for the specified user ID.

        Raises:
            RobotoNotFoundException: No user exists with the specified ID.
            RobotoUnauthorizedException: The caller is not authorized to access this user.

        Examples:
            Load a user by email:

            >>> from roboto import User
            >>> user = User.from_id("alice@example.com")
            >>> print(f"User name: {user.name}")
        """
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
        """Unique identifier for this user.

        User IDs are globally unique across the Roboto platform and typically
        correspond to email addresses for human users.

        Returns:
            The user's unique identifier.
        """
        return self.__record.user_id

    @property
    def name(self) -> Optional[str]:
        """Human-readable display name for this user.

        Returns:
            The user's display name, or None if not set.
        """
        return self.__record.name

    @property
    def record(self) -> UserRecord:
        """Access the underlying user record.

        Provides access to the raw UserRecord containing all user data fields.
        This is useful for accessing fields not exposed as properties.

        Returns:
            The underlying UserRecord instance.
        """
        return self.__record

    def delete(self) -> None:
        """Delete this user from Roboto.

        Permanently removes the user and all associated data. This action
        cannot be undone.

        Raises:
            RobotoUnauthorizedException: The caller is not authorized to delete this user.
            RobotoNotFoundException: The user no longer exists.

        Examples:
            Delete the current user:

            >>> from roboto import User
            >>> user = User.for_self()
            >>> user.delete()  # Permanently removes the user
        """
        self.__roboto_client.delete(
            "v1/users", headers=roboto_headers(user_id=self.user_id)
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert this user to a dictionary representation.

        Returns a JSON-serializable dictionary containing all user data.

        Returns:
            Dictionary representation of the user.

        Examples:
            Export user data:

            >>> from roboto import User
            >>> user = User.for_self()
            >>> user_data = user.to_dict()
            >>> print(f"User created: {user_data.get('created')}")
        """
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
