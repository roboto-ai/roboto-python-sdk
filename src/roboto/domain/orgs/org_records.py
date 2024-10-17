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
    """
    Org status enum
    """

    Provisioning = "provisioning"
    Active = "active"
    Deprovisioning = "de-provisioning"


class OrgTier(str, enum.Enum):
    """
    See our pricing page for details on different organization tiers.
    """

    free = "free"
    premium = "premium"


class OrgRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of an organization.
    """

    org_id: str
    name: str
    tier: OrgTier
    status: OrgStatus
    created: datetime.datetime
    created_by: typing.Optional[str] = None


class OrgRoleName(str, enum.Enum):
    """
    Org role enum
    """

    user = "user"
    admin = "admin"
    owner = "owner"


class OrgUserRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of an organization user.
    """

    user: UserRecord
    org: OrgRecord
    roles: list[OrgRoleName]


class OrgInviteRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of an organization invite.
    """

    invite_id: str
    user_id: str
    invited_by: UserRecord
    org: OrgRecord
