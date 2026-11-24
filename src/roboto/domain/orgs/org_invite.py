# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

from ...exceptions import RobotoInvalidRequestException
from ...http import RobotoClient
from .org_operations import CreateOrgInviteRequest
from .org_records import OrgInviteRecord, OrgInviteStatus, OrgRoleName


class OrgInvite:
    """An invitation for a user to join an organization.

    A member of an organization can invite a user with :py:meth:`~roboto.domain.orgs.Org.invite_user` or ``create``,
    unless the Roboto deployment lets only organization administrators invite, and Roboto emails the invitation to that
    user. The invited user accepts it with ``accept`` or declines it with ``decline``; the member who sent it, or an
    organization administrator, revokes it with ``decline``. Roboto keeps the invitation after that, and its ``status``
    says what became of it. Fetch existing invitations with ``from_id`` or ``for_org``.
    """

    __record: OrgInviteRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        invited_user_id: str,
        org_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        *,
        role: OrgRoleName = OrgRoleName.user,
    ) -> "OrgInvite":
        """Invite a user to join an organization.

        Roboto emails the invitation to the invited user. :py:meth:`~roboto.domain.orgs.Org.invite_user` does the same
        for an organization you already hold as an :py:class:`~roboto.domain.orgs.Org`. The invitation expires 14 days
        after it is sent.

        Args:
            invited_user_id: Email address of the user to invite, which is their user ID. The user does not need a
                Roboto account yet.
            org_id: ID of the organization to invite the user to.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            role: Role the invited user gets by accepting. Only an organization owner or a Roboto administrator may
                invite someone as :py:attr:`~roboto.domain.orgs.OrgRoleName.admin`, and no invitation may carry
                ``owner``.

        Returns:
            The new invitation.

        Raises:
            RobotoNotFoundException: No organization has this ID.
            RobotoInvalidRequestException: ``role`` is ``owner``; the user is already a member of the organization or
                is a service user; the user's email address is outside the email domains the Roboto deployment
                accepts; or the deployment does not support invitation roles, in which case it still created the
                invitation, with the ``user`` role, and declining the invitation withdraws it.
            RobotoConflictException: The user already has a pending invitation to the organization.
            RobotoLimitExceededException: The organization's members and pending invitations already reach its limit
                on members.
            RobotoUnauthorizedException: ``role`` is ``admin`` and the caller is not an owner of the organization, or
                the Roboto deployment lets only organization administrators invite users and the caller is not one.

        Examples:
            >>> from roboto.domain.orgs import OrgInvite
            >>> invite = OrgInvite.create("alice@example.com", "og_12345")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post(
            f"v1/orgs/id/{org_id}/users/id/{urllib.parse.quote_plus(invited_user_id)}/invites",
            data=None if role == OrgRoleName.user else CreateOrgInviteRequest(role=role),
        ).to_record(OrgInviteRecord)
        if record.role != role:
            raise RobotoInvalidRequestException(
                f"The invitation {record.invite_id} was created with the role '{record.role}' instead of '{role}', "
                "because this Roboto deployment does not support invitation roles. Decline it to withdraw it."
            )
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(cls, invite_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> "OrgInvite":
        """Fetch an invitation by its ID.

        Only the invited user and members of the invitation's organization can fetch it. It is returned in any status,
        so an invitation already accepted, declined, revoked, or expired can still be fetched.

        Args:
            invite_id: Unique ID of the invitation, beginning with ``in_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No invitation has this ID.
            RobotoUnauthorizedException: The caller is neither the invited user nor a member of the invitation's
                organization.

        Examples:
            >>> from roboto.domain.orgs import OrgInvite
            >>> invite = OrgInvite.from_id("in_12345")
            >>> print(invite.invited_user_id)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/orgs/invites/id/{invite_id}").to_record(OrgInviteRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Collection["OrgInvite"]:
        """List an organization's pending invitations, oldest first.

        Pending invitations past their expiry are included, with the status
        :py:attr:`~roboto.domain.orgs.OrgInviteStatus.Expired`.

        Args:
            org_id: ID of the organization whose invitations to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            >>> from roboto.domain.orgs import OrgInvite
            >>> for invite in OrgInvite.for_org("og_12345"):
            ...     print(invite.invited_user_id)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get(f"v1/orgs/id/{org_id}/invites").to_record_list(OrgInviteRecord)
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
        """Unique ID of the invitation, beginning with ``in_``."""
        return self.__record.invite_id

    @property
    def invited_user_id(self) -> str:
        """ID of the invited user, which for a person is their email address."""
        return self.__record.user_id

    @property
    def invited_by_user_id(self) -> str:
        """ID of the user who sent the invitation."""
        return self.__record.invited_by.user_id

    @property
    def org_id(self) -> str:
        """ID of the organization the invitation is to join."""
        return self.__record.org.org_id

    @property
    def role(self) -> OrgRoleName:
        """Role the invited user gets in the organization by accepting."""
        return self.__record.role

    @property
    def status(self) -> OrgInviteStatus:
        """Status of the invitation when Roboto read it.

        :py:attr:`~roboto.domain.orgs.OrgInviteRecord.status` says how expiry shows in it.
        """
        return self.__record.status

    @property
    def expires_at(self) -> typing.Optional[datetime.datetime]:
        """Time after which the invitation cannot be accepted, unless an organization administrator renews it.

        :py:attr:`~roboto.domain.orgs.OrgInviteRecord.expires_at` says when it is ``None``.
        """
        return self.__record.expires_at

    def accept(self) -> None:
        """Accept this invitation, making the invited user a member of the organization.

        Only the invited user can accept it. The new member gets the invitation's ``role``, and a user who is already
        a member keeps their roles. If Roboto has not finished setting up the organization, the user still joins it but
        cannot work in it yet, and the method raises ``RobotoServiceUnavailableException``: try accepting again in a
        few minutes, and if the organization is still not set up, contact the administrator that the exception's
        message names. Once the organization is set up, accepting again changes nothing.

        The method also raises ``RobotoServiceUnavailableException`` when another request was changing the invitation,
        the caller's account, or the organization at the same time, or when the Roboto deployment has not set the email
        domains it accepts; the exception's message says which. The SDK retries the request before it raises this
        exception, and accepting again adds no second membership and changes no role.

        Raises:
            RobotoUnauthorizedException: The caller is not the invited user, has not verified the invited email
                address, or is acting as another user.
            RobotoConflictException: The invitation was declined or revoked; a newer invitation to the same address
                replaced it; or it carries the ``owner`` role and no longer makes the user who accepts it the
                organization's first owner.
            RobotoExpiredException: The invitation has expired.
            RobotoInvalidRequestException: The invited email address is outside the email domains the Roboto
                deployment accepts.
            RobotoLimitExceededException: The organization already has as many members as it may, or the invitation
                carries the ``owner`` role and the caller already owns as many organizations as they may.

        Examples:
            >>> from roboto.domain.orgs import OrgInvite
            >>> invite = OrgInvite.from_id("in_12345")
            >>> invite.accept()
        """
        self.__roboto_client.post(f"v1/orgs/invites/id/{self.invite_id}/accept")

    def decline(self) -> None:
        """Decline this invitation as the invited user, or revoke it as its sender or an organization administrator.

        Either way, the invitation can no longer be accepted, and its status becomes
        :py:attr:`~roboto.domain.orgs.OrgInviteStatus.Declined` or ``Revoked``. Repeating the call changes nothing.

        Raises:
            RobotoUnauthorizedException: The caller is not the invited user, the user who sent the invitation, or an
                administrator or owner of the organization.
            RobotoConflictException: The invitation was already accepted; a newer invitation to the same address
                replaced it; the invited user declines an invitation that was revoked, or the sender or an
                administrator revokes one that was declined; or the caller would revoke an invitation that carries the
                ``owner`` role.
            RobotoExpiredException: The invitation has expired.

        Examples:
            >>> from roboto.domain.orgs import OrgInvite
            >>> invite = OrgInvite.from_id("in_12345")
            >>> invite.decline()
        """
        self.__roboto_client.post(f"v1/orgs/invites/id/{self.invite_id}/decline")

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the invitation's record as a JSON-compatible dictionary.

        Returns:
            :py:class:`~roboto.domain.orgs.OrgInviteRecord` of the invitation, as a JSON-compatible dictionary.

        Examples:
            >>> from roboto.domain.orgs import OrgInvite
            >>> invite = OrgInvite.from_id("in_12345")
            >>> print(invite.to_dict()["user_id"])
        """
        return self.__record.model_dump(mode="json")
