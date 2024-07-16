# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing
import urllib.parse

from ...http import RobotoClient
from .org_invite import OrgInvite
from .org_operations import (
    CreateOrgRequest,
    UpdateOrgRequest,
    UpdateOrgUserRequest,
)
from .org_records import (
    OrgRecord,
    OrgRoleName,
    OrgStatus,
    OrgTier,
    OrgUserRecord,
)


class Org:
    __record: OrgRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        bind_email_domain: bool = False,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Org":
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateOrgRequest(name=name, bind_email_domain=bind_email_domain)
        record = roboto_client.post("v1/orgs", data=request).to_record(OrgRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "Org":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/orgs/id/{org_id}").to_record(OrgRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_self(
        cls, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Sequence["Org"]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get("v1/orgs/caller").to_record_list(OrgRecord)
        return [cls(record=record, roboto_client=roboto_client) for record in records]

    @classmethod
    def for_user(
        cls, user_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Sequence["Org"]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get(
            f"v1/users/id/{urllib.parse.quote_plus(user_id)}/orgs"
        ).to_record_list(OrgRecord)
        return [cls(record=record, roboto_client=roboto_client) for record in records]

    def __init__(
        self, record: OrgRecord, roboto_client: typing.Optional[RobotoClient] = None
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def org_id(self):
        return self.__record.org_id

    @property
    def status(self) -> OrgStatus:
        return self.__record.status

    @property
    def tier(self) -> OrgTier:
        return self.__record.tier

    def add_role_for_user(self, user_id: str, role: OrgRoleName) -> "Org":
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}",
            data=UpdateOrgUserRequest(add_roles=[role]),
        )
        return self

    def remove_role_from_user(self, user_id: str, role: OrgRoleName) -> "Org":
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}",
            data=UpdateOrgUserRequest(remove_roles=[role]),
        )
        return self

    def bind_email_domain(self, email_domain: str) -> "Org":
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/email_domains/id/{urllib.parse.quote_plus(email_domain)}"
        )
        return self

    def delete(self) -> None:
        self.__roboto_client.delete(f"v1/orgs/id/{self.org_id}")

    def email_domains(self) -> collections.abc.Collection[str]:
        return self.__roboto_client.get(
            f"v1/orgs/id/{self.org_id}/email_domains"
        ).to_dict(json_path=["data"])

    def invite_user(
        self,
        user_id: str,
    ) -> OrgInvite:
        return OrgInvite.create(
            invited_user_id=user_id,
            org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def invites(self) -> collections.abc.Collection[OrgInvite]:
        return OrgInvite.for_org(org_id=self.org_id, roboto_client=self.__roboto_client)

    def refresh(self) -> "Org":
        self.__record = self.__roboto_client.get(f"v1/orgs/id/{self.org_id}").to_record(
            OrgRecord
        )
        return self

    def remove_user(self, user_id: str) -> "Org":
        self.__roboto_client.delete(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}"
        )
        return self

    def update(self, update: UpdateOrgRequest) -> "Org":
        self.__record = self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}", data=update
        ).to_record(OrgRecord)
        return self

    def users(self) -> collections.abc.Collection[OrgUserRecord]:
        return self.__roboto_client.get(
            f"v1/orgs/id/{self.org_id}/users"
        ).to_record_list(OrgUserRecord)

    def unbind_email_domain(self, email_domain: str) -> "Org":
        self.__roboto_client.delete(
            f"v1/orgs/id/{self.org_id}/email_domains/id/{urllib.parse.quote_plus(email_domain)}"
        )
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")
