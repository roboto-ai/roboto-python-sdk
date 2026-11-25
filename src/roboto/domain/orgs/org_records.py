# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ..users import UserRecord


class OrgStatus(StrEnum):
    """Lifecycle state of an organization."""

    Provisioning = "provisioning"
    """Unused. Roboto creates every organization as ``Active`` and never sets this state."""

    Active = "active"
    """Ready for use. Roboto creates every organization in this state."""

    Deprovisioning = "de-provisioning"
    """Unused. Roboto never sets this state, including when it deletes an organization."""


class OrgTier(StrEnum):
    """Subscription tier of an organization, which sets its usage limits and which features it can use."""

    free = "free"
    """Free tier, with lower usage limits and fewer features than premium."""

    premium = "premium"
    """Premium tier, with higher usage limits and more features than free."""


class EventModel(StrEnum):
    """Stage of an organization's move from the legacy event store to the session event store.

    Events on datasets, files, topics and message paths (IDs beginning with ``ev_``) live in the legacy store. Events
    on sessions (IDs beginning with ``evt_``) live in the session store. An organization moves forward through these
    stages, never back, in the order the members are listed.
    """

    Legacy = "legacy"
    """Only the legacy store. Session events cannot be created or read."""

    Dual = "dual"
    """Both stores, each readable and writable."""

    Migrating = "migrating"
    """Both stores. The legacy store is read-only while its events are copied to the session store."""

    Session = "session"
    """Only the session store. Legacy events cannot be created or read."""


class OrgRecord(pydantic.BaseModel):
    """Data record of an organization, as the Roboto API returns it.

    An organization is a workspace in which users share datasets, actions and other resources in Roboto.
    :py:class:`~roboto.domain.orgs.Org` wraps this record with methods that act on the organization.
    """

    org_id: str
    """Unique ID of the organization, beginning with ``og_``."""

    name: str
    """Human-readable name of the organization."""

    tier: OrgTier
    """Subscription tier of the organization."""

    status: OrgStatus
    """Lifecycle state of the organization."""

    created: datetime.datetime
    """Time the organization was created."""

    created_by: typing.Optional[str] = None
    """ID of the user who created the organization."""

    event_model: EventModel = EventModel.Legacy
    """Stage of the organization's move from the legacy event store to the session event store."""

    access_control_features: bool = False
    """Whether Roboto has turned on groups, restricted records and organization-defined roles for the organization.
    Only Roboto staff can change it. While it is off, the organization's groups and roles cannot be made or changed,
    and the web app does not offer to restrict a dataset or collection, though the API restricts one either way."""


class OrgEmailDomainStatus(StrEnum):
    """Verification status of an email domain an organization holds.

    Only a verified domain shows that the organization controls it.
    """

    ProvisionallyApproved = "provisionally_approved"
    """Approved for the organization by Roboto without verification.

    The approval lasts until ``OrgEmailDomainRecord.provisional_approval_expires_at``, and the status stays
    ``ProvisionallyApproved`` after that.
    """

    Unapproved = "unapproved"
    """Neither verified nor provisionally approved, as is a domain bound where Roboto does not require verification."""

    Verified = "verified"
    """Verified, either because Roboto found the DNS TXT record it issued for the domain or by a Roboto administrator.

    ``OrgEmailDomainRecord.verification_method`` says which.
    """


class OrgEmailDomainVerificationMethod(StrEnum):
    """Method by which an email domain was verified."""

    DnsTxt = "dns_txt"
    """Roboto found, at the domain, the DNS TXT record it issued for the organization's verification of it."""

    Staff = "staff"
    """A Roboto administrator verified the domain."""


