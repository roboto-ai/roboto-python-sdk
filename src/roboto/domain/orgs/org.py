# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing
import urllib.parse
import uuid
import warnings

from ...association import Association
from ...http import RobotoClient
from ...regionalization import RobotoRegion
from ..files import FileSystem
from .org_invite import OrgInvite
from .org_operations import (
    BindEmailDomainResponse,
    CreateOrgRequest,
    CreateOrgResponse,
    EmailDomainBindingOutcome,
    EmailDomainVerificationChallengeResponse,
    SetOrgEmailDomainAutoJoinRequest,
    UpdateOrgRequest,
    UpdateOrgUserRequest,
)
from .org_records import (
    OrgEmailDomainListing,
    OrgEmailDomainRecord,
    OrgRecord,
    OrgRoleName,
    OrgStatus,
    OrgTier,
    OrgUserRecord,
)


class Org:
    """An organization: a workspace in which users share datasets, actions and other resources in Roboto.

    Every dataset, action and other resource belongs to one organization. A user can belong to several organizations,
    with a different set of roles in each (see :py:class:`~roboto.domain.orgs.OrgRoleName`). An organization's tier
    sets its features and usage limits. Binding an email domain to an organization, and verifying it where Roboto
    requires that, makes people who sign up with an address in that domain join it.

    Get an ``Org`` from ``create``, ``from_id``, or ``for_self``. To wrap a :py:class:`~roboto.domain.orgs.OrgRecord`
    already fetched from Roboto, build an ``Org`` from it directly. Each instance holds a copy of the organization's
    record: ``update`` updates that copy from Roboto's response, and ``refresh`` fetches changes made elsewhere.

    Args:
        record: Record of the organization.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
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
        idempotency_key: typing.Optional[str] = None,
    ) -> "Org":
        """Create an organization, with the caller as its owner.

        The SDK retries the request after a timeout or a server error, and every attempt carries the same idempotency
        key, so the retries create one organization, not several. When the request still fails after the retries,
        ``create`` raises ``RobotoServiceUnavailableException``: calling it again with the same ``idempotency_key`` is
        safe, and finishes the setup of an organization the request created.

        Args:
            name: Human-readable name of the organization. Roboto does not require names to be unique.
            bind_email_domain: Whether to bind the creator's email domain to the new organization, so that people who
                sign up with an address in the domain join the organization. The organization is created whether or
                not the domain binds. When it does not bind, a ``UserWarning`` says why: the domain is one that no
                organization may bind, such as a public email provider's domain; another organization holds it; or
                Roboto requires the domain to be verified first, in which case the warning carries the DNS TXT record
                that verifies it, which Roboto shows only once.
            data_region: Region where Roboto stores the organization's data.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            idempotency_key: Key that identifies this creation: 1 to 255 printable ASCII characters, not including
                space. Calling ``create`` again with the same key returns the organization the first call created.
                ``None`` generates a key that only this call's retries use.

        Returns:
            The new organization.

        Raises:
            RobotoConflictException: ``idempotency_key`` was used before with a different ``name``, ``data_region`` or
                ``bind_email_domain``, or for an organization that is no longer the caller's, such as one deleted or
                one the caller left. No organization is created.
            RobotoInvalidRequestException: Roboto does not support ``data_region``, or ``idempotency_key`` is not 1 to
                255 printable ASCII characters other than space.
            RobotoLimitExceededException: The caller already owns as many organizations as they may.
            RobotoOrgCreationRefusedException: The Roboto deployment's sign-up policy does not let the caller create
                an organization now. Its ``next_step`` says what the caller can do instead.

        Examples:
            Create an organization:

            >>> from roboto.domain.orgs import Org
            >>> org = Org.create("my-company")
            >>> print(f"Created org: {org.name}")

            Create an organization in another region, and bind the creator's email domain to it:

            >>> from roboto import RobotoRegion
            >>> from roboto.domain.orgs import Org
            >>> org = Org.create(name="acme-corp", bind_email_domain=True, data_region=RobotoRegion.EU_CENTRAL)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateOrgRequest(name=name, bind_email_domain=bind_email_domain, data_region=data_region)
        response = roboto_client.post(
            "v1/orgs",
            data=request,
            headers={"Idempotency-Key": idempotency_key if idempotency_key is not None else str(uuid.uuid4())},
        ).to_record(CreateOrgResponse)
        unbound_reason = _unbound_email_domain_reason(response)
        if unbound_reason is not None:
            warnings.warn(
                f"Created organization '{response.name}' ({response.org_id}) but did not bind your email domain to it. "
                + unbound_reason,
                stacklevel=2,
            )
        # The binding outcome and the DNS TXT record describe this request, not the organization, so they stay out of
        # the Org's record and out of to_dict().
        return cls(record=OrgRecord.model_validate(response.model_dump()), roboto_client=roboto_client)

    @classmethod
    def from_id(cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> "Org":
        """Fetch an organization by its ID.

        Args:
            org_id: ID of the organization, beginning with ``og_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No organization has this ID.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> print(f"Organization: {org.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/orgs/id/{org_id}").to_record(OrgRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_self(cls, roboto_client: typing.Optional[RobotoClient] = None) -> collections.abc.Sequence["Org"]:
        """Fetch every organization the caller belongs to.

        Args:
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> for org in Org.for_self():
            ...     print(f"Member of: {org.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get("v1/orgs/caller").to_record_list(OrgRecord)
        return [cls(record=record, roboto_client=roboto_client) for record in records]

    @classmethod
    def for_user(
        cls, user_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Sequence["Org"]:
        """Fetch every organization a user belongs to.

        Args:
            user_id: ID of the user, which for a person is their email address.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No user exists with the specified ID.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> orgs = Org.for_user("alice@example.com")
            >>> print(f"Alice is in {len(orgs)} organizations")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get(f"v1/users/id/{urllib.parse.quote_plus(user_id)}/orgs").to_record_list(OrgRecord)
        return [cls(record=record, roboto_client=roboto_client) for record in records]

    def __init__(self, record: OrgRecord, roboto_client: typing.Optional[RobotoClient] = None):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def assets(self) -> FileSystem:
        """Files that belong to the organization as a whole, such as runbooks, rather than to a dataset or device.

        A dataset's files are reached through :py:attr:`~roboto.domain.datasets.Dataset.files`, and a device's
        configurations through :py:attr:`~roboto.domain.devices.Device.configurations`.
        """
        return FileSystem(Association.org(self.org_id), roboto_client=self.__roboto_client, org_id=self.org_id)

    @property
    def name(self) -> str:
        """Human-readable name of the organization."""
        return self.__record.name

    @property
    def org_id(self):
        """Unique ID of the organization, beginning with ``og_``."""
        return self.__record.org_id

    @property
    def status(self) -> OrgStatus:
        """Lifecycle state of the organization."""
        return self.__record.status

    @property
    def tier(self) -> OrgTier:
        """Subscription tier of the organization."""
        return self.__record.tier

    def add_role_for_user(self, user_id: str, role: OrgRoleName) -> "Org":
        """Grant a role to a member of this organization.

        A member can hold several roles at once. Granting :py:attr:`~roboto.domain.orgs.OrgRoleName.owner` also grants
        :py:attr:`~roboto.domain.orgs.OrgRoleName.admin`, and granting a role the member already holds changes nothing.

        Args:
            user_id: ID of the member, which for a person is their email address.
            role: Role to grant.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Raises:
            RobotoInvalidRequestException: ``role`` is ``admin`` or ``owner`` and the member is a service user.
            RobotoNotFoundException: The user is not a member of this organization.
            RobotoUnauthorizedException: The caller is granting a role to themselves, does not hold a higher role than
                the member, or grants ``owner`` without being an owner.

        Examples:
            >>> from roboto.domain.orgs import Org, OrgRoleName
            >>> org = Org.from_id("og_12345")
            >>> org.add_role_for_user("alice@example.com", OrgRoleName.admin)
        """
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}",
            data=UpdateOrgUserRequest(add_roles=[role]),
            caller_org_id=self.org_id,
        )
        return self

    def remove_role_from_user(self, user_id: str, role: OrgRoleName) -> "Org":
        """Revoke a role from a member of this organization.

        The user stays a member; ``remove_user`` removes them. Revoking
        :py:attr:`~roboto.domain.orgs.OrgRoleName.admin` also revokes :py:attr:`~roboto.domain.orgs.OrgRoleName.owner`,
        and revoking a role the member does not hold changes nothing. A member can revoke their own roles.

        Args:
            user_id: ID of the member, which for a person is their email address.
            role: Role to revoke: ``admin`` or ``owner``.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Raises:
            RobotoInvalidRequestException: ``role`` is ``user``, which every member holds; or ``role`` is ``owner``
                and the member is the organization's only owner.
            RobotoNotFoundException: The user is not a member of this organization.
            RobotoUnauthorizedException: The member is someone else, and the caller does not hold a higher role than
                them.

        Examples:
            >>> from roboto.domain.orgs import Org, OrgRoleName
            >>> org = Org.from_id("og_12345")
            >>> org.remove_role_from_user("alice@example.com", OrgRoleName.admin)
        """
        self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}",
            data=UpdateOrgUserRequest(remove_roles=[role]),
        )
        return self

    def bind_email_domain(self, email_domain: str) -> "Org":
        """Bind an email domain to this organization.

        Where Roboto does not require email domains to be verified, a domain the organization does not hold yet binds
        with auto-join on, so people who sign up with an address at the domain join this organization. Where Roboto
        requires verification, this starts a verification of the domain instead, and discards the DNS TXT record that
        completes it: call ``start_email_domain_verification`` instead to get the record, or
        ``new_email_domain_verification_record`` for a new one. Once the domain is verified,
        ``set_email_domain_auto_join`` turns auto-join on. A domain the organization already holds keeps its auto-join
        setting. Roboto stores the domain in lowercase. Only organization administrators may bind email domains.

        Args:
            email_domain: Email domain to bind, such as ``example.com``. The caller's own email address must be in it.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Raises:
            RobotoInvalidRequestException: The domain is not an email domain, or is on Roboto's list of domains that no
                organization may bind, which includes public email providers' domains.
            RobotoLimitExceededException: The organization is verifying as many email domains at once as it may.
            RobotoOrgEmailDomainChangeRefusedException: Another organization holds the domain.
            RobotoUnauthorizedException: Roboto does not require email domains to be verified, and the caller's email
                address is not at the domain.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.bind_email_domain("example.com")
        """
        self.__roboto_client.put(f"v1/orgs/id/{self.org_id}/email_domains/id/{urllib.parse.quote_plus(email_domain)}")
        return self

    def check_email_domain_verification(self, email_domain: str) -> OrgEmailDomainRecord:
        """Verify an email domain for this organization, once its verification's DNS TXT record is published.

        Roboto looks up the DNS TXT record of this organization's verification of the domain, and verifies the domain
        when it finds the record. A domain the organization does not hold yet becomes one it holds, with auto-join on
        when :py:attr:`~roboto.domain.orgs.EmailDomainVerificationChallengeRecord.auto_join_on_verify` is ``True``; a
        domain it holds keeps its auto-join setting. When Roboto cannot reach DNS, the method raises
        ``RobotoServiceUnavailableException``; try again in a few minutes. Only organization administrators may verify
        email domains.

        Args:
            email_domain: Email domain to verify, such as ``example.com``.

        Returns:
            Record of the verified email domain.

        Raises:
            RobotoInvalidRequestException: The domain is not an email domain, or is on Roboto's list of domains that no
                organization may bind.
            RobotoOrgEmailDomainChangeRefusedException: The organization has no unexpired verification of the domain,
                Roboto did not find the record at the domain, or another organization holds the domain. Its ``reason``
                says which.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.check_email_domain_verification("example.com").status
            <OrgEmailDomainStatus.Verified: 'verified'>
        """
        return self.__roboto_client.post(
            f"v1/orgs/id/{self.org_id}/email-domains/id/{urllib.parse.quote_plus(email_domain)}/check-verification"
        ).to_record(OrgEmailDomainRecord)

    def delete(self) -> None:
        """Delete this organization and everything in it, such as its datasets, actions and memberships.

        Roboto removes the organization at once and deletes its data afterward. This cannot be undone. Deleting an
        organization that no longer exists succeeds and changes nothing.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.delete()
        """
        self.__roboto_client.delete(f"v1/orgs/id/{self.org_id}")

    def email_domain_listing(self) -> OrgEmailDomainListing:
        """Fetch the email domains this organization holds and its unexpired verifications of email domains.

        Each domain's record gives its verification status and its auto-join setting.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> for domain in org.email_domain_listing().email_domains:
            ...     print(domain.email_domain, domain.status, domain.auto_join)
        """
        return self.__roboto_client.get(f"v1/orgs/id/{self.org_id}/email-domains/listing").to_record(
            OrgEmailDomainListing
        )

    def email_domains(self) -> collections.abc.Collection[str]:
        """Fetch the email domains bound to this organization.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> for domain in org.email_domains():
            ...     print(f"Bound domain: {domain}")
        """
        return self.__roboto_client.get(f"v1/orgs/id/{self.org_id}/email_domains").to_dict(json_path=["data"])

    def invite_user(
        self,
        user_id: str,
        *,
        role: OrgRoleName = OrgRoleName.user,
    ) -> OrgInvite:
        """Invite a user to join this organization.

        Roboto emails the invitation to the user, who need not have a Roboto account yet. The user joins with ``role``
        when they accept it (:py:meth:`~roboto.domain.orgs.OrgInvite.accept`). The invitation expires 14 days after it
        is sent.

        Args:
            user_id: ID of the user to invite, which is their email address.
            role: Role the invited user gets by accepting. Only an organization owner or a Roboto administrator may
                invite someone as :py:attr:`~roboto.domain.orgs.OrgRoleName.admin`, and no invitation may carry
                ``owner``.

        Returns:
            The new invitation.

        Raises:
            RobotoNotFoundException: The organization has been deleted.
            RobotoInvalidRequestException: ``role`` is ``owner``; the user is already a member or is a service user;
                the user's email address is outside the email domains the Roboto deployment accepts; or the
                deployment does not support invitation roles, in which case it still created the invitation, with the
                ``user`` role, and declining the invitation withdraws it.
            RobotoConflictException: The user already has a pending invitation to the organization.
            RobotoLimitExceededException: The organization's members and pending invitations already reach its limit
                on members.
            RobotoUnauthorizedException: ``role`` is ``admin`` and the caller is not an owner of the organization, or
                the Roboto deployment lets only organization administrators invite users and the caller is not one.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> invite = org.invite_user("alice@example.com")
            >>> print(f"Invitation created: {invite.invite_id}")
        """
        return OrgInvite.create(
            invited_user_id=user_id,
            org_id=self.org_id,
            roboto_client=self.__roboto_client,
            role=role,
        )

    def invites(self) -> collections.abc.Collection[OrgInvite]:
        """Fetch this organization's pending invitations, oldest first.

        Pending invitations past their expiry are included, with the status
        :py:attr:`~roboto.domain.orgs.OrgInviteStatus.Expired`.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> for invite in org.invites():
            ...     print(f"Pending invite for: {invite.invited_user_id}")
        """
        return OrgInvite.for_org(org_id=self.org_id, roboto_client=self.__roboto_client)

    def new_email_domain_verification_record(self, email_domain: str) -> EmailDomainVerificationChallengeResponse:
        """Create a verification of an email domain for this organization, with a new DNS TXT record.

        The new record replaces the record of any verification of the domain the organization has, which then no longer
        completes it. Only organization administrators may verify email domains.

        Args:
            email_domain: Email domain to verify, such as ``example.com``.

        Returns:
            The verification, and the DNS TXT record to publish at the domain. Roboto shows the record's value only in
            this response.

        Raises:
            RobotoInvalidRequestException: The domain is not an email domain, or is on Roboto's list of domains that no
                organization may bind.
            RobotoLimitExceededException: The organization is verifying as many other email domains at once as it may.
            RobotoOrgEmailDomainChangeRefusedException: Another organization holds the domain.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> record = org.new_email_domain_verification_record("example.com").verification_txt_record
            >>> print(record.name, record.value)
        """
        return self.__roboto_client.post(
            f"v1/orgs/id/{self.org_id}/email-domains/id/{urllib.parse.quote_plus(email_domain)}"
            "/replace-verification-challenge"
        ).to_record(EmailDomainVerificationChallengeResponse)

    def refresh(self) -> "Org":
        """Fetch this organization's record from Roboto, replacing the copy this instance holds.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The organization has been deleted.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.refresh()
        """
        self.__record = self.__roboto_client.get(f"v1/orgs/id/{self.org_id}").to_record(OrgRecord)
        return self

    def remove_user(self, user_id: str) -> "Org":
        """Remove a member from this organization, with all their roles in it.

        Removing a user who is not a member succeeds and changes nothing.

        Args:
            user_id: ID of the member to remove, which for a person is their email address.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Raises:
            RobotoInvalidRequestException: The member is the organization's only owner, or is an owner removing
                themselves.
            RobotoUnauthorizedException: The member is someone else, and the caller does not hold a higher role than
                them.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.remove_user("alice@example.com")
        """
        self.__roboto_client.delete(f"v1/orgs/id/{self.org_id}/users/id/{urllib.parse.quote_plus(user_id)}")
        return self

    def set_email_domain_auto_join(self, email_domain: str, enabled: bool) -> OrgEmailDomainRecord:
        """Turn auto-join on or off for an email domain this organization holds.

        With auto-join on, people who sign up with an address at the domain join this organization. Turning it on needs
        a verified domain, or one Roboto has provisionally approved with an approval that has not expired. Only
        organization administrators may change auto-join.

        Args:
            email_domain: Email domain to change, such as ``example.com``.
            enabled: Whether to turn auto-join on.

        Returns:
            Record of the email domain, with the change applied.

        Raises:
            RobotoNotFoundException: This organization does not hold the domain.
            RobotoOrgEmailDomainChangeRefusedException: ``enabled`` is ``True``, auto-join is off, and the domain is
                neither verified nor provisionally approved by Roboto with an approval that has not expired.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.set_email_domain_auto_join("example.com", enabled=False)
        """
        return self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/email-domains/id/{urllib.parse.quote_plus(email_domain)}/auto-join",
            data=SetOrgEmailDomainAutoJoinRequest(enabled=enabled),
        ).to_record(OrgEmailDomainRecord)

    def start_email_domain_verification(self, email_domain: str) -> BindEmailDomainResponse:
        """Bind an email domain to this organization, or start a verification of it where Roboto requires one.

        Where Roboto requires email domains to be verified, a domain the organization holds verified, or provisionally
        approved by Roboto with an approval that has not expired, is returned bound, and any other domain gets a
        verification. A verification already in progress is returned without its DNS TXT record, which Roboto shows
        only once; ``new_email_domain_verification_record`` issues a new record. Publish the record at the domain, then
        call ``check_email_domain_verification``. Where Roboto does not require verification, the domain binds at once,
        and a domain the organization already holds is returned as it is. Only organization administrators may bind
        email domains.

        Args:
            email_domain: Email domain to bind, such as ``example.com``.

        Returns:
            What became of the domain: :py:attr:`~roboto.domain.orgs.EmailDomainBindingOutcome.Bound`, with the domain
            as the organization holds it; or
            :py:attr:`~roboto.domain.orgs.EmailDomainBindingOutcome.VerificationStarted`, with the verification and,
            when this call started it, the DNS TXT record to publish.

        Raises:
            RobotoInvalidRequestException: The domain is not an email domain, or is on Roboto's list of domains that no
                organization may bind.
            RobotoLimitExceededException: The organization is verifying as many email domains at once as it may.
            RobotoOrgEmailDomainChangeRefusedException: Another organization holds the domain.
            RobotoUnauthorizedException: Roboto does not require email domains to be verified, and the caller's email
                address is not at the domain.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> response = org.start_email_domain_verification("example.com")
            >>> if response.verification_txt_record is not None:
            ...     print(response.verification_txt_record.name, response.verification_txt_record.value)
        """
        return self.__roboto_client.put(
            f"v1/orgs/id/{self.org_id}/email-domains/id/{urllib.parse.quote_plus(email_domain)}"
        ).to_record(BindEmailDomainResponse)

    def update(self, update: UpdateOrgRequest) -> "Org":
        """Update this organization's name or status.

        Only a Roboto administrator may set the status.

        Args:
            update: Changes to apply. A field left ``None`` is unchanged.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoUnauthorizedException: ``update`` sets the organization's status, and the caller is not a Roboto
                administrator.

        Examples:
            Rename an organization:

            >>> from roboto.domain.orgs import Org, UpdateOrgRequest, OrgRecordUpdates
            >>> org = Org.from_id("og_12345")
            >>> request = UpdateOrgRequest(updates=OrgRecordUpdates(name="New Company Name"))
            >>> org.update(request)
        """
        self.__record = self.__roboto_client.put(f"v1/orgs/id/{self.org_id}", data=update).to_record(OrgRecord)
        return self

    def users(self) -> collections.abc.Collection[OrgUserRecord]:
        """Fetch this organization's members, each with their roles.

        Raises:
            RobotoNotFoundException: The caller cannot see this organization.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> for user_record in org.users():
            ...     print(f"Member: {user_record.user.name} ({user_record.roles})")
        """
        return self.__roboto_client.get(f"v1/orgs/id/{self.org_id}/users").to_record_list(OrgUserRecord)

    def unbind_email_domain(self, email_domain: str) -> "Org":
        """Unbind an email domain from this organization, and remove any verification of the domain in progress.

        People who sign up with an address in the domain no longer join the organization. Unbinding a domain the
        organization does not hold succeeds and changes nothing.

        Args:
            email_domain: Email domain to unbind, such as ``example.com``.

        Returns:
            This instance. Its record is unchanged until you fetch it again.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org.unbind_email_domain("example.com")
        """
        self.__roboto_client.delete(
            f"v1/orgs/id/{self.org_id}/email_domains/id/{urllib.parse.quote_plus(email_domain)}"
        )
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        """Return this organization's record as a JSON-serializable dictionary.

        Returns:
            :py:class:`~roboto.domain.orgs.OrgRecord` of the organization, as a JSON-compatible dictionary.

        Examples:
            >>> from roboto.domain.orgs import Org
            >>> org = Org.from_id("og_12345")
            >>> org_data = org.to_dict()
            >>> print(f"Org created: {org_data.get('created')}")
        """
        return self.__record.model_dump(mode="json")


def _unbound_email_domain_reason(response: CreateOrgResponse) -> typing.Optional[str]:
    """Return why the creation left the creator's email domain unbound.

    ``None`` when it bound the domain or was not asked to.
    """
    match response.email_domain_binding_outcome:
        case EmailDomainBindingOutcome.DenyListed:
            return (
                "Your domain is on Roboto's list of domains that no organization may bind, such as public email "
                + "providers' domains."
            )
        case EmailDomainBindingOutcome.EmailNotProven:
            return "Roboto has no confirmed email address for you, so it can't tell which domain is yours."
        case EmailDomainBindingOutcome.HeldByAnotherOrg:
            return (
                "Another organization already uses your email domain. For help, contact the administrator of the "
                + "Roboto deployment you're using."
            )
        case EmailDomainBindingOutcome.VerificationStarted:
            txt_record = response.verification_txt_record
            if txt_record is None:
                return (
                    "To bind your domain, first verify it: get a DNS TXT record for it with "
                    + "Org.new_email_domain_verification_record."
                )
            return (
                "To bind your domain, first verify it: publish this DNS TXT record, then call "
                + f"Org.check_email_domain_verification. Name: {txt_record.name} Value: {txt_record.value}"
            )
        case _:
            return None
