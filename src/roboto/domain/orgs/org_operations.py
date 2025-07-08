# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...regionalization import RobotoRegion
from .org_records import OrgRoleName, OrgStatus


class CreateOrgRequest(pydantic.BaseModel):
    """Request payload to create an organization."""

    name: str
    """Unique name for the organization."""

    bind_email_domain: bool = False
    """Whether to automatically bind the creator's email domain to this organization."""

    data_region: RobotoRegion = RobotoRegion.US_WEST
    """AWS region where the organization's data will be stored."""


class OrgRecordUpdates(pydantic.BaseModel):
    """Payload containing organization field updates."""

    name: typing.Optional[str] = None
    """Updated name for the organization."""

    status: typing.Optional[OrgStatus] = None
    """Updated status for the organization."""


class UpdateOrgRequest(pydantic.BaseModel):
    """Request payload to update an organization."""

    updates: OrgRecordUpdates
    """Organization field updates to apply."""


class UpdateOrgUserRequest(pydantic.BaseModel):
    """Request payload to update an organization user's roles."""

    add_roles: typing.Optional[list[OrgRoleName]] = None
    """Roles to add to the user."""

    remove_roles: typing.Optional[list[OrgRoleName]] = None
    """Roles to remove from the user."""

    @pydantic.model_validator(mode="after")
    def check_some_updates_present(self) -> "UpdateOrgUserRequest":
        if len(self.add_roles or []) == 0 and len(self.remove_roles or []) == 0:
            raise ValueError(
                "At least one role should be included in add_roles or remove_roles"
            )

        return self


class RemoveUserFromOrgRequest(pydantic.BaseModel):
    """Request payload to remove a user from an organization."""

    user_id: str
    """Unique identifier for the user to remove."""


# Deprecated
class ModifyRoleForUserRequest(pydantic.BaseModel):
    """Request payload to modify the role for a user in an organization.

    .. deprecated::
        Use :py:class:`UpdateOrgUserRequest` instead.
    """

    user_id: str
    """Unique identifier for the user."""

    role_name: OrgRoleName
    """Role to assign to the user."""


class BindEmailDomainRequest(pydantic.BaseModel):
    """Request payload to bind an email domain to an organization."""

    email_domain: str
    """Email domain to bind (e.g., "example.com")."""


class InviteUserRequest(pydantic.BaseModel):
    """Request payload to invite a user to an organization."""

    invited_user_id: str
    """Unique identifier for the user to invite."""
