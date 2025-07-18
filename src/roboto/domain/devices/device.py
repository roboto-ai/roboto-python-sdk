# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...exceptions import RobotoDomainException
from ...http import RobotoClient
from ..tokens import (
    CreateTokenRequest,
    Token,
    TokenRecord,
)
from .operations import CreateDeviceRequest
from .record import DeviceRecord


class Device:
    """A device is a non-human entity that can interact with Roboto on behalf of an organization.

    Devices represent robots, systems, or other non-human entities that
    need to authenticate and interact with the Roboto platform. Each device is uniquely
    identified by a device_id within its organization and can be assigned API tokens for
    secure authentication.

    Common device types include:

    - Robots that upload log data directly from their onboard software
    - Automated upload stations that collect and transmit data from multiple sources
    - Edge computing devices that process and forward data to Roboto

    Devices are associated with :py:class:`~roboto.domain.orgs.Org` entities and can create
    :py:class:`~roboto.domain.tokens.Token` objects for authentication. The underlying data
    is stored in :py:class:`DeviceRecord` objects for wire transmission.

    Device IDs are typically meaningful identifiers like serial numbers, asset tags, or
    other organization-specific naming schemes that help identify the physical or logical
    entity in the real world.

    Note:
        Devices cannot be instantiated directly through the constructor. Use the class
        methods :py:meth:`create`, :py:meth:`from_id`, or :py:meth:`for_org` to obtain
        Device instances.
    """

    __roboto_client: RobotoClient
    __record: DeviceRecord

    # Class methods + Constructor

    @classmethod
    def create(
        cls,
        device_id: str,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Device":
        """Register a new device with the Roboto platform.

        Creates a new device entity that can authenticate and interact with Roboto
        on behalf of the specified organization. The device_id must be unique within
        the organization.

        Args:
            device_id: A user-provided identifier for the device, unique within the organization.
                This is typically a meaningful identifier like a serial number, asset tag,
                or other organization-specific naming scheme.
            caller_org_id: The organization ID to register the device under. If not specified
                and the caller belongs to only one organization, that organization will be used.
                Required if the caller belongs to multiple organizations.
            roboto_client: Optional RobotoClient instance for API communication. If not provided,
                the default client configuration will be used.

        Returns:
            A Device instance representing the newly registered device.

        Raises:
            RobotoConflictException: If a device with the same device_id already exists
                in the specified organization.
            RobotoUnauthorizedException: If the caller lacks permission to create devices
                in the specified organization.
            RobotoInvalidRequestException: If the device_id is invalid or the organization
                ID is malformed.

        Examples:
            Register a robot device:

            >>> device = Device.create(
            ...     device_id="robot_001",
            ...     caller_org_id="og_abc123"
            ... )
            >>> print(f"Registered device: {device.device_id}")
            Registered device: robot_001

            Register an upload station:

            >>> device = Device.create(device_id="upload_station_alpha")
            >>> print(f"Device org: {device.org_id}")
            Device org: og_xyz789
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDeviceRequest(device_id=device_id, org_id=caller_org_id)
        record = roboto_client.post(
            "v1/devices/create", caller_org_id=caller_org_id, data=request
        ).to_record(DeviceRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Generator["Device", None, None]:
        """List all devices registered for a given organization.

        Retrieves all devices that belong to the specified organization. For organizations
        with large numbers of devices, this method uses pagination and yields results as
        they become available from the API.

        Args:
            org_id: The organization ID to list devices for.
            roboto_client: Optional RobotoClient instance for API communication. If not provided,
                the default client configuration will be used.

        Returns:
            A generator of Device objects. For organizations with many devices, this may involve
            multiple service calls, and the generator will yield results as they become available.

        Raises:
            RobotoUnauthorizedException: If the caller lacks permission to list devices
                in the specified organization.
            RobotoNotFoundException: If the specified organization does not exist.

        Examples:
            List all devices in an organization:

            >>> for device in Device.for_org("og_abc123"):
            ...     print(f"Device: {device.device_id} (created: {device.created})")
            Device: robot_001 (created: 2024-01-15 10:30:00)
            Device: upload_station_beta (created: 2024-01-17 09:15:00)

            Count devices in an organization:

            >>> device_count = sum(1 for _ in Device.for_org("og_abc123"))
            >>> print(f"Total devices: {device_count}")
            Total devices: 2
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if next_token:
                query_params["page_token"] = str(next_token)

            results = roboto_client.get(
                f"v1/devices/org/{org_id}",
                query=query_params,
            ).to_paginated_list(DeviceRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def from_id(
        cls,
        device_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        org_id: typing.Optional[str] = None,
    ) -> "Device":
        """Retrieve a device by its device ID.

        Looks up and returns a Device instance for the specified device_id. The device_id
        must be unique within the organization scope.

        Args:
            device_id: The device ID to look up. This is the user-provided identifier
                that was specified when the device was created.
            roboto_client: Optional RobotoClient instance for API communication. If not provided,
                the default client configuration will be used.
            org_id: The organization ID that owns the device. If not specified and the caller
                belongs to only one organization, that organization will be used. Required if
                the caller belongs to multiple organizations.

        Returns:
            A Device object representing the specified device.

        Raises:
            RobotoNotFoundException: If the specified device is not registered with Roboto
                or does not exist in the specified organization.
            RobotoUnauthorizedException: If the caller lacks permission to access the device
                or the specified organization.
            RobotoInvalidRequestException: If the device_id or org_id parameters are malformed.

        Examples:
            Retrieve a device by ID with explicit organization:

            >>> device = Device.from_id("robot_001", org_id="og_abc123")
            >>> print(f"Device: {device.device_id} in org {device.org_id}")
            Device: robot_001 in org og_abc123

            Retrieve a device:

            >>> device = Device.from_id("upload_station_alpha")
            >>> print(f"Found device created by: {device.created_by}")
            Found device created by: user@example.com
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/devices/id/{device_id}",
            owner_org_id=org_id,
        ).to_record(DeviceRecord)
        return cls(record=record, roboto_client=roboto_client)

    def __init__(
        self, record: DeviceRecord, roboto_client: typing.Optional[RobotoClient] = None
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """The timestamp when this device was registered with Roboto."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """The user ID of the person who registered this device."""
        return self.__record.created_by

    @property
    def device_id(self) -> str:
        """
        This device's ID. Device ID is a user-provided identifier for a device, which is unique within the
        device's org.
        """
        return self.__record.device_id

    @property
    def modified(self) -> datetime.datetime:
        """The timestamp when this device record was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """The user ID of the person who last modified this device record."""
        return self.__record.modified_by

    @property
    def org_id(self) -> str:
        """
        The ID of the org to which this device belongs.
        """
        return self.__record.org_id

    @property
    def record(self) -> DeviceRecord:
        """
        The underlying DeviceRecord object which represents this device. This is often used as the wire representation
        of a device during API requests, and is subject to evolve over time. You should not program against this
        if avoidable.
        """
        return self.__record

    def create_token(
        self,
        expiry_days: int = 366,
        name: typing.Optional[str] = None,
        description: typing.Optional[str] = None,
    ) -> tuple[Token, str]:
        """Create an authentication token for this device.

        Generates a new API token that can be used to authenticate requests made on behalf
        of this device. The token secret is returned only once and cannot be retrieved again,
        so it must be stored securely by the caller.

        Args:
            expiry_days: Number of days until the token expires. Defaults to 366 days (1 year).
                Must be a positive integer.
            name: Human-readable name for the token. If not provided, defaults to
                "{org_id}_{device_id}" format.
            description: Optional description explaining the token's purpose or usage context.

        Returns:
            A tuple containing:
            - Token: The Token object representing the created token
            - str: The secret token value (only available at creation time)

        Raises:
            RobotoDomainException: If token creation fails or the secret is not returned
                by the server (this should never happen under normal circumstances).
            RobotoUnauthorizedException: If the caller lacks permission to create tokens
                for this device.

        Examples:
            Create a token with default settings:

            >>> device = Device.from_id("robot_001", org_id="og_abc123")
            >>> token, secret = device.create_token()
            >>> print(f"Token created: {token.token_id}")
            >>> print(f"Secret (save this!): {secret}")
            Token created: to_abc123def456
            Secret (save this!): robo_pat_abc123def456...

            Create a token with custom expiry and description:

            >>> token, secret = device.create_token(
            ...     expiry_days=30,
            ...     name="Monthly Upload Token",
            ...     description="Token for automated monthly data uploads"
            ... )
            >>> print(f"Token expires in 30 days: {token.token_id}")
            Token expires in 30 days: to_def789ghi012
        """
        request = CreateTokenRequest(
            expiry_days=expiry_days,
            name=name or f"{self.org_id}_{self.device_id}",
            description=description,
        )

        record = self.__roboto_client.post(
            f"v1/devices/id/{self.device_id}/tokens",
            owner_org_id=self.org_id,
            data=request,
        ).to_record(TokenRecord)

        if record.secret is None:
            raise RobotoDomainException(
                "Token was generated without returning secret value, this should never happen. "
                + "Please reach out to support@roboto.ai"
            )

        return (
            Token(record=record, roboto_client=self.__roboto_client),
            record.secret,
        )

    def delete(self) -> None:
        """Delete this device from the Roboto platform.

        Permanently removes this device and all associated tokens. This action cannot
        be undone. Any tokens created for this device will be immediately invalidated.

        Raises:
            RobotoUnauthorizedException: If the caller lacks permission to delete this device.
            RobotoNotFoundException: If the device has already been deleted or does not exist.

        Examples:
            Delete a device after confirming its identity:

            >>> device = Device.from_id("old_robot_001")
            >>> print(f"Deleting device: {device.device_id}")
            >>> device.delete()
            >>> print("Device deleted successfully")
            Deleting device: old_robot_001
            Device deleted successfully
        """
        self.__roboto_client.delete(
            f"v1/devices/id/{self.device_id}", owner_org_id=self.org_id
        )

    def tokens(self) -> collections.abc.Sequence[Token]:
        """Retrieve all authentication tokens associated with this device.

        Returns a list of all tokens that have been created for this device, including
        both active and expired tokens. The token secrets are not included in the response
        as they are only available at creation time.

        Returns:
            A sequence of Token objects representing all tokens created for this device.
            The sequence may be empty if no tokens have been created.

        Raises:
            RobotoUnauthorizedException: If the caller lacks permission to list tokens
                for this device.

        Examples:
            List all tokens for a device:

            >>> device = Device.from_id("robot_001")
            >>> tokens = device.tokens()
            >>> for token in tokens:
            ...     print(f"Token: {token.token_id}")
            Token: to_abc123def456
            Token: to_ghi789jkl012

            Check if device has any tokens:

            >>> device = Device.from_id("new_robot")
            >>> if device.tokens():
            ...     print("Device has tokens")
            ... else:
            ...     print("No tokens found for device")
            No tokens found for device
        """
        records = self.__roboto_client.get(
            f"v1/devices/id/{self.device_id}/tokens", owner_org_id=self.org_id
        ).to_record_list(TokenRecord)
        return [
            Token(record=record, roboto_client=self.__roboto_client)
            for record in records
        ]
