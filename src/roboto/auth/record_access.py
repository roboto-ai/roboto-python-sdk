# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import typing

import pydantic


class AccessSubjectKind(str, enum.Enum):
    """Kind of subject a grant on a dataset, collection or View names."""

    User = "user"
    """One user, named by user ID."""

    Group = "group"
    """Every member of one group, named by group ID."""

    OrgMembers = "org_members"
    """Every member of one organization, named by organization ID.

    A grant to it may be added only on a dataset, collection or View of that organization.
    """

    Everyone = "everyone"
    """Every signed-in Roboto user. Takes no ID, and may hold only ``AccessRole.Viewer``."""


class AccessRole(str, enum.Enum):
    """Role a grant gives its subject on a dataset, collection or View: what the subject may do with it.

    Each role includes the ones before it: ``Editor`` may do everything ``Viewer`` may, and ``Deleter`` everything
    ``Editor`` may.
    """

    Viewer = "viewer"
    """Permission to read the dataset, collection or View."""

    Editor = "editor"
    """Permission to read and change the dataset, collection or View, and to add or remove its grants.

    On a dataset or collection, an editor may also set whether it is restricted; on a View, only the View's author and
    the organization's admins and owners may.
    """

    Deleter = "deleter"
    """On a dataset or collection, permission to do everything an editor may and to delete it.

    On a View, only what an editor may do, since only a View's author and its organization's admins and owners may
    delete it; a View takes no new ``Deleter`` grant.
    """


class AccessSubject(pydantic.BaseModel):
    """Subject of a grant on a dataset, collection or View: whom the grant names.

    A subject is one user, every member of one group or organization, or every signed-in Roboto user. Serialized
    without ``id`` when ``id`` is ``None``, as an ``AccessSubjectKind.Everyone`` subject is.

    Examples:
        >>> from roboto.auth import AccessSubject
        >>> AccessSubject.user("ben@example.com").model_dump(mode="json")
        {'kind': 'user', 'id': 'ben@example.com'}
        >>> AccessSubject.everyone().model_dump(mode="json")
        {'kind': 'everyone'}
    """

    kind: AccessSubjectKind
    """Kind of subject."""

    id: typing.Optional[str] = None
    """ID of the user, group or organization the subject names.

    ``None`` for an ``AccessSubjectKind.Everyone`` subject.
    """

    @classmethod
    def user(cls, user_id: str) -> "AccessSubject":
        """Build a subject naming one user.

        Args:
            user_id: ID of the user, which for a person is their email address.
        """
        return cls(kind=AccessSubjectKind.User, id=user_id)

    @classmethod
    def group(cls, group_id: str) -> "AccessSubject":
        """Build a subject naming every member of one group.

        Args:
            group_id: ID of the group.
        """
        return cls(kind=AccessSubjectKind.Group, id=group_id)

    @classmethod
    def org_members(cls, org_id: str) -> "AccessSubject":
        """Build a subject naming every member of one organization.

        A grant to it may be added only on a dataset, collection or View of that organization.

        Args:
            org_id: ID of the organization.
        """
        return cls(kind=AccessSubjectKind.OrgMembers, id=org_id)

    @classmethod
    def everyone(cls) -> "AccessSubject":
        """Build a subject naming every signed-in Roboto user."""
        return cls(kind=AccessSubjectKind.Everyone)

    @pydantic.model_serializer(mode="wrap")
    def _leave_out_a_missing_id(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        serialized = handler(self)
        if serialized.get("id") is None:
            serialized.pop("id", None)
        return serialized


class AccessGrant(pydantic.BaseModel):
    """Grant on a dataset, collection or View: a subject and the role it holds there.

    Examples:
        >>> from roboto.auth import AccessGrant, AccessRole, AccessSubject
        >>> grant = AccessGrant(subject=AccessSubject.user("ben@example.com"), role=AccessRole.Viewer)
    """

    subject: AccessSubject
    """Subject the grant names."""

    role: AccessRole
    """Role the grant gives the subject."""


class RecordAccessResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.collections.Collection.get_record_access`.

    It holds who a dataset, collection or View (the record) is shared with.
    :py:meth:`~roboto.domain.collections.Collection.edit_record_access` returns it too, after its change. From API
    version 2026-11-19, ``GET`` and ``PUT`` on ``/v1/datasets/{dataset_id}/access``,
    ``/v1/collections/{collection_id}/access`` and ``/v1/views/id/{view_id}/access`` return it.
    """

    restricted: bool
    """Whether members of the record's organization need a grant to reach it.

    While a dataset or collection is unrestricted, every member of its organization may read, change, share and delete
    it; while a View is unrestricted, every member may read it. The organization's admins and owners, and a View's
    author, reach the record either way.

    A collection starts unrestricted. A dataset starts unrestricted unless its organization's admins have stored
    ``true`` under the organization config key ``org_new_datasets_start_restricted``. A View starts restricted unless it
    is created with :py:attr:`~roboto.domain.views.ViewVisibility.Organization` visibility."""

    grants: list[AccessGrant] = pydantic.Field(default_factory=list)
    """Grants on the record, ordered by subject kind, then subject ID, then role."""


class EditRecordAccessRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.collections.Collection.edit_record_access`.

    It changes who a dataset, collection or View (the record) is shared with. From API version 2026-11-19, ``PUT`` on
    ``/v1/datasets/{dataset_id}/access``, ``/v1/collections/{collection_id}/access`` and
    ``/v1/views/id/{view_id}/access`` takes it. Roboto applies the change whole or not at all, in this order:

    1. Adds the grants in ``add``.
    2. Removes the grants in ``remove``.
    3. Sets the record's restriction, when ``restricted`` is not ``None``.

    A request that changes nothing returns who the record is shared with, and needs only permission to read the
    record.
    """

    add: list[AccessGrant] = pydantic.Field(default_factory=list)
    """Grants to add. Defaults to none.

    A grant to ``AccessSubjectKind.OrgMembers`` may name only the record's own organization,
    ``AccessSubjectKind.Everyone`` may be given only ``AccessRole.Viewer``, and a View takes no new
    ``AccessRole.Deleter`` grant. A grant that breaks one of these rules raises ``RobotoInvalidRequestException``.
    """

    remove: list[AccessGrant] = pydantic.Field(default_factory=list)
    """Grants to remove. Defaults to none.

    A grant that ``add`` would refuse, such as a grant to another organization's members, may still be removed.
    Removing a grant the record does not hold changes nothing.
    """

    restricted: typing.Optional[bool] = None
    """Whether members of the record's organization need a grant to reach it, or ``None`` to leave it as it is.

    On a View, only the View's author and its organization's admins and owners may set it.
    """
