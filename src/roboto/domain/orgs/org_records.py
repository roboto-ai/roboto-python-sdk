# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

from ..users import UserRecord


class OrgStatus(str, enum.Enum):
    """Organization status enumeration.

    Represents the current operational state of an organization.
    """

    Provisioning = "provisioning"
    """Organization is being set up and is not yet ready for use."""

    Active = "active"
    """Organization is fully operational and ready for use."""

    Deprovisioning = "de-provisioning"
    """Organization is being deleted and resources are being cleaned up."""


class OrgTier(str, enum.Enum):
    """Organization tier enumeration.

    See our pricing page for details on different organization tiers and
    their associated features and limits.
    """

    free = "free"
    """Free tier with basic features and usage limits."""

    premium = "premium"
    """Premium tier with advanced features and higher usage limits."""


class OrgRecord(pydantic.BaseModel):
    """A wire-transmissible representation of an organization."""

    org_id: str
    """Unique identifier for the organization."""

    name: str
    """Human-readable name of the organization."""

    tier: OrgTier
    """Subscription tier of the organization."""

    status: OrgStatus
    """Current operational status of the organization."""

    created: datetime.datetime
    """Timestamp when the organization was created."""

    created_by: typing.Optional[str] = None
    """User ID of the organization creator."""


class OrgRoleName(str, enum.Enum):
    """Organization role enumeration.

    Defines the different permission levels users can have within an organization.
    """

    user = "user"
    """Basic user role with read access to organization resources."""

    admin = "admin"
    """Administrative role with management permissions for organization resources."""

    owner = "owner"
    """Owner role with full control over the organization including billing and deletion."""


class OrgUserRecord(pydantic.BaseModel):
    """A wire-transmissible representation of an organization user."""

    user: UserRecord
    """User information for the organization member."""

    org: OrgRecord
    """Organization information."""

    roles: list[OrgRoleName]
    """List of roles the user has within the organization."""


class OrgInviteRecord(pydantic.BaseModel):
    """A wire-transmissible representation of an organization invite."""

    invite_id: str
    """Unique identifier for the invitation."""

    user_id: str
    """User ID of the person who was invited."""

    invited_by: UserRecord
    """User information for the person who created the invitation."""

    org: OrgRecord
    """Organization information for the organization being invited to."""