class OrgEmailDomainRecord(pydantic.BaseModel):
    """Data record of an email domain an organization holds, as the Roboto API returns it.

    People who sign up with an address at the domain join the organization while ``auto_join`` is on and the domain is
    verified, or provisionally approved by Roboto with an approval that has not expired. Where Roboto does not require
    email domains to be verified, an unapproved domain lets them join too.

    Returned by :py:meth:`~roboto.domain.orgs.Org.check_email_domain_verification` and
    :py:meth:`~roboto.domain.orgs.Org.set_email_domain_auto_join`, and listed by
    :py:meth:`~roboto.domain.orgs.Org.email_domain_listing`.
    """

    auto_join: bool
    """Whether auto-join is on: whether people who sign up with an address at the domain join the organization."""

    created: datetime.datetime
    """Time the organization started holding the domain."""

    email_domain: str
    """Email domain, such as ``example.com``, in lowercase."""

    may_turn_on_auto_join: bool
    """Whether auto-join could be turned on for the domain when Roboto built this record.

    It is ``True`` when the domain was verified then, or provisionally approved with an approval that had not expired.
    Every caller gets the same value; only an organization administrator can turn auto-join on.
    """

    org_id: str
    """ID of the organization that holds the domain."""

    provisional_approval_expires_at: typing.Optional[datetime.datetime] = None
    """Time Roboto's provisional approval of the domain expires.

    ``None`` unless ``status`` is ``ProvisionallyApproved``.
    """

    status: OrgEmailDomainStatus
    """Verification status of the domain."""

    verification_method: typing.Optional[OrgEmailDomainVerificationMethod] = None
    """Method by which the domain was verified, or ``None`` unless ``status`` is ``Verified``."""

    verified_at: typing.Optional[datetime.datetime] = None
    """Time the domain was verified, or ``None`` unless ``status`` is ``Verified``."""


class EmailDomainVerificationChallengeRecord(pydantic.BaseModel):
    """Data record of an organization's pending verification of an email domain, as the Roboto API returns it.

    The verification completes when an organization administrator asks Roboto to check the domain, with
    :py:meth:`~roboto.domain.orgs.Org.check_email_domain_verification`, before ``expires_at``, and Roboto finds the DNS
    TXT record it issued for the verification. Carried in ``OrgEmailDomainListing.verification_challenges``,
    :py:attr:`~roboto.domain.orgs.BindEmailDomainResponse.verification_challenge` and
    :py:attr:`~roboto.domain.orgs.EmailDomainVerificationChallengeResponse.verification_challenge`.
    """

    auto_join_on_verify: bool
    """Whether auto-join turns on when the verification completes, for a domain the organization does not hold yet.

    A domain the organization already holds keeps its auto-join setting.
    """

    created: datetime.datetime
    """Time Roboto issued the verification's current DNS TXT record."""

    email_domain: str
    """Email domain being verified."""

    expires_at: datetime.datetime
    """Time from which the verification's DNS TXT record no longer completes it, 14 days after ``created``."""

    org_id: str
    """ID of the organization verifying the domain."""


class EmailDomainVerificationTxtRecord(pydantic.BaseModel):
    """DNS TXT record to publish at an email domain to verify it for an organization.

    Roboto shows its value once, in the response to the request that issued it, and keeps only a hash of its token.
    Carried in :py:attr:`~roboto.domain.orgs.CreateOrgResponse.verification_txt_record`,
    :py:attr:`~roboto.domain.orgs.BindEmailDomainResponse.verification_txt_record` and
    :py:attr:`~roboto.domain.orgs.EmailDomainVerificationChallengeResponse.verification_txt_record`.
    """

    name: str
    """DNS name to publish the record at, which is the email domain."""

    value: str
    """Value of the record: ``roboto-domain-verification=`` followed by a token."""


