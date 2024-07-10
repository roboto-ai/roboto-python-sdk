# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from .org_records import OrgRoleName, OrgStatus


class CreateOrgRequest(pydantic.BaseModel):
    name: str
    bind_email_domain: bool = False


class OrgRecordUpdates(pydantic.BaseModel):
    name: typing.Optional[str] = None
    status: typing.Optional[OrgStatus] = None


class UpdateOrgRequest(pydantic.BaseModel):
    updates: OrgRecordUpdates


class UpdateOrgUserRequest(pydantic.BaseModel):
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
    user_id: str


# Deprecated
class ModifyRoleForUserRequest(pydantic.BaseModel):
    user_id: str
    role_name: OrgRoleName


class BindEmailDomainRequest(pydantic.BaseModel):
    email_domain: str


class InviteUserRequest(pydantic.BaseModel):
    invited_user_id: str
