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
    """An invitation to join an organization from one user to another.

    Organization invitations allow existing members to invite new users to join
    their organization. Invitations are created by calling :py:meth:`Org.invite_user`
    and can be accepted or declined by the invited user.

    Invitations cannot be created directly through the constructor - they must
    be created through the organization's invite_user method.
    """

    __record: OrgInviteRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        invited_user_id: str,
        org_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "OrgInvite":
        """Create a new organization invitation.

        Creates an invitation for the specified user to join the organization.
        This method is typically called internally by :py:meth:`Org.invite_user`.

        Args:
            invited_user_id: Unique identifier for the user to invite.
            org_id: Unique identifier for the organization.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A new OrgInvite instance representing the created invitation.

        Raises:
            RobotoNotFoundException: The user or organization does not exist.
            RobotoInvalidRequestException: The user is already a member or has a pending invite.
            RobotoUnauthorizedException: The caller lacks permission to invite users.

        Examples:
            Create an invitation (typically done via Org.invite_user):

            >>> from roboto import OrgInvite
            >>> invite = OrgInvite.create("alice@example.com", "org_12345")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post(
            f"v1/orgs/id/{org_id}/users/id/{invited_user_id}/invites"
        ).to_record(OrgInviteRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, invite_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "OrgInvite":
        """Load an existing invitation by its unique ID.

        Args:
            invite_id: Unique identifier for the invitation to retrieve.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            OrgInvite instance for the specified invitation ID.

        Raises:
            RobotoNotFoundException: No invitation exists with the specified ID.
            RobotoUnauthorizedException: The caller is not authorized to access this invitation.

        Examples:
            Load an invitation by ID:

            >>> from roboto import OrgInvite
            >>> invite = OrgInvite.from_id("invite_12345")
            >>> print(f"Invited user: {invite.invited_user_id}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/orgs/invites/id/{invite_id}").to_record(
            OrgInviteRecord
        )
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Collection["OrgInvite"]:
        """Retrieve all pending invitations for an organization.

        Args:
            org_id: Unique identifier for the organization.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            Collection of OrgInvite instances for pending invitations.

        Raises:
            RobotoNotFoundException: The organization does not exist.
            RobotoUnauthorizedException: The caller lacks permission to view invitations.

        Examples:
            List all invitations for an organization:

            >>> from roboto import OrgInvite
            >>> invites = OrgInvite.for_org("org_12345")
            >>> for invite in invites:
            ...     print(f"Pending invite for: {invite.invited_user_id}")
        """
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
        """Unique identifier for this invitation.

        Returns:
            The invitation's unique ID.
        """
        return self.__record.invite_id

    @property
    def invited_user_id(self) -> str:
        """User ID of the person who was invited.

        Returns:
            The unique identifier of the invited user.
        """
        return self.__record.user_id

    @property
    def invited_by_user_id(self) -> str:
        """User ID of the person who created this invitation.

        Returns:
            The unique identifier of the user who sent the invitation.
        """
        return self.__record.invited_by.user_id

    @property
    def org_id(self) -> str:
        """Organization ID for the organization this invitation is for.

        Returns:
            The unique identifier of the organization.
        """
        return self.__record.org.org_id

    def accept(self) -> None:
        """Accept this invitation and join the organization.

        The invited user becomes a member of the organization with default
        user role permissions.

        Raises:
            RobotoUnauthorizedException: The caller is not the invited user.
            RobotoInvalidRequestException: The invitation has already been accepted or declined.

        Examples:
            Accept an invitation:

            >>> from roboto import OrgInvite
            >>> invite = OrgInvite.from_id("invite_12345")
            >>> invite.accept()  # Join the organization
        """
        self.__roboto_client.post(f"v1/orgs/invites/id/{self.invite_id}/accept")

    def decline(self) -> None:
        """Decline this invitation and do not join the organization.

        The invitation is marked as declined and cannot be accepted later.

        Raises:
            RobotoUnauthorizedException: The caller is not the invited user.
            RobotoInvalidRequestException: The invitation has already been accepted or declined.

        Examples:
            Decline an invitation:

            >>> from roboto import OrgInvite
            >>> invite = OrgInvite.from_id("invite_12345")
            >>> invite.decline()  # Do not join the organization
        """
        self.__roboto_client.post(f"v1/orgs/invites/id/{self.invite_id}/decline")

    def to_dict(self) -> dict[str, typing.Any]:
        """Convert this invitation to a dictionary representation.

        Returns a JSON-serializable dictionary containing all invitation data.

        Returns:
            Dictionary representation of the invitation.

        Examples:
            Export invitation data:

            >>> from roboto import OrgInvite
            >>> invite = OrgInvite.from_id("invite_12345")
            >>> invite_data = invite.to_dict()
            >>> print(f"Invited user: {invite_data.get('user_id')}")
        """
        return self.__record.model_dump(mode="json")
