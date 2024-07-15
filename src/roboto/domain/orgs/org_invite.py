# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...http import RobotoClient
from .org_records import OrgInviteRecord


class OrgInvite:
    __record: OrgInviteRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        invited_user_id: str,
        org_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "OrgInvite":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post(
            f"v1/orgs/id/{org_id}/users/id/{invited_user_id}/invites"
        ).to_record(OrgInviteRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, invite_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ):
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/orgs/invites/id/{invite_id}").to_record(
            OrgInviteRecord
        )
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Collection["OrgInvite"]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get(f"v1/orgs/id/{org_id}/invites").to_record_list(
            OrgInviteRecord
        )
        return [cls(record=record, roboto_client=roboto_client) for record in records]

    def __init__(
        self,
        record: OrgInviteRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def invite_id(self) -> str:
        return self.__record.invite_id

    @property
    def invited_user_id(self) -> str:
        return self.__record.user_id

    @property
    def invited_by_user_id(self) -> str:
        return self.__record.invited_by.user_id

    @property
    def org_id(self) -> str:
        return self.__record.org.org_id

    def accept(self) -> None:
        self.__roboto_client.post(f"v1/orgs/invites/id/{self.invite_id}/accept")

    def decline(self) -> None:
        self.__roboto_client.post(f"v1/orgs/invites/id/{self.invite_id}/decline")

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")
