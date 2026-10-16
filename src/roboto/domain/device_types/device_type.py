# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...association import Association
from ...http import RobotoClient
from ..devices import Device, DeviceRecord
from ..files import FileSystem
from .operations import (
    CreateDeviceTypeRequest,
    UpdateDeviceTypeRequest,
)
from .record import DeviceTypeRecord


class DeviceType:
    """A named kind of device within an organization, such as one robot model.

    A :py:class:`~roboto.domain.devices.Device` has at most one device type, whose ID is its
    :py:attr:`~roboto.domain.devices.Device.device_type_id`. A device type has its own configurations
    (:py:attr:`configurations`), such as a URDF or a bill of materials that applies to every device of that type, and
    its own description, metadata and tags. Devices inherit none of the type's description, metadata or tags. A
    device's configurations listed with ``include_inherited=True``
    (:py:meth:`~roboto.domain.files.FileSystem.list_files`) include its type's configurations beside its own.

    Device type IDs (``dt_...``) are assigned by Roboto; the name is user-provided and unique within the org.

    Note:
        Device types cannot be instantiated directly through the constructor. Use the class methods
        :py:meth:`create`, :py:meth:`from_id`, or :py:meth:`for_org` to obtain DeviceType instances.

    Examples:
        Give every device of a type the same URDF, then read it back from one device:

        >>> import pathlib
        >>> from roboto import Device, DeviceType
        >>> device_type = DeviceType.create(name="mk2", description="Second-generation arm")
        >>> device_type.configurations.upload_file(pathlib.Path("/path/to/mk2.urdf"), "mk2.urdf")
        >>> device = Device.from_id("robot_001").set_device_type(device_type.device_type_id)
        >>> for file in device.configurations.list_files(include_inherited=True):
        ...     print(file.relative_path, file.association.is_device_type)
        mk2.urdf True
    """

    __record: DeviceTypeRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "DeviceType":
        """Create a device type in an organization.

        Args:
            name: Name of the device type, unique within the organization.
            description: Optional free-text description of the device type.
            metadata: Optional key-value pairs to associate with the device type.
            tags: Optional tags to associate with the device type.
            caller_org_id: The organization to create the device type in. If not specified and the caller belongs
                to only one organization, that organization will be used. Required if the caller belongs to
                multiple organizations.
            roboto_client: Optional RobotoClient instance for API communication. If not provided, the default
                client configuration will be used.

        Returns:
            The newly created device type.

        Raises:
            RobotoConflictException: The organization already has a device type with this name.
            RobotoFeatureNotAvailableException: Device types are not enabled for the organization.
            RobotoUnauthorizedException: The caller lacks permission to manage devices in the organization.

        Examples:
            >>> device_type = DeviceType.create(name="mk2", description="Second-generation arm", tags=["arm"])
            >>> device_type.device_type_id
            'dt_abc123'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDeviceTypeRequest(
            name=name,
            description=description,
            metadata=metadata or {},
            tags=tags or [],
        )
        record = roboto_client.post("v1/device-types/create", caller_org_id=caller_org_id, data=request).to_record(
            DeviceTypeRecord
        )
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Generator["DeviceType", None, None]:
        """List an organization's device types, newest first.

        Args:
            org_id: The organization ID to list device types for.
            roboto_client: Optional RobotoClient instance for API communication. If not provided, the default
                client configuration will be used.

        Yields:
            Each of the organization's device types, fetched a page at a time.

        Raises:
            RobotoFeatureNotAvailableException: Device types are not enabled for the organization.
            RobotoUnauthorizedException: The caller lacks permission to manage devices in the organization.

        Examples:
            >>> for device_type in DeviceType.for_org("og_abc123"):
            ...     print(device_type.name)
            mk3
            mk2
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if next_token:
                query_params["page_token"] = str(next_token)

            results = roboto_client.get(
                f"v1/device-types/org/{org_id}",
                query=query_params,
            ).to_paginated_list(DeviceTypeRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def from_id(
        cls,
        device_type_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        org_id: typing.Optional[str] = None,
    ) -> "DeviceType":
        """Retrieve a device type by its ID.

        Args:
            device_type_id: The Roboto-assigned ``dt_`` ID of the device type, not its name.
            roboto_client: Optional RobotoClient instance for API communication. If not provided, the default
                client configuration will be used.
            org_id: The organization that owns the device type. If not specified and the caller belongs to only
                one organization, that organization will be used. Required if the caller belongs to multiple
                organizations.

        Returns:
            The device type.

        Raises:
            RobotoFeatureNotAvailableException: Device types are not enabled for the organization.
            RobotoNotFoundException: The organization has no device type with this ID.
            RobotoUnauthorizedException: The caller lacks permission to view the device type.

        Examples:
            >>> device_type = DeviceType.from_id("dt_abc123", org_id="og_abc123")
            >>> device_type.name
            'mk2'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/device-types/id/{device_type_id}",
            owner_org_id=org_id,
        ).to_record(DeviceTypeRecord)
        return cls(record=record, roboto_client=roboto_client)

    def __init__(self, record: DeviceTypeRecord, roboto_client: typing.Optional[RobotoClient] = None):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """The timestamp when this device type was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """The user ID of the person who created this device type."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Free-text description of this device type."""
        return self.__record.description

    @property
    def device_count(self) -> int:
        """Number of devices of this device type, counted when Roboto returned this device type.

        The count does not follow devices added or removed later; call :py:meth:`from_id` for a current count.
        """
        return self.__record.device_count

    @property
    def device_type_id(self) -> str:
        """This device type's Roboto-assigned ``dt_`` ID, unique across all orgs and never changed."""
        return self.__record.device_type_id

    @property
    def configurations(self) -> FileSystem:
        """Files that apply to every device of the type, such as a URDF."""
        return FileSystem(
            Association.device_type(self.device_type_id),
            roboto_client=self.__roboto_client,
            org_id=self.org_id,
        )

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata pairs associated with this device type."""
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        """The timestamp when this device type was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """The user ID of the person who last modified this device type."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """This device type's name, unique within its org."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """The ID of the org to which this device type belongs."""
        return self.__record.org_id

    @property
    def record(self) -> DeviceTypeRecord:
        """Underlying :py:class:`DeviceTypeRecord` for this device type.

        This is the raw record as returned by Roboto and may evolve over time; prefer the public
        :py:class:`DeviceType` API unless you need direct access to the record.
        """
        return self.__record

    @property
    def tags(self) -> list[str]:
        """List of tags associated with this device type."""
        return self.__record.tags

    def delete(self) -> None:
        """Delete this device type.

        Refused while any device is of this type; reassign or clear those devices' types first. The device type's
        configurations (:py:attr:`configurations`) are deleted with it, every version of each file, shortly after
        this call returns. Links elsewhere that point at those files stop working.
        Deleting a device type that no longer exists succeeds.

        Raises:
            RobotoConflictException: At least one device is of this type.
            RobotoFeatureNotAvailableException: Device types are not enabled for the organization.
            RobotoUnauthorizedException: The caller lacks permission to delete this device type.

        Examples:
            >>> device_type = DeviceType.from_id("dt_abc123")
            >>> device_type.delete()
        """
        self.__roboto_client.delete(
            f"v1/device-types/id/{self.device_type_id}",
            owner_org_id=self.org_id,
        )

    def devices(self) -> collections.abc.Generator[Device, None, None]:
        """List the devices that are of this device type, newest first.

        Yields:
            Each device of this type, fetched a page at a time.

        Raises:
            RobotoFeatureNotAvailableException: Device types are not enabled for the organization.
            RobotoUnauthorizedException: The caller lacks permission to view this device type, or to manage devices in
                its org.

        Examples:
            >>> device_type = DeviceType.from_id("dt_abc123")
            >>> for device in device_type.devices():
            ...     print(device.device_id)
            robot_002
            robot_001
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/device-types/id/{self.device_type_id}/devices",
                owner_org_id=self.org_id,
                query=query,
            ).to_paginated_list(DeviceRecord)

            for record in page.items:
                yield Device(record=record, roboto_client=self.__roboto_client)

            next_token = page.next_token
            if not next_token:
                break

    def update(self, request: UpdateDeviceTypeRequest) -> "DeviceType":
        """Update this device type's name, description, metadata or tags.

        Args:
            request: The changes to apply. Fields left at their defaults change nothing.

        Returns:
            Updated DeviceType instance with the changes applied.

        Raises:
            RobotoConflictException: The new name is already taken by another device type in the org.
            RobotoFeatureNotAvailableException: Device types are not enabled for the organization.
            RobotoUnauthorizedException: The caller lacks permission to edit this device type.

        Examples:
            Rename a device type and clear its description:

            >>> from roboto import UpdateDeviceTypeRequest
            >>> device_type = DeviceType.from_id("dt_abc123")
            >>> device_type = device_type.update(UpdateDeviceTypeRequest(name="mk2-rev-b", description=None))
        """
        record = self.__roboto_client.put(
            f"v1/device-types/id/{self.device_type_id}",
            owner_org_id=self.org_id,
            data=request,
        ).to_record(DeviceTypeRecord)
        return DeviceType(record=record, roboto_client=self.__roboto_client)
