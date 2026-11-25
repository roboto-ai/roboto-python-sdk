# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...compat import StrEnum
from ...regionalization import RobotoRegion
from ...sentinels import NotSet, NotSetType
from .org_records import (
    EmailDomainVerificationChallengeRecord,
    EmailDomainVerificationTxtRecord,
    GuestOrMember,
    OrgEmailDomainRecord,
    OrgRecord,
    OrgRoleName,
    OrgStatus,
)


class CreateOrgRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.orgs.Org.create`."""

    name: str
    """Human-readable name of the organization."""

    bind_email_domain: bool = False
    """Whether to bind the creator's email domain to the organization.

    People who sign up with an address at a bound domain join the organization. Where Roboto requires email domains to
    be verified, this starts a verification of the domain instead, and auto-join turns on when the verification
    completes. ``CreateOrgResponse.email_domain_binding_outcome`` reports what Roboto did.
    """

    data_region: RobotoRegion = RobotoRegion.US_WEST
    """Region where Roboto stores the organization's data."""


class EmailDomainBindingOutcome(StrEnum):
    """Outcome of a request to bind an email domain to an organization, at its creation or later."""

    Bound = "bound"
    """Roboto bound the domain to the organization, or the organization already held it."""

    DenyListed = "deny_listed"
    """Roboto left the domain unbound, because it is on Roboto's list of domains that no organization may bind.

    The list includes public email providers' domains, such as ``gmail.com``.
    """

    EmailNotProven = "email_not_proven"
    """Unused. Roboto never returns this value.

    It is reserved for a domain left unbound, with no verification started, because Roboto has no confirmed email
    address for the organization's owner.
    """

    HeldByAnotherOrg = "held_by_another_org"
    """Roboto left the domain unbound, because another organization holds it."""

    VerificationStarted = "verification_started"
    """The organization has a verification of the domain in progress.

    The verification completes when the DNS TXT record Roboto issued for it is published at the domain, and an
    organization administrator asks Roboto to check it, in the Roboto web app or with
    :py:meth:`~roboto.domain.orgs.Org.check_email_domain_verification`.
    """


class CreateOrgResponse(OrgRecord):
    """Response body of :py:meth:`~roboto.domain.orgs.Org.create`.

    Holds the new organization's record, the outcome of binding the creator's email domain to it, and the DNS TXT
    record of any verification of that domain the request started.
    """

    email_domain_binding_outcome: typing.Optional[EmailDomainBindingOutcome] = None
    """Outcome of binding the creator's email domain to the organization.

    ``None`` if ``CreateOrgRequest.bind_email_domain`` was ``False``.
    """

    verification_txt_record: typing.Optional[EmailDomainVerificationTxtRecord] = None
    """DNS TXT record that completes the verification of the creator's email domain that the request started.

    ``None`` when the request started no verification, and on a retry with the same idempotency key, since Roboto
    shows the record once. An organization administrator can get a new record with
    :py:meth:`~roboto.domain.orgs.Org.new_email_domain_verification_record`.
    """


class OrgCreationEligibility(pydantic.BaseModel):
    """Response body of ``GET /v1/orgs/creation/eligibility``.

    Says whether the caller may create an organization now and, if not, what they can do next. No SDK method returns
    it.
    """

    next_step: str
    """Step the caller can take toward creating an organization.

    ``create_org`` when the caller may create an organization now. Otherwise what would let them:
    ``bind_org_creation_grant`` (confirm their approval in the Roboto web app), ``submit_access_request``,
    ``contact_deployment_administrator``, ``use_web_app_session`` (sign in to Roboto in a browser, without acting as
    another user), or ``none`` (nothing would; ``reason`` says why).
    """

    reason: typing.Optional[str] = None
    """Reason for ``next_step`` when the step alone does not say, otherwise ``None``.

    ``owned_org_limit_reached`` comes with ``none``: the caller owns as many organizations as they may.
    ``org_creation_grant_bound_to_other_cognito_user`` comes with ``contact_deployment_administrator``: the caller's
    approval is linked to a different sign-in.
    """

    sign_up_policy: typing.Optional[str] = None
    """Sign-up policy of the Roboto deployment: ``request_access`` or ``closed``.

    ``None`` when the deployment sets none, which Roboto treats as ``closed``.
    """

    access_control_config_revision: typing.Optional[str] = None
    """Revision of the deployment's access control settings that Roboto answered from.

    ``None`` when the deployment records none.
    """

    relaxation_document_revision: typing.Optional[int] = None
    """Revision of the list of exceptions to the deployment's access control rules that Roboto read for this answer.

    ``None`` when it read none.
    """


class OrgRecordUpdates(pydantic.BaseModel):
    """Changes to apply to an organization.

    A field left ``None`` is unchanged. Carried in ``UpdateOrgRequest.updates``.
    """

    name: typing.Optional[str] = None
    """Human-readable name to give the organization."""

    status: typing.Optional[OrgStatus] = None
    """Status to set on the organization. Only a Roboto administrator may set it."""


class UpdateOrgRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.orgs.Org.update`.

    Only organization owners may send it.
    """

    updates: OrgRecordUpdates
    """Changes to apply to the organization."""


class UpdateOrgUserRequest(pydantic.BaseModel):
    """Request body that adds roles to, or removes roles from, a member of an organization.

    Sent by :py:meth:`~roboto.domain.orgs.Org.add_role_for_user` and
    :py:meth:`~roboto.domain.orgs.Org.remove_role_from_user`. Only organization administrators may send it. Building
    one that neither adds nor removes a role raises ``pydantic.ValidationError``.
    """

    add_roles: typing.Optional[list[OrgRoleName]] = None
    """Roles to grant the member. ``None`` grants none."""

    remove_roles: typing.Optional[list[OrgRoleName]] = None
    """Roles to revoke from the member. ``None`` revokes none."""

    @pydantic.model_validator(mode="after")
    def check_some_updates_present(self) -> "UpdateOrgUserRequest":
        """Reject a request whose ``add_roles`` and ``remove_roles`` are both ``None`` or empty."""
        if len(self.add_roles or []) == 0 and len(self.remove_roles or []) == 0:
            raise ValueError("At least one role should be included in add_roles or remove_roles")

        return self


class CreateOrgGroupRequest(pydantic.BaseModel):
    """Request payload to make a group of an organization's members."""

    name: typing.Annotated[str, pydantic.StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    """The group's name (1 to 120 characters), unique within the organization whatever its case."""

    description: typing.Optional[str] = None
    """What the group is for."""


class UpdateOrgGroupRequest(pydantic.BaseModel):
    """Request payload to rename an organization's group or change its description. Only the fields given change."""

    name: typing.Union[
        typing.Annotated[str, pydantic.StringConstraints(strip_whitespace=True, min_length=1, max_length=120)],
        NotSetType,
    ] = NotSet
    """The group's new name (1 to 120 characters), unique within the organization whatever its case."""

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """The group's new description. Set to None to clear it."""

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


class UpdateOrgGroupMembersRequest(pydantic.BaseModel):
    """Request payload to add members to an organization's group and remove members from it. Each added user must be a
    member of the organization."""

    add_user_ids: list[str] = pydantic.Field(default_factory=list)
    """User IDs to add to the group. Adding a member again changes nothing."""

    remove_user_ids: list[str] = pydantic.Field(default_factory=list)
    """User IDs to remove from the group. Removing a user who is not a member changes nothing."""


class CreateOrgRoleRequest(pydantic.BaseModel):
    """Request payload to define a role in an organization. Only an admin or owner of the organization may define
    one."""

    name: typing.Annotated[str, pydantic.StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    """The role's name (1 to 120 characters), unique within the organization whatever its case."""

    description: typing.Optional[str] = None
    """What the role is for."""

    switches: list[str] = pydantic.Field(default_factory=list)
    """The names of the switches the role turns on, such as ``view_data``; every other switch is off. A name that is
    not a switch is refused, and the refusal lists every switch."""


class UpdateOrgRoleRequest(pydantic.BaseModel):
    """Request payload to rename a role an organization defined, or change its description or switches. Only the
    fields given change. A change of switches applies to every holder at their next request. Only an admin or owner of
    the organization may change a role, and nobody may change a preset."""

    name: typing.Union[
        typing.Annotated[str, pydantic.StringConstraints(strip_whitespace=True, min_length=1, max_length=120)],
        NotSetType,
    ] = NotSet
    """The role's new name (1 to 120 characters), unique within the organization whatever its case."""

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """The role's new description. Set to None to clear it."""

    switches: typing.Union[list[str], NotSetType] = NotSet
    """The names of the switches the role turns on; every other switch is off."""

    model_config = pydantic.ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


MAX_ROLES_HELD_DIRECTLY: typing.Final = 25
"""The most presets and roles the organization defined that one member, or one group, may hold itself. Roles a member
holds through groups do not count toward the member's limit."""

HeldRoleIds = typing.Annotated[list[str], pydantic.Field(max_length=MAX_ROLES_HELD_DIRECTLY)]
"""The IDs of the presets and roles an organization defined that one member or group holds, at most
:py:data:`MAX_ROLES_HELD_DIRECTLY` of them."""


class SetOrgMemberRolesRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/orgs/id/<org_id>/users/id/<user_id>/roles``: set a member's built-in role to
    guest or member, and replace the roles they hold themselves, in one change. Only an admin or owner of the
    organization may.

    An admin or owner is made one, and stops being one, through the organization's membership update instead. Roles
    held through a group are set on the group.
    """

    built_in_role: typing.Optional[GuestOrMember] = None
    """The member's new built-in role; ``None`` leaves it as it is. An admin, an owner or a service user is never made
    a guest."""

    role_ids: HeldRoleIds
    """Every preset and role the organization defined that the member holds themselves afterwards; each one not listed
    is taken from them."""


class SetOrgGroupRolesRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/orgs/id/<org_id>/groups/<group_id>/roles``: replace the roles a group of the
    organization holds. Only an admin or owner of the organization may."""

    role_ids: HeldRoleIds
    """Every preset and role the organization defined that the group holds afterwards; each one not listed is taken
    from it. Each member of the group holds them through it."""


class RemoveUserFromOrgRequest(pydantic.BaseModel):
    """Deprecated. Request body for ``DELETE /v1/orgs/users``, which removes a user from the caller's organization.

    Use :py:meth:`~roboto.domain.orgs.Org.remove_user` instead.
    """

    user_id: str
    """ID of the user to remove, which for a person is their email address."""


class ModifyRoleForUserRequest(pydantic.BaseModel):
    """Deprecated. Request body for ``PUT /v1/orgs/roles`` and ``DELETE /v1/orgs/roles``.

    Use :py:meth:`~roboto.domain.orgs.Org.add_role_for_user` and
    :py:meth:`~roboto.domain.orgs.Org.remove_role_from_user` instead. ``PUT`` adds one role to a member of the
    caller's organization, and ``DELETE`` removes it. Only organization administrators may send it. No SDK method
    sends it.
    """

    user_id: str
    """ID of the user whose role changes, which for a person is their email address."""

    role_name: OrgRoleName
    """Role to add or remove."""


class BindEmailDomainRequest(pydantic.BaseModel):
    """Deprecated. Request body for ``PUT /v1/orgs/subdomains`` and ``DELETE /v1/orgs/subdomains``.

    Use :py:meth:`~roboto.domain.orgs.Org.bind_email_domain` and
    :py:meth:`~roboto.domain.orgs.Org.unbind_email_domain` instead. ``PUT`` binds an email domain to the caller's
    organization, and ``DELETE`` unbinds it. Only organization administrators may send it. No SDK method sends it.
    """

    email_domain: str
    """Email domain to bind or unbind, such as ``example.com``."""


class BindEmailDomainResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.orgs.Org.start_email_domain_verification`.

    Says what became of a request to bind an email domain to an organization.
    """

    email_domain: typing.Optional[OrgEmailDomainRecord] = None
    """Record of the domain as the organization holds it, or ``None`` when the organization does not hold it."""

    outcome: EmailDomainBindingOutcome
    """Outcome of the request: ``EmailDomainBindingOutcome.Bound`` or ``EmailDomainBindingOutcome.VerificationStarted``.

    ``Bound`` when the organization holds the domain and needs no verification of it, and ``VerificationStarted`` when
    it has a verification of the domain in progress. An organization can hold a domain it has not verified, so
    ``VerificationStarted`` can come with ``email_domain`` set.
    """

    verification_challenge: typing.Optional[EmailDomainVerificationChallengeRecord] = None
    """Record of the organization's verification of the domain, or ``None`` when none is in progress."""

    verification_txt_record: typing.Optional[EmailDomainVerificationTxtRecord] = None
    """DNS TXT record to publish at the domain, or ``None`` unless this request started the verification."""


class EmailDomainVerificationChallengeResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.orgs.Org.new_email_domain_verification_record`.

    Holds a verification of an email domain with a new DNS TXT record, which replaces the record of the organization's
    previous verification of the domain.
    """

    verification_challenge: EmailDomainVerificationChallengeRecord
    """Record of the verification."""

    verification_txt_record: EmailDomainVerificationTxtRecord
    """DNS TXT record to publish at the domain. Roboto shows it only in this response."""


class OrgEmailDomainChangeRefusal(StrEnum):
    """Reason Roboto refused to change an organization's email domain as asked.

    :py:class:`~roboto.exceptions.RobotoOrgEmailDomainChangeRefusedException` carries it in its ``reason``.
    """

    DnsRecordNotFound = "dns_record_not_found"
    """Roboto did not find the verification's DNS TXT record at the domain.

    DNS changes can take up to an hour to appear.
    """

    HeldByAnotherOrg = "held_by_another_org"
    """Another organization holds the domain."""

    NoVerificationChallenge = "no_verification_challenge"
    """The organization has no unexpired verification of the domain.

    :py:meth:`~roboto.domain.orgs.Org.new_email_domain_verification_record` starts one with a new DNS TXT record.
    """

    NotVerifiedOrProvisionallyApproved = "not_verified_or_provisionally_approved"
    """The domain is neither verified nor provisionally approved by Roboto with an approval that has not expired.

    Turning auto-join on needs one of the two.
    """


class SetOrgEmailDomainAutoJoinRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.orgs.Org.set_email_domain_auto_join`."""

    enabled: bool
    """Whether to turn auto-join on, so that people who sign up with an address at the domain join the organization."""


class InviteUserRequest(pydantic.BaseModel):
    """Deprecated. Request body for ``POST /v1/orgs/invites``, which invites a user to the caller's organization.

    Use :py:meth:`~roboto.domain.orgs.Org.invite_user` instead.
    """

    invited_user_id: str
    """ID of the user to invite, which for a person is their email address."""


class CreateOrgInviteRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.orgs.OrgInvite.create`."""

    role: OrgRoleName = OrgRoleName.user
    """Role the invited user gets by accepting.

    Only an organization owner or a Roboto administrator may invite someone as
    :py:attr:`~roboto.domain.orgs.OrgRoleName.admin`. ``owner`` raises ``RobotoInvalidRequestException``.
    """

    built_in_role: typing.Optional[GuestOrMember] = None
    """Built-in role the invited user gets by accepting an invite with the ``user`` role, or ``None`` for a member.

    ``guest`` also needs an organization whose ``access_control_features`` is on, and is refused with any other role.
    ``member`` with another role is ignored.
    """
