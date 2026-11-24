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
    """A device type: a named kind of device within an organization, such as one robot model.

    A :py:class:`~roboto.domain.devices.Device` has at most one device type, whose ID is its
    :py:attr:`~roboto.domain.devices.Device.device_type_id`. A device type has its own configurations
    (``configurations``), such as a URDF or a bill of materials that applies to every device of the type, and its own
    description, metadata and tags. Devices inherit none of the type's description, metadata or tags. Listing a
    device's configurations with ``include_inherited=True`` (:py:meth:`~roboto.domain.files.FileSystem.list_files`)
    includes its type's configurations beside its own; where both have a file at the same path, only the device's is
    listed.

    Get a ``DeviceType`` from ``create``, ``from_id``, or ``for_org``. To wrap a ``DeviceTypeRecord`` already fetched
    from Roboto, build a ``DeviceType`` from it directly. Each instance holds a copy of the device type's record;
    ``update`` returns a new instance and leaves this one's record unchanged.

    Args:
        record: Record of the device type.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.

    Examples:
        Give every device of a type the same URDF, then list it among one device's configurations:

        >>> import pathlib
        >>> from roboto import Device, DeviceType
        >>> device_type = DeviceType.create(name="mk2", description="Second-generation arm")
        >>> device_type.configurations.upload_file(pathlib.Path("/path/to/mk2.urdf"), "mk2.urdf")
        >>> device = Device.from_id("robot_001").set_device_type(device_type.device_type_id)
        >>> for file in device.configurations.list_files(include_inherited=True):
        ...     print(file.relative_path, file.association.is_device_type)
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
            name: Human-readable name of the device type, unique within its organization.
            description: Human-readable description of the device type.
            metadata: Key-value metadata to set on the device type. ``None`` sets none.
            tags: Tags to set on the device type. ``None`` sets none.
            caller_org_id: Organization to create the device type in. Required when the caller belongs to more than
                one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new device type.

        Raises:
            RobotoConflictException: The organization already has a device type with this name.

        Examples:
            >>> device_type = DeviceType.create(name="mk2", description="Second-generation arm", tags=["arm"])
            >>> print(device_type.device_type_id)
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
            org_id: ID of the organization whose device types to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each of the organization's device types, fetched a page at a time as the generator advances.

        Raises:
            RobotoUnauthorizedException: The caller cannot manage devices in the organization. It surfaces on the
                first iteration.

        Examples:
            >>> for device_type in DeviceType.for_org("og_abc123"):
            ...     print(device_type.name)
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
        """Fetch a device type by its ID.

        Args:
            device_type_id: Unique ID of the device type, beginning with ``dt_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            org_id: Organization that owns the device type. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.

        Raises:
            RobotoNotFoundException: The organization has no device type with this ID.

        Examples:
            >>> device_type = DeviceType.from_id("dt_abc123", org_id="og_abc123")
            >>> print(device_type.name)
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
        """Time the device type was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the device type, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the device type, or ``None`` if it has none."""
        return self.__record.description

    @property
    def device_count(self) -> int:
        """Number of devices of this device type, counted when Roboto returned this record.

        The count does not change as devices later gain or lose this type; ``from_id`` fetches a current count.
        """
        return self.__record.device_count

    @property
    def device_type_id(self) -> str:
        """Unique ID of the device type, beginning with ``dt_``."""
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
        """Key-value metadata on the device type."""
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        """Time the device type was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the device type, in the same ``<type>:<id>`` form as ``created_by``."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Human-readable name of the device type, unique within its organization."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the device type."""
        return self.__record.org_id

    @property
    def record(self) -> DeviceTypeRecord:
        """Record of the device type that this instance holds."""
        return self.__record

    @property
    def tags(self) -> list[str]:
        """Tags on the device type."""
        return self.__record.tags

    def delete(self) -> None:
        """Delete this device type.

        Roboto refuses while any device is of this type; give those devices another type, or none, first. Shortly
        after this call returns, Roboto deletes every version of every file in the device type's configurations
        (``configurations``). Downloading a link elsewhere that points at one of those files then raises
        ``RobotoNotFoundException``. Deleting a device type that no longer exists succeeds and changes nothing.

        Raises:
            RobotoConflictException: At least one device is of this type.

        Examples:
            >>> device_type = DeviceType.from_id("dt_abc123")
            >>> device_type.delete()
        """
        self.__roboto_client.delete(
            f"v1/device-types/id/{self.device_type_id}",
            owner_org_id=self.org_id,
        )

    def devices(self) -> collections.abc.Generator[Device, None, None]:
        """List the devices of this device type, newest first.

        Yields:
            Each :py:class:`~roboto.domain.devices.Device` of this type, fetched a page at a time as the generator
            advances.

        Raises:
            RobotoUnauthorizedException: The caller cannot manage devices in the device type's organization. It
                surfaces on the first iteration.

        Examples:
            >>> device_type = DeviceType.from_id("dt_abc123")
            >>> for device in device_type.devices():
            ...     print(device.device_id)
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
            request: Changes to make, as ``UpdateDeviceTypeRequest`` describes.

        Returns:
            A new ``DeviceType`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoConflictException: Another device type in the organization already has the new name.

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
