# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pydantic

from .compat import StrEnum


class RobotoPrincipalType(StrEnum):
    """Type of a principal: the kind of identity a ``RobotoPrincipal`` names."""

    Device = "device"
    """Devices (:py:class:`~roboto.domain.devices.Device`)."""

    Integration = "integration"
    """Integrations: Roboto features, such as the Slack app, that record changes under their own identity."""

    Invocation = "invocation"
    """Invocations of actions (:py:class:`~roboto.domain.actions.Invocation`)."""

    User = "user"
    """Users (:py:class:`~roboto.domain.users.User`)."""

    Org = "org"
    """Organizations (:py:class:`~roboto.domain.orgs.Org`)."""


class RobotoPrincipal(pydantic.BaseModel):
    """A principal: an identity that acts in Roboto or owns a resource, such as a user, a device, or an organization.

    Fields such as a dataset's ``created_by`` hold a principal in its string form, ``<type>:<id>``, which
    ``from_string`` parses. Creating a principal, directly or with any method
    of this class, raises ``pydantic.ValidationError`` when its ID contains a colon.
    """

    ptype: RobotoPrincipalType
    """Type of the principal, such as user or device."""

    id: str
    """ID of the principal, unique among principals of its type.

    For users, organizations, invocations and integrations, this is the resource's own ID. A device's ID is unique only
    within its organization, so a device principal's ID is ``<device_id>@<org_id>``: device ``sn001`` in organization
    ``og_12345`` has the ID ``sn001@og_12345``.
    """

    @pydantic.field_validator("id")
    def validate_id(cls, value: str) -> str:
        """Reject an ID that contains a colon, which separates the type from the ID in the string form.

        Pydantic calls this while it builds a principal.
        """
        if ":" in value:
            raise ValueError(f"ID cannot contain a colon, got {value}")

        return value

    @classmethod
    def for_device(cls, device_id: str, org_id: str) -> RobotoPrincipal:
        """Build the principal of a device, whose ID is ``<device_id>@<org_id>``.

        Args:
            device_id: ID the organization gave the device, such as a serial number.
            org_id: ID of the organization that owns the device.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Device, id=f"{device_id}@{org_id}")

    @classmethod
    def for_integration(cls, integration_id: str) -> RobotoPrincipal:
        """Build the principal of an integration.

        Args:
            integration_id: ID of the integration, such as ``slack``.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Integration, id=integration_id)

    @classmethod
    def for_invocation(cls, invocation_id: str) -> RobotoPrincipal:
        """Build the principal of an invocation of an action.

        Args:
            invocation_id: ID of the invocation, beginning with ``iv_``.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Invocation, id=invocation_id)

    @classmethod
    def for_org(cls, org_id: str) -> RobotoPrincipal:
        """Build the principal of an organization.

        Args:
            org_id: ID of the organization.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.Org, id=org_id)

    @classmethod
    def for_user(cls, user_id: str) -> RobotoPrincipal:
        """Build the principal of a user.

        Args:
            user_id: ID of the user, which for a person is their email address.
        """
        return RobotoPrincipal(ptype=RobotoPrincipalType.User, id=user_id)

    @classmethod
    def from_string(cls, serialized_principal: str) -> RobotoPrincipal:
        """Parse a principal from its ``<type>:<id>`` string form, as ``str()`` of a principal returns it.

        Text after a second colon is dropped: ``user:a:b`` parses as user ``a``.

        Args:
            serialized_principal: Principal in its string form, such as ``user:<user_id>`` or
                ``device:<device_id>@<org_id>``.

        Raises:
            ValueError: The text before the first colon, or the whole string when it has none, is not a
                ``RobotoPrincipalType`` value.
            IndexError: The string is a type with no colon after it, such as ``user``.
        """
        return RobotoPrincipal(
            ptype=RobotoPrincipalType(serialized_principal.split(":")[0]),
            id=serialized_principal.split(":")[1],
        )

    def __str__(self):
        """Return the principal's ``<type>:<id>`` string form."""
        return f"{self.ptype.value}:{self.id}"
