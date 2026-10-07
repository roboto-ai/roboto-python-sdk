# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

from ...association import Association
from ...auth.scope import ApiScope
from ...exceptions import (
    RobotoConflictException,
    RobotoDomainException,
    RobotoNotReadyException,
)
from ...experimental.sessions import (
    Session,
    SessionDeclaration,
    SessionFile,
    SessionRecord,
)
from ...experimental.sessions.operations import CreateSessionsRequest
from ...http import (
    BatchResponse,
    RobotoClient,
)
from ...time import Time, to_epoch_nanoseconds
from ...updates import CustomFieldChangeset, MetadataChangeset
from ...warnings import experimental
from ..files import FileSystem
from ..tokens import (
    CreateTokenRequest,
    Token,
    TokenRecord,
)
from .operations import (
    CreateDeviceRequest,
    UpdateDeviceRequest,
)
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
        methods :py:meth:`create`, :py:meth:`from_id`, :py:meth:`get_or_create`, or :py:meth:`for_org`
        to obtain Device instances.
    """

    __record: DeviceRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        device_id: str,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
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
            metadata: Optional key-value pairs to associate with the device for discovery and search.
                For example: {"model": "mk2", "serial_number": "SN001234"}.
            tags: Optional list of tags to associate with the device for discovery and organization.
                For example: ["production", "warehouse-a"].
            custom_fields: Optional initial values for Ready custom fields defined on
                Devices in the caller's org. Keys must match Ready field names; values
                must satisfy each field's declared type.
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

            >>> device = Device.create(device_id="robot_001", caller_org_id="og_abc123")
            >>> print(f"Registered device: {device.device_id}")
            Registered device: robot_001

            Register an upload station:

            >>> device = Device.create(device_id="upload_station_alpha")
            >>> print(f"Device org: {device.org_id}")
            Device org: og_xyz789
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDeviceRequest(
            device_id=device_id,
            org_id=caller_org_id,
            metadata=metadata or {},
            tags=tags or [],
            custom_fields=custom_fields,
        )
        record = roboto_client.post("v1/devices/create", caller_org_id=caller_org_id, data=request).to_record(
            DeviceRecord
        )
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
        encoded_device_id = urllib.parse.quote(device_id, safe="")
        record = roboto_client.get(
            f"v1/devices/id/{encoded_device_id}",
            owner_org_id=org_id,
        ).to_record(DeviceRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    @experimental
    def get_or_create(
        cls,
        device_id: str,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Device":
        """Register a device, or return the existing one if ``device_id`` is already taken.

        ``metadata``, ``tags``, and ``custom_fields`` are applied only by the call that registers the
        device; a device that is already registered comes back unchanged.

        Args:
            device_id: A user-provided identifier for the device, unique within the organization.
            metadata: Optional key-value pairs to associate with the device on first registration.
            tags: Optional tags to associate with the device on first registration.
            custom_fields: Optional initial values for Ready custom fields, applied on first registration.
            caller_org_id: The organization the device belongs to. Required if the caller
                belongs to multiple organizations.
            roboto_client: Optional RobotoClient instance for API communication.

        Returns:
            The newly registered or pre-existing Device.

        Raises:
            RobotoUnauthorizedException: If the caller lacks permission to create devices in,
                or read devices from, the specified organization.
            RobotoInvalidRequestException: If the device_id is invalid or the organization
                ID is malformed.
            RobotoNotFoundException: If the device is deleted between the registration attempt
                and the lookup that follows it. Those are two calls rather than one atomic
                operation, so the race is possible, though unlikely.

        Examples:
            >>> device = Device.get_or_create(device_id="aloha_001")
            >>> device.device_id
            'aloha_001'
        """
        try:
            return cls.create(
                device_id=device_id,
                metadata=metadata,
                tags=tags,
                custom_fields=custom_fields,
                caller_org_id=caller_org_id,
                roboto_client=roboto_client,
            )
        except RobotoConflictException:
            return cls.from_id(device_id, roboto_client=roboto_client, org_id=caller_org_id)

    def __init__(self, record: DeviceRecord, roboto_client: typing.Optional[RobotoClient] = None):
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
    def encoded_device_id(self) -> str:
        """
        The device ID, URL-encoded. This is useful for constructing URLs to Roboto APIs which contain the device ID.
        """
        return urllib.parse.quote(self.device_id, safe="")

    @property
    def files(self) -> FileSystem:
        """The files associated with this device: its calibrations, part manifests, and the like.

        These are the device's own files, distinct from the dataset files whose ``device_id`` names this
        device as the one that recorded them.

        Raises:
            RobotoNotReadyException: The device has no ``universal_device_id``, which only a Roboto
                deployment that predates device files returns.
        """
        if self.__record.universal_device_id is None:
            raise RobotoNotReadyException(
                f"Device '{self.device_id}' has no universal_device_id, so its files cannot be addressed; "
                "the Roboto deployment it was loaded from predates device files."
            )
        return FileSystem(
            Association.device(self.__record.universal_device_id),
            roboto_client=self.__roboto_client,
            org_id=self.org_id,
        )

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata pairs associated with this device."""
        return self.__record.metadata

    @property
    @experimental
    def custom_fields(self) -> dict[str, typing.Any]:
        """Custom-field values defined on Devices in this org.

        Every ``Ready`` :py:class:`~roboto.domain.custom_fields.CustomField` defined
        for ``(org_id, Device)`` appears as a key. Values that have not been set
        on this device surface as ``None`` rather than being absent. Empty when
        no custom fields are defined for the org.

        A :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is returned
        as an ISO 8601 string.
        """
        return self.__record.custom_fields

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
        """Underlying :py:class:`DeviceRecord` for this device.

        This is the wire representation used in API requests and may evolve over time; prefer the public
        :py:class:`Device` API unless you need direct access to the record.
        """
        return self.__record

    @property
    def tags(self) -> list[str]:
        """List of tags associated with this device."""
        return self.__record.tags

    @experimental
    def create_session(
        self,
        name: str,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[collections.abc.Sequence[str]] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        anchor: typing.Optional[Time] = None,
        files: typing.Optional[collections.abc.Sequence[SessionFile]] = None,
    ) -> Session:
        """Create one Session on this Device, optionally with its files, topics, and schemas.

        The one-session form of :py:meth:`create_sessions`, taking a single declaration's fields as arguments
        and sharing its semantics: the Session, its file attachments, its topics, and its time ranges are
        created together or not at all, and every file the declaration names must already be uploaded.
        ``name`` identifies the Session within this Device, so resending the same call is safe;
        the platform reuses the Session already registered under that name instead of creating a second one.
        Arguments left at their defaults are left out of the request,
        so a call that reuses an existing Session never overwrites attributes it does not name.
        To create a Session with no name, or one spanning several Devices,
        use :py:meth:`~roboto.experimental.sessions.Session.create`.

        A declaration the platform refuses raises here. Only :py:meth:`create_sessions` reports a refusal
        instead of raising it, because only a batch has positions to trace refusals back to.

        Declared times are stored exactly as given, in each file's own timestamps, and read as nanoseconds
        since the Unix epoch; the platform never invents a wall-clock time. To place the Session at the
        wall-clock time it happened, supply ``anchor``, or call
        :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset` later.

        Args:
            name: Name of the Session, unique within this Device (max 120 characters).
            description: Optional description of the Session.
            metadata: Optional initial metadata.
                Sessions are not filterable or sortable by ``metadata`` keys;
                for queryable structured attributes, define a custom field on the ``Session`` entity type.
            tags: Optional initial tags.
                Sessions can be filtered by tag membership but are not sortable by tag.
            custom_fields: Optional initial values for Ready custom fields defined on
                Sessions in this Device's org. Keys must match Ready field names; values
                must satisfy each field's declared type.
            anchor: Optional wall-clock anchor, the real-world instant at which the declared data's time 0
                occurred. An ``int`` is nanoseconds since the Unix epoch; any other
                :py:data:`~roboto.time.Time` is read as :py:func:`~roboto.time.to_epoch_nanoseconds` reads it
                (a ``datetime`` or ISO 8601 string is that instant; a ``float``, ``Decimal``, or numeric string
                is seconds since the epoch). It applies to every file entry that does not carry its own
                :py:attr:`~roboto.experimental.sessions.FileDeclaration.anchor_ns`.
            files: Files composing this Session, with the topics whose data each one carries. Every file
                must already be uploaded, and may appear at most once. Files can also be included after
                creation with :py:meth:`~roboto.experimental.sessions.Session.add_file` or
                :py:meth:`~roboto.experimental.sessions.Session.add_files`.

        Returns:
            The created Session.

        Raises:
            TypeError: If ``anchor`` is not one of the :py:data:`~roboto.time.Time` types.
            ValueError: If ``anchor`` is a boolean, a negative number (an ``int``, ``float``, ``Decimal``, or
                numeric string), or a string that is neither a number of seconds nor an ISO 8601 timestamp. Raised
                before anything is sent to the platform.
            OverflowError: If ``anchor`` is an infinite ``float``, ``Decimal``, or string, such as ``"inf"``.
                Raised before anything is sent to the platform.
            pydantic.ValidationError: If ``name`` is empty or longer than 120 characters, ``anchor`` does
                not fall after the Unix epoch or is too large for a signed 64-bit integer of nanoseconds, a
                file appears in more than one entry, ``files`` declares more than
                :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST` files and topics
                combined, or representations name one file in two storage formats. Raised while the request is
                being built, before anything is sent to the platform.
            RobotoInvalidRequestException: If the platform refuses the declaration, either because it
                contradicts data the platform already holds or because it carries a value the platform
                rejects, such as a ``custom_fields`` value that does not satisfy its field's declared
                type. No Session, file attachment, topic, or time range is created; the topic identifiers
                and schema definitions the declaration resolved stay stored, and a resend reuses them.
            RobotoConflictException: If something the declaration was prepared against changed while it
                was being written. Nothing is created; resending is the fix.
            RobotoNotFoundException: If this Device is no longer registered, the ``file_id`` of a file entry,
                or of a representation one of its topics lists, does not name a file in this Device's
                organization whose status is :py:attr:`~roboto.domain.files.FileStatus.Available`,
                or the declaration names something else that does not exist, such as a ``custom_fields`` key
                naming a custom field the organization does not define on Sessions. Nothing is created.
            RobotoUnauthorizedException: If the caller lacks permission to create Sessions on this Device, or
                to edit a file the declaration declares topics on, a file it anchors, or a file a listed
                representation names, or lacks topic edit access in this Device's organization while the
                declaration states ``is_default_for_reads`` on a timeline source.
            RobotoUnrecognizedErrorException: If the platform refuses the declaration under an error code
                this SDK release does not define. Carries the code and message the platform sent.

        Examples:
            Create a Session and add a file to it:

            >>> device = Device.from_id("robot_001", org_id="og_abc123")
            >>> session = device.create_session(name="2024-05-01_morning_run")
            >>> session.add_file("fl_0123456789abcdef")

            Create a Session placed at the wall-clock time it was recorded:

            >>> import datetime
            >>> session = device.create_session(
            ...     name="2024-05-01_morning_run",
            ...     anchor=datetime.datetime(2024, 5, 1, 9, 30, tzinfo=datetime.timezone.utc),
            ... )
        """
        # Building the declaration out of only the supplied arguments is what keeps the rest off the wire:
        # the request body serializes with ``exclude_unset``.
        optional_fields: dict[str, typing.Any] = {
            "description": description,
            "metadata": metadata,
            "tags": None if tags is None else list(tags),
            "custom_fields": custom_fields,
            "anchor_ns": None if anchor is None else to_epoch_nanoseconds(anchor),
            "files": None if files is None else list(files),
        }
        declaration = SessionDeclaration(
            name=name,
            **{field: value for field, value in optional_fields.items() if value is not None},
        )

        return self.create_sessions([declaration]).single()

    @experimental
    def create_sessions(
        self,
        sessions: collections.abc.Sequence[SessionDeclaration],
    ) -> BatchResponse[Session]:
        """Create many Sessions on this Device, each with its files, topics, and schemas, in one call.

        Each call accepts up to :py:data:`~roboto.experimental.sessions.MAX_SESSIONS_PER_REQUEST`
        declarations, one per Session (e.g. the episodes of a LeRobot dataset), and up to
        :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST` files and topics combined,
        counted across every declaration; split anything larger across several calls.
        Every file a declaration names must already be uploaded;
        :py:meth:`~roboto.domain.datasets.Dataset.upload_files` returns the file IDs it creates,
        and files from any number of datasets may appear in one batch.

        The platform decides which declarations to refuse before writing anything, then writes the rest
        together. A declaration's Session, file attachments, topics, and time ranges are created together or
        not at all, and a declaration the platform refuses leaves the others written as if it were absent. None
        of the declarations is written when a failure the platform did not anticipate, such as a timeout,
        interrupts the call, or when a Session a declaration reuses is deleted before the call completes, which
        raises :py:class:`~roboto.exceptions.RobotoNotFoundException`. Each declaration is written as it would be
        had the ones before it been sent as calls of their own: a later declaration anchoring data an earlier one
        holds moves the earlier Session's time range with it. A refused declaration, or a call that fails,
        still leaves behind the topic identifiers and schema definitions it resolved, which a resend reuses.

        Check :py:attr:`~roboto.http.BatchResponse.failed` before treating the batch as done. Each entry
        there is the :py:class:`~roboto.exceptions.RobotoDomainException` the platform refused a declaration
        with, so ``isinstance`` tells the reasons apart; a refusal under an error code this SDK release does
        not define arrives as :py:class:`~roboto.exceptions.RobotoUnrecognizedErrorException`.

        Resending the same call is safe. This Device plus each declaration's ``name`` identifies the Session
        the declaration creates or reuses, so a resend fills in only what is missing rather than duplicating
        what an earlier attempt created.

        Declared times are stored exactly as given, in each file's own timestamps, and read as nanoseconds
        since the Unix epoch; the platform never invents a wall-clock time. A recording whose timestamps
        start at 0 therefore sits at the epoch until it is anchored. To place a Session at the wall-clock
        time it happened, supply :py:attr:`~roboto.experimental.sessions.SessionDeclaration.anchor_ns`, or
        call :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset` later.

        Args:
            sessions: One declaration per Session to create. An empty sequence returns an empty response
                without contacting the platform.

        Returns:
            A :py:class:`~roboto.http.BatchResponse` with one element per declaration, in request order,
            holding either the Session the declaration created or why the platform refused it. A declaration
            naming a Session this Device already holds yields that Session rather than a second one.

        Raises:
            pydantic.ValidationError: If more than
                :py:data:`~roboto.experimental.sessions.MAX_SESSIONS_PER_REQUEST` declarations are given, the
                batch declares more than
                :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST` files and topics
                combined, the same session name is declared more than once, or representations name one file
                in two storage formats. All are enforced when the request body is constructed, before
                anything is sent to the platform.
            RobotoInvalidRequestException: If the batch is malformed. Nothing is created.
            RobotoNotFoundException: If this Device is no longer registered, the ``file_id`` of a file entry,
                or of a representation one of its topics lists, does not name a file in this Device's
                organization whose status is :py:attr:`~roboto.domain.files.FileStatus.Available`,
                or a Session a declaration reuses is deleted before the call completes. Nothing is created.
            RobotoUnauthorizedException: If the caller lacks permission to create Sessions on this Device, or
                to edit a file a declaration declares topics on, a file it anchors, or a file a listed
                representation names, or lacks topic edit access in this Device's organization while a
                declaration states ``is_default_for_reads`` on a timeline source.

        Examples:
            Register two chunks of one recording as a single Session, each chunk's topic data read from the
            chunk itself:

            >>> import pathlib
            >>> from roboto.domain.datasets import Dataset
            >>> from roboto.domain.devices import Device
            >>> from roboto.domain.topics import CanonicalDataType, RepresentationStorageFormat
            >>> from roboto.experimental.ingest import (
            ...     Field,
            ...     McapLogTimeSource,
            ...     RepresentationDeclaration,
            ...     Schema,
            ...     TopicDeclaration,
            ... )
            >>> from roboto.experimental.sessions import SessionDeclaration, SessionFile
            >>> imu_schema = Schema(
            ...     name="sensor_msgs/msg/Imu",
            ...     fields=[
            ...         Field(
            ...             name="angular_velocity_x",
            ...             data_type="float64",
            ...             canonical_data_type=CanonicalDataType.Number,
            ...         ),
            ...     ],
            ... )
            >>> dataset = Dataset.from_id("ds_0123456789ab")
            >>> device = Device.from_id("robot_001")
            >>> chunks = [pathlib.Path("recording/chunk_0000.mcap"), pathlib.Path("recording/chunk_0001.mcap")]
            >>> file_ids = dataset.upload_files(chunks)
            >>> batch = device.create_sessions(
            ...     [
            ...         SessionDeclaration(
            ...             name="morning_drive",
            ...             files=[
            ...                 SessionFile(
            ...                     file_id=file_ids[chunks[0]],
            ...                     topics=[
            ...                         TopicDeclaration(
            ...                             topic_name="/imu",
            ...                             topic_schema=imu_schema,
            ...                             timeline_sources=[
            ...                                 McapLogTimeSource(
            ...                                     min_file_timestamp_ns=1_785_974_400_000_000_000,
            ...                                     max_file_timestamp_ns=1_785_974_404_000_000_000,
            ...                                 ),
            ...                             ],
            ...                             representations=[
            ...                                 RepresentationDeclaration(
            ...                                     file_id=file_ids[chunks[0]],
            ...                                     storage_format=RepresentationStorageFormat.MCAP,
            ...                                 ),
            ...                             ],
            ...                         ),
            ...                     ],
            ...                 ),
            ...                 SessionFile(
            ...                     file_id=file_ids[chunks[1]],
            ...                     topics=[
            ...                         TopicDeclaration(
            ...                             topic_name="/imu",
            ...                             topic_schema=imu_schema,
            ...                             timeline_sources=[
            ...                                 McapLogTimeSource(
            ...                                     min_file_timestamp_ns=1_785_974_404_000_000_000,
            ...                                     max_file_timestamp_ns=1_785_974_408_000_000_000,
            ...                                 ),
            ...                             ],
            ...                             representations=[
            ...                                 RepresentationDeclaration(
            ...                                     file_id=file_ids[chunks[1]],
            ...                                     storage_format=RepresentationStorageFormat.MCAP,
            ...                                 ),
            ...                             ],
            ...                         ),
            ...                     ],
            ...                 ),
            ...             ],
            ...         ),
            ...     ],
            ... )
            >>> batch.failed
            []
        """
        if not sessions:
            return BatchResponse[Session](responses=[])

        record_batch = self.__roboto_client.post(
            f"v1/devices/id/{self.encoded_device_id}/sessions",
            data=CreateSessionsRequest(sessions=list(sessions)),
            owner_org_id=self.org_id,
        ).to_record(BatchResponse[SessionRecord])
        return record_batch.map_data(lambda record: Session(record, roboto_client=self.__roboto_client))

    def create_token(
        self,
        expiry_days: int = 366,
        name: typing.Optional[str] = None,
        description: typing.Optional[str] = None,
        api_scopes: typing.Optional[collections.abc.Collection[ApiScope]] = None,
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
            api_scopes: Optional set of API scopes to limit the token's permissions. If not provided,
                the token will have full access to all APIs.

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
            ...     expiry_days=30, name="Monthly Upload Token", description="Token for automated monthly data uploads"
            ... )
            >>> print(f"Token expires in 30 days: {token.token_id}")
            Token expires in 30 days: to_def789ghi012
        """
        request = CreateTokenRequest(
            expiry_days=expiry_days,
            name=name or f"{self.org_id}_{self.device_id}",
            description=description,
            api_scopes=None if api_scopes is None else set(api_scopes),
        )

        record = self.__roboto_client.post(
            f"v1/devices/id/{self.encoded_device_id}/tokens",
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

    def delete(self, keep_files: bool = False) -> None:
        """Delete this device from the Roboto platform.

        Permanently removes this device and all associated tokens. This action cannot
        be undone. Any tokens created for this device will be immediately invalidated.

        The device's own files (:py:attr:`files`) are deleted with it, every version of each, shortly after this
        call returns. With ``keep_files=True`` they move to the org root instead, under
        ``devices/<universal_device_id>/``, keeping their file IDs and every version, so they stay reachable through
        ``org.files``. Links among the device's files are deleted in both cases, never moved; their targets are left
        alone.

        Args:
            keep_files: Move the device's files to the org root instead of deleting them. Requires permission to
                upload files to the org.

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

            Delete a device but keep its calibrations and manifests in the org root:

            >>> device = Device.from_id("old_robot_001")
            >>> device.delete(keep_files=True)
        """
        self.__roboto_client.delete(
            f"v1/devices/id/{self.encoded_device_id}",
            owner_org_id=self.org_id,
            query={"keep_files": "true"} if keep_files else None,
        )

    @experimental
    def list_sessions(self) -> collections.abc.Generator[Session, None, None]:
        """Iterate all Sessions attached to this Device.

        Yields results as they are returned from the server, paginating transparently.

        Examples:
            Print the name of every Session for a Device:

            >>> device = Device.from_id("robot_001", org_id="og_abc123")
            >>> for session in device.list_sessions():
            ...     print(session.name)
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/devices/id/{self.encoded_device_id}/sessions",
                owner_org_id=self.org_id,
                query=query,
            ).to_paginated_list(SessionRecord)

            for record in page.items:
                yield Session(record=record, roboto_client=self.__roboto_client)

            next_token = page.next_token
            if not next_token:
                break

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "Device":
        """Add or update metadata fields for this device.

        Args:
            metadata: Key-value pairs to add or update in the device's metadata.
                Existing keys will be overwritten, new keys will be added.

        Returns:
            Updated Device instance with the new metadata.

        Example:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.put_metadata({"firmware_version": "2.1.0", "location": "warehouse-b"})
            >>> print(updated_device.metadata["firmware_version"])
            2.1.0
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(put_fields=metadata)))

    def put_tags(self, tags: list[str]) -> "Device":
        """Add tags to this device.

        Args:
            tags: List of tags to add to the device. Duplicate tags will be ignored.

        Returns:
            Updated Device instance with the new tags added.

        Example:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.put_tags(["production", "warehouse-c"])
            >>> print("production" in updated_device.tags)
            True
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(put_tags=tags)))

    def remove_metadata(self, keys: list[str]) -> "Device":
        """Remove metadata fields from this device.

        Args:
            keys: List of metadata keys to remove from the device.

        Returns:
            Updated Device instance with the specified metadata keys removed.

        Example:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.remove_metadata(["old_field", "deprecated_key"])
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(remove_fields=keys)))

    def remove_tags(self, tags: list[str]) -> "Device":
        """Remove tags from this device.

        Args:
            tags: List of tags to remove from the device.

        Returns:
            Updated Device instance with the specified tags removed.

        Example:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.remove_tags(["old_tag", "deprecated"])
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(remove_tags=tags)))

    @experimental
    def set_custom_field(self, name: str, value: typing.Any) -> "Device":
        """Set a single custom-field value on this device.

        ``name`` must be the name of a
        :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` custom
        field for this device's org and the
        :py:class:`~roboto.domain.custom_fields.TargetEntityType.Device`
        entity type; ``value`` must satisfy the field's declared type.
        """
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value})))

    @experimental
    def clear_custom_field(self, name: str) -> "Device":
        """Clear a single custom-field value on this device to ``None``."""
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name])))

    @experimental
    def set_custom_fields(self, fields: dict[str, typing.Any]) -> "Device":
        """Set or overwrite multiple custom-field values on this device.

        Each key must name a Ready custom field for this device's org and the
        :py:class:`~roboto.domain.custom_fields.TargetEntityType.Device`
        entity type; each value must satisfy the field's declared type.
        """
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(set_fields=fields)))

    @experimental
    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> "Device":
        """Clear multiple custom-field values on this device to ``None``."""
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names))))

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
            f"v1/devices/id/{self.encoded_device_id}/tokens", owner_org_id=self.org_id
        ).to_record_list(TokenRecord)
        return [Token(record=record, roboto_client=self.__roboto_client) for record in records]

    def update(self, request: UpdateDeviceRequest) -> "Device":
        """Update device properties using a structured request.

        Args:
            request: UpdateDeviceRequest containing the changes to apply.

        Returns:
            Updated Device instance with the changes applied.

        Example:
            >>> from roboto.updates import MetadataChangeset
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.update(
            ...     UpdateDeviceRequest(
            ...         metadata_changeset=MetadataChangeset(
            ...             put_fields={"version": "2.0"}, put_tags=["updated"], remove_tags=["old"]
            ...         )
            ...     )
            ... )
        """
        record = self.__roboto_client.put(
            f"v1/devices/id/{self.encoded_device_id}",
            owner_org_id=self.org_id,
            data=request,
        ).to_record(DeviceRecord)
        return Device(record=record, roboto_client=self.__roboto_client)
