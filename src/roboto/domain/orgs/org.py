# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing
import urllib.parse

from ...http import RobotoClient
from ...regionalization import RobotoRegion
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
    """A collaborative workspace for multiple Roboto users.

    Organizations are the primary grouping mechanism in Roboto, allowing multiple
    users to collaborate on datasets, actions, and other resources. Each organization
    has its own isolated namespace for resources and can have different limits and
    functionality depending on its tier (free or premium).

    Organization names are unique within the Roboto platform. Users can be
    members of multiple organizations with different roles (user, admin, owner).
    Organizations can also be configured with email domain binding to automatically
    add users with matching email domains.
    """

    __record: OrgRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        bind_email_domain: bool = False,
        data_region: RobotoRegion = RobotoRegion.US_WEST,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Org":
        """Create a new organization.

        Creates a new organization with the specified name and configuration.

        Args:
            name: Name for the organization.
            bind_email_domain: Whether to automatically bind the email domain
                from the creator's email address to this organization.
            data_region: Geographic region where the organization's data will be stored.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A new Org instance representing the created organization.

        Raises:
            RobotoInvalidRequestException: The request contains invalid data.
            RobotoUnauthorizedException: The caller is not authorized to create organizations.

        Examples:
            Create a basic organization:

            >>> from roboto import Org
            >>> org = Org.create("my-company")
            >>> print(f"Created org: {org.name}")

            Create an organization with email domain binding:

            >>> from roboto import Org, RobotoRegion
            >>> org = Org.create(
            ...     name="acme-corp",
            ...     bind_email_domain=True,
            ...     data_region=RobotoRegion.EU_WEST
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateOrgRequest(
            name=name, bind_email_domain=bind_email_domain, data_region=data_region
        )
        record = roboto_client.post("v1/orgs", data=request).to_record(OrgRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "Org":
        """Load an existing organization by its unique ID.

        Args:
            org_id: Unique identifier for the organization to retrieve.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            Org instance for the specified organization ID.

        Raises:
            RobotoNotFoundException: No organization exists with the specified ID.
            RobotoUnauthorizedException: The caller is not authorized to access this organization.

        Examples:
            Load an organization by ID:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> print(f"Organization: {org.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/orgs/id/{org_id}").to_record(OrgRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_self(
        cls, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Sequence["Org"]:
        """Retrieve all organizations the current user is a member of.

        Args:
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            Sequence of Org instances for organizations the user belongs to.

        Raises:
            RobotoUnauthorizedException: No valid authentication credentials provided.

        Examples:
            List user's organizations:

            >>> from roboto import Org
            >>> orgs = Org.for_self()
            >>> for org in orgs:
            ...     print(f"Member of: {org.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get("v1/orgs/caller").to_record_list(OrgRecord)
        return [cls(record=record, roboto_client=roboto_client) for record in records]

    @classmethod
    def for_user(
        cls, user_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Sequence["Org"]:
        """Retrieve all organizations a specific user is a member of.

        Args:
            user_id: Unique identifier for the user.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            Sequence of Org instances for organizations the user belongs to.

        Raises:
            RobotoNotFoundException: No user exists with the specified ID.
            RobotoUnauthorizedException: The caller is not authorized to view this user's organizations.

        Examples:
            List another user's organizations:

            >>> from roboto import Org
            >>> orgs = Org.for_user("alice@example.com")
            >>> print(f"Alice is in {len(orgs)} organizations")
        """
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
        """Human-readable name of this organization.

        Returns:
            The organization's name.
        """
        return self.__record.name

    @property
    def org_id(self):
        """Unique identifier for this organization.

        Returns:
            The organization's unique ID.
        """
        return self.__record.org_id

    @property
    def status(self) -> OrgStatus:
        """Current status of this organization.

        Returns:
            The organization's status (provisioning, active, or de-provisioning).
        """
        return self.__record.status

    @property
    def tier(self) -> OrgTier:
        """Subscription tier of this organization.

        Returns:
            The organization's tier (free or premium).
        """
        return self.__record.tier

    def add_role_for_user(self, user_id: str, role: OrgRoleName) -> "Org":
        """Add a role to a user in this organization.

        Grants the specified role to a user who is already a member of the organization.
        Users can have multiple roles simultaneously.

        Args:
            user_id: Unique identifier for the user.
            role: Role to add (user, admin, or owner).

        Returns:
            This Org instance for method chaining.

        Raises:
            RobotoNotFoundException: The user is not a member of this organization.
            RobotoUnauthorizedException: The caller lacks permission to modify user roles.

        Examples:
            Grant admin role to a user:

            >>> from roboto import Org, OrgRoleName
            >>> org = Org.from_id("org_12345")
            >>> org.add_role_for_user("alice@example.com", OrgRoleName.admin)
        """
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}",
            data=UpdateOrgUserRequest(add_roles=[role]),
            caller_org_id=self.org_id,
        )
        return self

    def remove_role_from_user(self, user_id: str, role: OrgRoleName) -> "Org":
        """Remove a role from a user in this organization.

        Revokes the specified role from a user. The user remains a member of the
        organization unless all roles are removed.

        Args:
            user_id: Unique identifier for the user.
            role: Role to remove (user, admin, or owner).

        Returns:
            This Org instance for method chaining.

        Raises:
            RobotoNotFoundException: The user is not a member of this organization.
            RobotoUnauthorizedException: The caller lacks permission to modify user roles.

        Examples:
            Remove admin role from a user:

            >>> from roboto import Org, OrgRoleName
            >>> org = Org.from_id("org_12345")
            >>> org.remove_role_from_user("alice@example.com", OrgRoleName.admin)
        """
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}",
            data=UpdateOrgUserRequest(remove_roles=[role]),
        )
        return self

    def bind_email_domain(self, email_domain: str) -> "Org":
        """Bind an email domain to this organization.

        Users with email addresses from the bound domain will automatically
        be added to this organization when they sign up for Roboto.

        Args:
            email_domain: Email domain to bind (e.g., "example.com").

        Returns:
            This Org instance for method chaining.

        Raises:
            RobotoInvalidRequestException: The email domain is invalid or already bound.
            RobotoUnauthorizedException: The caller lacks permission to bind email domains.

        Examples:
            Bind a company email domain:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> org.bind_email_domain("acme.com")
        """
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/email_domains/id/{urllib.parse.quote_plus(email_domain)}"
        )
        return self

    def delete(self) -> None:
        """Delete this organization permanently.

        Permanently removes the organization and all associated data including
        datasets, actions, and user memberships. This action cannot be undone.

        Raises:
            RobotoUnauthorizedException: The caller lacks permission to delete this organization.
            RobotoInvalidRequestException: The organization cannot be deleted due to active resources.

        Examples:
            Delete an organization:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> org.delete()  # Permanently removes the organization
        """
        self.__roboto_client.delete(f"v1/orgs/id/{self.org_id}")

    def email_domains(self) -> collections.abc.Collection[str]:
        """Retrieve all email domains bound to this organization.

        Returns:
            Collection of email domain strings bound to this organization.

        Raises:
            RobotoUnauthorizedException: The caller lacks permission to view email domains.

        Examples:
            List bound email domains:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> domains = org.email_domains()
            >>> for domain in domains:
            ...     print(f"Bound domain: {domain}")
        """
        return self.__roboto_client.get(
            f"v1/orgs/id/{self.org_id}/email_domains"
        ).to_dict(json_path=["data"])

    def invite_user(
        self,
        user_id: str,
    ) -> OrgInvite:
        """Invite a user to join this organization.

        Creates an invitation that the specified user can accept to become
        a member of this organization.

        Args:
            user_id: Unique identifier for the user to invite.

        Returns:
            OrgInvite instance representing the created invitation.

        Raises:
            RobotoNotFoundException: The specified user does not exist.
            RobotoInvalidRequestException: The user is already a member or has a pending invite.
            RobotoUnauthorizedException: The caller lacks permission to invite users.

        Examples:
            Invite a user to the organization:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> invite = org.invite_user("alice@example.com")
            >>> print(f"Invitation created: {invite.invite_id}")
        """
        return OrgInvite.create(
            invited_user_id=user_id,
            org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def invites(self) -> collections.abc.Collection[OrgInvite]:
        """Retrieve all pending invitations for this organization.

        Returns:
            Collection of OrgInvite instances for pending invitations.

        Raises:
            RobotoUnauthorizedException: The caller lacks permission to view invitations.

        Examples:
            List pending invitations:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> invites = org.invites()
            >>> for invite in invites:
            ...     print(f"Pending invite for: {invite.invited_user_id}")
        """
        return OrgInvite.for_org(org_id=self.org_id, roboto_client=self.__roboto_client)

    def refresh(self) -> "Org":
        """Refresh this organization's data from the server.

        Fetches the latest organization data from Roboto and updates this
        instance's internal state.

        Returns:
            This Org instance with updated data.

        Raises:
            RobotoNotFoundException: The organization no longer exists.
            RobotoUnauthorizedException: The caller no longer has access to this organization.

        Examples:
            Refresh organization data:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> org.refresh()  # Updates with latest data from server
        """
        self.__record = self.__roboto_client.get(f"v1/orgs/id/{self.org_id}").to_record(
            OrgRecord
        )
        return self

    def remove_user(self, user_id: str) -> "Org":
        """Remove a user from this organization.

        Completely removes the user from the organization, revoking all roles
        and access to organization resources.

        Args:
            user_id: Unique identifier for the user to remove.

        Returns:
            This Org instance for method chaining.

        Raises:
            RobotoNotFoundException: The user is not a member of this organization.
            RobotoUnauthorizedException: The caller lacks permission to remove users.

        Examples:
            Remove a user from the organization:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> org.remove_user("alice@example.com")
        """
        self.__roboto_client.delete(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}"
        )
        return self

    def update(self, update: UpdateOrgRequest) -> "Org":
        """Update this organization's properties.

        Updates the organization with the provided changes and refreshes
        this instance with the updated data.

        Args:
            update: Update request containing the changes to apply.

        Returns:
            This Org instance with updated data.

        Raises:
            RobotoInvalidRequestException: The update contains invalid data.
            RobotoUnauthorizedException: The caller lacks permission to update this organization.

        Examples:
            Update organization name:

            >>> from roboto import Org, UpdateOrgRequest, OrgRecordUpdates
            >>> org = Org.from_id("org_12345")
            >>> update = UpdateOrgRequest(
            ...     updates=OrgRecordUpdates(name="New Company Name")
            ... )
            >>> org.update(update)
        """
        self.__record = self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}", data=update
        ).to_record(OrgRecord)
        return self

    def users(self) -> collections.abc.Collection[OrgUserRecord]:
        """Retrieve all users who are members of this organization.

        Returns:
            Collection of OrgUserRecord instances representing organization members.

        Raises:
            RobotoUnauthorizedException: The caller lacks permission to view organization members.

        Examples:
            List organization members:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> users = org.users()
            >>> for user_record in users:
            ...     print(f"Member: {user_record.user.name} ({user_record.roles})")
        """
        return self.__roboto_client.get(
            f"v1/orgs/id/{self.org_id}/users"
        ).to_record_list(OrgUserRecord)

    def unbind_email_domain(self, email_domain: str) -> "Org":
        """Remove an email domain binding from this organization.

        Users with email addresses from this domain will no longer be
        automatically added to the organization.

        Args:
            email_domain: Email domain to unbind (e.g., "example.com").

        Returns:
            This Org instance for method chaining.

        Raises:
            RobotoNotFoundException: The email domain is not bound to this organization.
            RobotoUnauthorizedException: The caller lacks permission to unbind email domains.

        Examples:
            Unbind an email domain:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> org.unbind_email_domain("old-company.com")
        """
        self.__roboto_client.delete(
            f"v1/orgs/id/{self.org_id}/email_domains/id/{urllib.parse.quote_plus(email_domain)}"
        )
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        """Convert this organization to a dictionary representation.

        Returns a JSON-serializable dictionary containing all organization data.

        Returns:
            Dictionary representation of the organization.

        Examples:
            Export organization data:

            >>> from roboto import Org
            >>> org = Org.from_id("org_12345")
            >>> org_data = org.to_dict()
            >>> print(f"Org created: {org_data.get('created')}")
        """
        return self.__record.model_dump(mode="json")