class OrgEmailDomainListing(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.orgs.Org.email_domain_listing`.

    Holds the email domains an organization holds, and its unexpired verifications of email domains.
    """

    email_domains: list[OrgEmailDomainRecord]
    """Email domains the organization holds."""

    verification_challenges: list[EmailDomainVerificationChallengeRecord]
    """Unexpired verifications of email domains that the organization has in progress."""


class OrgRoleName(StrEnum):
    """Role a user holds in an organization.

    Each role includes the permissions of the roles below it: ``owner`` includes ``admin``, and ``admin`` includes
    ``user``. The user who creates an organization holds all three.
    """

    user = "user"
    """Member of the organization, with access to its resources."""

    admin = "admin"
    """Member who can also manage the organization's settings, such as roles, email domains and integrations."""

    owner = "owner"
    """Member who can also update and delete the organization."""


class OrgBuiltInRole(StrEnum):
    """The built-in role a member of an organization holds. Every member holds exactly one, and each includes the one
    before it: a member may do everything a guest may, an admin everything a member may, and an owner everything an
    admin may.

    Presets and roles the organization defines add to a member's built-in role, whether held by the member or by a
    group they are in. Every such role gives only what a member already has, so it changes what a guest may do and
    nothing for anyone else. Guest exists only in an organization whose ``access_control_features`` is on; in every
    other organization every member is a member, admin or owner.
    """

    guest = "guest"
    """May do what every member always may, such as reading the organization, its members, groups and roles, plus
    what their roles, their groups' roles and records shared with them allow. A guest never invites anyone or changes
    the organization's members, groups, roles or settings."""

    member = "member"
    """May open, change and upload to the organization's records that are not restricted, and invite people."""

    admin = "admin"
    """May also run the organization (its members, invites, groups, roles and settings) and open its restricted
    records."""

    owner = "owner"
    """May also change and delete the organization."""


GuestOrMember: typing.TypeAlias = typing.Literal[OrgBuiltInRole.guest, OrgBuiltInRole.member]
"""The built-in roles a member is given by setting their roles or by accepting an invite: guest or member. Admin and
owner are given through the organization's membership update, and admin also through an invite's ``role``."""


class OrgRoleKind(StrEnum):
    """Who defined a role an organization's members can hold."""

    built_in = "built_in"
    """One of the four built-in roles (:py:class:`OrgBuiltInRole`), which nobody may change or delete. A member's
    membership sets their built-in role; no member's or group's list of roles may name one."""

    preset = "preset"
    """A role Roboto defined, which any organization's admins and owners may give and nobody may change or delete."""

    org_defined = "org_defined"
    """A role the organization's admins or owners defined."""


class OrgInviteStatus(StrEnum):
    """Status of an invitation to join an organization."""

    Pending = "pending"
    """Not yet accepted, declined, revoked, or past its expiry. The invited user may still accept or decline it."""

    Accepted = "accepted"
    """Accepted by the invited user, who became a member."""

    Declined = "declined"
    """Declined by the invited user."""

    Revoked = "revoked"
    """Withdrawn by its sender or an organization administrator, or replaced by a Roboto administrator's new one."""

    Expired = "expired"
    """Past its expiry while still pending."""


class OrgRoleHeldDirectly(pydantic.BaseModel):
    """A role held by the member themselves."""

    kind: typing.Literal["direct"] = "direct"


class OrgRoleHeldThroughGroup(pydantic.BaseModel):
    """A role held through a group of the organization the member is in."""

    kind: typing.Literal["group"] = "group"

    group_id: str
    """The group's ID."""

    name: str
    """The group's name."""


OrgRoleSource = typing.Annotated[
    typing.Union[OrgRoleHeldDirectly, OrgRoleHeldThroughGroup], pydantic.Field(discriminator="kind")
]
"""How a member holds a role: themselves (``{"kind": "direct"}``) or through a group (``{"kind": "group", "group_id",
"name"}``)."""


class OrgHeldRoleRecord(pydantic.BaseModel):
    """A role a member of an organization holds, a preset or one the organization defined, and every way they hold
    it."""

    role_id: str
    """The role's ID, which starts with ``rl_`` for a role the organization defined and ``preset_`` for a preset."""

    name: str
    """The role's name."""

    through: list[OrgRoleSource]
    """Every way the member holds the role: themselves, and each group of the organization that holds it and that
    they are in."""


class OrgUserRecord(pydantic.BaseModel):
    """Data record of a user's membership in an organization, as the Roboto API returns it.

    :py:meth:`~roboto.domain.orgs.Org.users` returns one for each member.
    """

    user: UserRecord
    """Record of the member."""

    org: OrgRecord
    """Record of the organization."""

    roles: list[OrgRoleName]
    """Roles the member holds in the organization.

    A guest and a member both hold ``["user"]``; :py:attr:`built_in_role` tells them apart.
    """

    built_in_role: typing.Optional[OrgBuiltInRole] = None
    """The user's built-in role in the organization: ``owner``, ``admin``, ``guest`` or ``member``. Filled on every
    membership a Roboto deployment returns; ``None`` only from an older deployment. It reads ``guest`` only where roles
    apply: in an organization whose ``access_control_features`` is on. Elsewhere a guest reads ``member``."""

    held_roles: typing.Optional[list[OrgHeldRoleRecord]] = None
    """The roles, presets included, that the user holds, themselves or through a group, one entry per role with every
    way they hold it, ordered by name whatever its case. Each adds to what the user's :py:attr:`built_in_role` lets
    them do. Filled by the organization's members list (:py:meth:`~roboto.domain.orgs.Org.users`) and the response to
    setting a member's roles, only where roles apply (as for :py:attr:`built_in_role`), where a member who holds no
    role gets an empty list. ``None`` everywhere else, so a non-``None`` value means roles apply to the
    organization."""


class OrgGroupRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a group of an organization's members, which the organization's records
    can be shared with."""

    group_id: str
    """Unique identifier for the group."""

    org_id: str
    """Organization the group belongs to."""

    name: str
    """The group's name, unique within its organization whatever its case."""

    description: typing.Optional[str] = None
    """What the group is for, as its organization's admins wrote it."""

    created_by: typing.Optional[str] = None
    """User ID of the person who made the group."""

    created: datetime.datetime
    """When the group was made."""

    role_ids: typing.Optional[list[str]] = None
    """The IDs of the roles the group holds, presets included, ordered by ID. Each member of the group holds them
    through it. ``None`` unless roles apply to the organization (see :py:attr:`OrgUserRecord.held_roles`)."""


class OrgGroupMemberRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a member of an organization's group."""

    user: UserRecord
    """User information for the group member."""

    added_by: typing.Optional[str] = None
    """User ID of the person who added them to the group."""

    added: datetime.datetime
    """When they were added to the group."""


class OrgRoleRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a role an organization's members can hold, as the organization's roles
    list returns it.

    A role is one of the four built-in roles (:py:class:`OrgBuiltInRole`), a preset that Roboto defined, or one the
    organization's admins or owners defined; :py:attr:`kind` says which. Every member holds exactly one built-in role.
    Any member, and any group of the organization, may also hold presets and roles the organization defined. Each of
    those is a set of switches, such as ``view_data`` or ``upload_data``, and each switch lets its holder do a group of
    things with the organization's records that are not restricted. A member may do what their built-in role lets them
    do plus what the switches of every role they hold, themselves or through a group, turn on. Roles only add to what a
    member may do. Every switch gives only what a member already has, so these roles change what a guest may do and
    nothing for a member, admin or owner.

    Presets and roles the organization defined can be given only in an organization whose ``access_control_features``
    is on.
    """

    role_id: str
    """The role's ID: the :py:class:`OrgBuiltInRole` value for a built-in role, and otherwise starting with ``rl_``
    for a role the organization defined and ``preset_`` for a preset."""

    org_id: str
    """Organization the role belongs to, or, for a built-in role or a preset, the organization it was listed for."""

    name: str
    """The role's name. No two roles the organization defined share a name, whatever its case."""

    description: typing.Optional[str] = None
    """What the role is for. For a built-in role, what it allows that no switch gives."""

    switches: list[str]
    """The switches the role turns on, in the order Roboto lists them; every other switch is off. A built-in role
    lists each switch whose every operation it allows."""

    kind: OrgRoleKind = OrgRoleKind.org_defined
    """Who defined the role. Only a role the organization defined can be changed or deleted."""

    created_by: typing.Optional[str] = None
    """User ID of the person who defined the role; ``None`` for a built-in role or a preset."""

    created: typing.Optional[datetime.datetime] = None
    """When the role was defined; ``None`` for a built-in role or a preset."""

    modified_by: typing.Optional[str] = None
    """User ID of the person who last changed the role; ``None`` for a built-in role or a preset."""

    modified: typing.Optional[datetime.datetime] = None
    """When the role was last changed; ``None`` for a built-in role or a preset."""


class OrgInviteRecord(pydantic.BaseModel):
    """Data record of an invitation to join an organization, as the Roboto API returns it.

    :py:class:`~roboto.domain.orgs.OrgInvite` wraps this record with methods to accept or decline the invitation.
    """

    invite_id: str
    """Unique ID of the invitation, beginning with ``in_``."""

    user_id: str
    """ID of the invited user, which for a person is their email address."""

    invited_by: UserRecord
    """Record of the user who sent the invitation."""

    org: OrgRecord
    """Record of the organization the invitation is to."""

    role: OrgRoleName = OrgRoleName.user
    """Role the invited user gets in the organization by accepting."""

    built_in_role: typing.Optional[GuestOrMember] = None
    """On an invite with the ``user`` role, the built-in role the invited user gets in the organization by accepting,
    where ``None`` means a member. ``None`` on an invite with any other role, whose :py:attr:`role` decides."""

    status: OrgInviteStatus = OrgInviteStatus.Pending
    """Status of the invitation when Roboto read it. A pending invitation reads as ``Expired`` after its expiry."""

    expires_at: typing.Optional[datetime.datetime] = None
    """Time after which the invitation cannot be accepted, unless an organization administrator renews it.

    ``None`` from a Roboto deployment that does not set invitation expiry.
    """

    latest_email_bounced: bool = False
    """Whether the most recent email of the invitation bounced. ``False`` while a resent email waits to be sent."""
