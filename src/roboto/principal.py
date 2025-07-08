# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum

import pydantic


class RobotoPrincipalType(str, enum.Enum):
    """Types of principals supported by the Roboto platform."""

    User = "user"
    """Individual user."""

    Org = "org"
    """Entire organization."""


class RobotoPrincipal(pydantic.BaseModel):
    """Represents a principal (user or organization) in the Roboto platform.

    A principal is an entity that can perform actions, own resources, or be granted
    permissions within the Roboto platform. This class provides a unified way to
    represent both users and organizations.
    """

    ptype: RobotoPrincipalType
    """The type of principal (user or organization)."""

    id: str
    """Unique identifier for the principal."""

    @classmethod
    def for_user(cls, user_id: str) -> "RobotoPrincipal":
        """Create a principal representing a user.

        Args:
            user_id: Unique identifier for the user.

        Returns:
            A RobotoPrincipal instance configured for the specified user.

        Examples:
            Create a principal for a user:

            >>> from roboto.principal import RobotoPrincipal
            >>> user_principal = RobotoPrincipal.for_user("user_12345")
            >>> print(user_principal.ptype)
            RobotoPrincipalType.User
            >>> print(user_principal.id)
            user_12345
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.User, id=user_id)

    @classmethod
    def for_org(cls, org_id: str) -> "RobotoPrincipal":
        """Create a principal representing an organization.

        Args:
            org_id: Unique identifier for the organization.

        Returns:
            A RobotoPrincipal instance configured for the specified organization.

        Examples:
            Create a principal for an organization:

            >>> from roboto.principal import RobotoPrincipal
            >>> org_principal = RobotoPrincipal.for_org("org_67890")
            >>> print(org_principal.ptype)
            RobotoPrincipalType.Org
            >>> print(org_principal.id)
            org_67890
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Org, id=org_id)
