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
    """
    Request payload to create an organization
    """

    name: str
    bind_email_domain: bool = False
    data_region: RobotoRegion = RobotoRegion.US_WEST


class OrgRecordUpdates(pydantic.BaseModel):
    """
    Payload to update an organization
    """

    name: typing.Optional[str] = None
    status: typing.Optional[OrgStatus] = None


class UpdateOrgRequest(pydantic.BaseModel):
    """
    Request payload to update an organization
    """

    updates: OrgRecordUpdates


class UpdateOrgUserRequest(pydantic.BaseModel):
    """
    Request payload to update an organization user
    """

    add_roles: typing.Optional[list[OrgRoleName]] = None
    remove_roles: typing.Optional[list[OrgRoleName]] = None

    @pydantic.model_validator(mode="after")
    def check_some_updates_present(self) -> "UpdateOrgUserRequest":
        if len(self.add_roles or []) == 0 and len(self.remove_roles or []) == 0:
            raise ValueError(
                "At least one role should be included in add_roles or remove_roles"
            )

        return self


class RemoveUserFromOrgRequest(pydantic.BaseModel):
    """
    Request payload to remove a user from an organization
    """

    user_id: str


# Deprecated
class ModifyRoleForUserRequest(pydantic.BaseModel):
    """
    Request payload to modify the role for a user in an organization
    """

    user_id: str
    role_name: OrgRoleName


class BindEmailDomainRequest(pydantic.BaseModel):
    """
    Request payload to bind an email domain to an organization
    """

    email_domain: str


class InviteUserRequest(pydantic.BaseModel):
    """
    Request payload to invite a user to an organization
    """

    invited_user_id: str
