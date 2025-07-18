# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import enum

import pydantic


class RobotoPrincipalType(str, enum.Enum):
    """Types of principals supported by the Roboto platform."""

    Device = "device"
    """See :py:class:`roboto.domain.devices.Device`."""

    Invocation = "invocation"
    """See :py:class:`roboto.domain.actions.Invocation`."""

    User = "user"
    """See :py:class:`roboto.domain.users.User`."""

    Org = "org"
    """See :py:class:`roboto.domain.orgs.Org`."""


class RobotoPrincipal(pydantic.BaseModel):
    """Represents a principal (user, organization, device, etc.) in the Roboto platform."""

    ptype: RobotoPrincipalType
    """The type of principal (user or organization)."""

    id: str
    """Fully qualified principal ID.

    For resources which have universally unique IDs (e.g. users, orgs, invocations, datasets, files, etc.) this will
    just be the resource ID.

    For resources which have org-unique IDs (e.g. devices, actions), this will be the resource ID + "@" + the org ID,
    e.g. a device ``sn001`` in org ``og_67890`` will have a fully qualified ID of ``sn001@og_67890``.
    """

    @pydantic.field_validator("id")
    def validate_id(cls, value: str) -> str:
        if ":" in value:
            raise ValueError(f"ID cannot contain a colon, got {value}")

        return value

    @classmethod
    def for_device(cls, device_id: str, org_id: str) -> "RobotoPrincipal":
        """Create a principal representing a device.

        Args:
            device_id: Unique identifier for the device.
            org_id: Organization ID that owns the device.

        Returns:
            A RobotoPrincipal instance configured for the specified device.
        """
        return RobotoPrincipal(
            ptype=RobotoPrincipalType.Device, id=f"{device_id}@{org_id}"
        )

    @classmethod
    def for_invocation(cls, invocation_id: str) -> "RobotoPrincipal":
        """Create a principal representing an invocation.

        Args:
            invocation_id: Unique identifier for the invocation.

        Returns:
            A RobotoPrincipal instance configured for the specified invocation.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Invocation, id=invocation_id)

    @classmethod
    def for_org(cls, org_id: str) -> "RobotoPrincipal":
        """Create a principal representing an organization.

        Args:
            org_id: Unique identifier for the organization.

        Returns:
            A RobotoPrincipal instance configured for the specified organization.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Org, id=org_id)

    @classmethod
    def for_user(cls, user_id: str) -> "RobotoPrincipal":
        """Create a principal representing a user.

        Args:
            user_id: Unique identifier for the user.

        Returns:
            A RobotoPrincipal instance configured for the specified user.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.User, id=user_id)

    @classmethod
    def from_string(cls, serialized_principal: str) -> RobotoPrincipal:
        """Create a principal from a serialized string representation.

        Args:
            serialized_principal: String in format "ptype:id".

        Returns:
            A RobotoPrincipal instance parsed from the string.

        Raises:
            ValueError: If the serialized principal is not in the correct format.
        """
        return RobotoPrincipal(
            ptype=RobotoPrincipalType(serialized_principal.split(":")[0]),
            id=serialized_principal.split(":")[1],
        )

    def __str__(self):
        """Serialize the principal to a string representation.

        Returns:
            String representation of the principal in format "ptype:id".
        """
        return f"{self.ptype.value}:{self.id}"
