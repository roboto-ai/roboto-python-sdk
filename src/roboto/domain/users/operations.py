# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from roboto.notifications import (
    NotificationChannel,
    NotificationType,
)


class CreateUserRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.users.User.create`.

    Only Roboto administrators may send it.

    A ``user_id`` that already belongs to a user raises ``RobotoConflictException``. ``is_system_user`` set to
    ``True`` by any caller other than Roboto's own services raises ``RobotoUnauthorizedException``.
    """

    user_id: str
    """Unique ID of the user, which for a person is their email address.

    Roboto stores it lowercased, after Unicode NFKC normalization.
    """

    name: Optional[str] = None
    """Human-readable name of the user."""

    is_service_user: bool = False
    """Whether the user is a service user: an account that acts for an organization rather than a person.

    A trigger, for example, can invoke its action as a service user.
    """

    is_system_user: bool = False
    """Whether to create the user as Roboto staff, such as a Roboto administrator."""

    picture_url: Optional[str] = None
    """URL of the user's profile picture."""

    default_notification_channels: Optional[list[NotificationChannel]] = [NotificationChannel.Email]
    """Notification channels to enable for the user.

    Every other channel starts disabled. ``None`` or an empty list enables none.
    """

    default_notification_types: Optional[list[NotificationType]] = [NotificationType.CommentMention]
    """Notification types to enable for the user.

    Every other type starts disabled. ``None`` or an empty list enables none.
    """


class UpdateUserRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.users.User.update`.

    A field left ``None`` is unchanged. Constructing the model raises ``pydantic.ValidationError`` when ``name`` or
    ``picture_url`` is an empty string.
    """

    name: Optional[str] = None
    """Human-readable name to set on the user."""

    picture_url: Optional[str] = None
    """URL of the profile picture to set on the user."""

    notification_channels_enabled: Optional[dict[NotificationChannel, bool]] = None
    """Whether each notification channel is enabled for the user.

    Replaces the user's whole mapping, so a channel left out is disabled. An empty mapping, like ``None``, leaves it
    unchanged.
    """

    notification_types_enabled: Optional[dict[NotificationType, bool]] = None
    """Whether each notification type is enabled for the user.

    Replaces the user's whole mapping, so a type left out is disabled. An empty mapping, like ``None``, leaves it
    unchanged.
    """

    @pydantic.field_validator("name", "picture_url")
    @classmethod
    def validate_non_empty_string(
        cls,
        value: Optional[str],
        info: pydantic.ValidationInfo,
    ) -> Optional[str]:
        """Reject an empty ``name`` or ``picture_url``.

        Pydantic calls this while it builds the request.
        """
        if value == "":
            raise ValueError(f"{info.field_name} cannot be empty")

        return value
