# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

import pydantic

from ...association import Association
from ...auth.scope import ApiScope
from ...exceptions import (
    RobotoConflictException,
    RobotoDomainException,
    RobotoNotFoundException,
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
    """A device: a robot, upload station, or other non-human entity that interacts with Roboto programmatically.

    A device belongs to one organization, which gives it an ID, such as a serial number or asset tag, unique within
    that organization. Access tokens from ``create_token`` let the device make requests as itself, such as creating
    datasets and uploading files, which then record its ID. A device also has files of its own, its
    ``configurations``, and carries tags, key-value metadata, and custom-field values.

    Get a ``Device`` from ``create``, ``from_id``, or ``for_org``. To wrap a
    :py:class:`~roboto.domain.devices.DeviceRecord` already fetched from Roboto, build a ``Device`` from it directly.
    Methods that change the device return a new ``Device`` holding the updated record, and leave the record of the
    instance they were called on as it was.

    Args:
        record: Record of the device.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
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
        device_type_id: typing.Optional[str] = None,
    ) -> "Device":
        """Create a device.

        Args:
            device_id: ID to give the device, such as a serial number, unique within the organization.
                :py:func:`~roboto.domain.devices.validate_device_id` lists the IDs Roboto refuses.
            metadata: Key-value metadata to set on the device. ``None`` sets none.
            tags: Tags to set on the device. ``None`` sets none.
            custom_fields: Initial values for the device's custom fields, keyed by field name. Each name must be a
                custom field defined for devices in the organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type. ``None`` sets none.
            caller_org_id: Organization to create the device in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            device_type_id: ID of a device type in the same organization to assign to the device, beginning with
                ``dt_``. ``None`` leaves the device without one.

        Returns:
            The new device.

        Raises:
            RobotoConflictException: The organization already has a device with this ``device_id``.
            RobotoInvalidRequestException: ``device_type_id`` is given and the organization has no such device type.
            RobotoIllegalArgumentException: A ``custom_fields`` name is not a ready custom field for devices, or its
                value does not match the field's type.
            pydantic.ValidationError: :py:func:`~roboto.domain.devices.validate_device_id` refuses ``device_id``.
                Raised before anything is sent to Roboto.

        Examples:
            Create a device in a named organization:

            >>> device = Device.create(device_id="robot_001", caller_org_id="og_12345")
            >>> device.device_id
            'robot_001'

            Create a device with tags and metadata:

            >>> device = Device.create(
            ...     device_id="upload_station_alpha",
            ...     tags=["production", "warehouse-a"],
            ...     metadata={"model": "mk2", "serial_number": "SN001234"},
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDeviceRequest(
            device_id=device_id,
            org_id=caller_org_id,
            metadata=metadata or {},
            tags=tags or [],
            custom_fields=custom_fields,
            device_type_id=device_type_id,
        )
        record = roboto_client.post("v1/devices/create", caller_org_id=caller_org_id, data=request).to_record(
            DeviceRecord
        )
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls, org_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Generator["Device", None, None]:
        """List the devices of an organization.

        Fetches the devices a page at a time, as the generator is iterated.

        Args:
            org_id: ID of the organization whose devices to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            Print the ID of every device in an organization:

            >>> for device in Device.for_org("og_12345"):
            ...     print(device.device_id)

            Count the devices in an organization:

            >>> device_count = sum(1 for _ in Device.for_org("og_12345"))
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
        """Fetch a device by its ID.

        Args:
            device_id: ID the organization gave the device when creating it.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            org_id: Organization that owns the device. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.

        Raises:
            RobotoNotFoundException: The organization has no device with this ID.

        Examples:
            >>> device = Device.from_id("robot_001", org_id="og_12345")
            >>> device.org_id
            'og_12345'
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
        """Create a device, or fetch the existing one when the organization already has a device with this ID.

        ``metadata``, ``tags``, and ``custom_fields`` apply only to a device this call creates; an existing device
        comes back unchanged.

        Args:
            device_id: ID of the device, such as a serial number, unique within the organization.
            metadata: Key-value metadata to set on a device this call creates. ``None`` sets none.
            tags: Tags to set on a device this call creates. ``None`` sets none.
            custom_fields: Initial values for the custom fields of a device this call creates, keyed by field name.
                ``None`` sets none.
            caller_org_id: Organization to create the device in, or to fetch it from. Required when the caller
                belongs to more than one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new or existing device.

        Raises:
            RobotoIllegalArgumentException: The device is new, and a ``custom_fields`` name is not a ready custom field
                for devices or its value does not match the field's type.
            pydantic.ValidationError: :py:func:`~roboto.domain.devices.validate_device_id` refuses ``device_id``, and
                the organization has no device with that ID.
            RobotoNotFoundException: The device is deleted between the attempt to create it and the request that
                fetches it. These are two requests, not one, so another caller can delete the device in between.

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
        except pydantic.ValidationError as refusal:
            # An existing device can have an ID that create refuses, so look the ID up before reporting the refusal.
            try:
                return cls.from_id(device_id, roboto_client=roboto_client, org_id=caller_org_id)
            except RobotoNotFoundException:
                raise refusal from None

    def __init__(self, record: DeviceRecord, roboto_client: typing.Optional[RobotoClient] = None):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """Time the device was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the device, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def device_id(self) -> str:
        """ID the organization gave the device, such as a serial number, unique within the organization."""
        return self.__record.device_id

    @property
    def device_type_id(self) -> typing.Optional[str]:
        """ID of the device type assigned to the device, beginning with ``dt_``, or ``None`` if it has none."""
        return self.__record.device_type_id

    @property
    def encoded_device_id(self) -> str:
        """Device ID, percent-encoded so that it fits in one segment of a URL path, ``/`` included."""
        return urllib.parse.quote(self.device_id, safe="")

    @property
    def configurations(self) -> FileSystem:
        """Files of the device itself, such as URDFs, calibration files, manifests, and maintenance logs.

        Data the device records goes to datasets instead: a dataset file whose ``device_id`` names this device is not
        one of its configurations.

        A device with a device type also inherits the type's configurations. Pass ``include_inherited=True`` to
        :py:meth:`~roboto.domain.files.FileSystem.list_files` or
        :py:meth:`~roboto.domain.files.FileSystem.download_files` to include them; the other methods act on the
        device's own files only.

        Reading it raises ``RobotoNotReadyException`` when the device's record has no ``universal_device_id``.
        """
        if self.__record.universal_device_id is None:
            raise RobotoNotReadyException(
                f"Device '{self.device_id}' has no universal_device_id, so its configurations cannot be addressed."
            )
        return FileSystem(
            Association.device(self.__record.universal_device_id),
            roboto_client=self.__roboto_client,
            org_id=self.org_id,
        )

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata on the device."""
        return self.__record.metadata

    @property
    @experimental
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields the organization defines for devices, keyed by field name.

        Which fields appear as keys is as :py:attr:`~roboto.domain.devices.DeviceRecord.custom_fields` describes. A
        :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is an ISO 8601 string.
        """
        return self.__record.custom_fields

    @property
    def modified(self) -> datetime.datetime:
        """Time the device was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the device, in the same ``<type>:<id>`` form as ``created_by``."""
        return self.__record.modified_by

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the device."""
        return self.__record.org_id

    @property
    def record(self) -> DeviceRecord:
        """Record of the device that this instance holds."""
        return self.__record

    @property
    def tags(self) -> list[str]:
        """Tags on the device."""
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
        """Create one session on this device, optionally with its files, topics, and schemas.

        The one-session form of ``create_sessions``, taking a single declaration's fields as arguments and sharing its
        semantics: the session, its file attachments, its topics, and its time ranges are created together or not at
        all, and every file the declaration names must already be uploaded. ``name`` identifies the session within
        this device, so resending the same call is safe: Roboto reuses the session already registered under that name
        instead of creating a second one. Arguments left at their defaults are left out of the request, so a call that
        reuses an existing session never overwrites attributes it does not name. To create a session with no name, or
        one spanning several devices, use :py:meth:`~roboto.experimental.sessions.Session.create`.

        A declaration Roboto refuses raises its exception here, where ``create_sessions`` reports it in its response
        instead.

        Declared times are stored exactly as given, in each file's own timestamps, and read as nanoseconds since the
        Unix epoch; Roboto never invents a wall-clock time. To place the session at the wall-clock time it happened,
        supply ``anchor``, or call :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset` later.

        Args:
            name: Name of the session, unique within this device, at most 120 characters.
            description: Human-readable description of the session.
            metadata: Key-value metadata to set on the session. Sessions cannot be filtered or sorted by metadata
                keys; for attributes to query by, define a custom field for sessions.
            tags: Tags to set on the session. Sessions can be filtered by tag but not sorted by tag.
            custom_fields: Initial values for the session's custom fields, keyed by field name. Each name must be a
                custom field defined for sessions in this device's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type.
            anchor: Wall-clock time at which the declared data's time 0 occurred. An ``int`` is nanoseconds since the
                Unix epoch; any other :py:const:`~roboto.time.Time` is read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime.datetime`` or ISO 8601 string is
                that instant; a ``float``, ``decimal.Decimal``, or numeric string is seconds since the epoch). It
                applies to every file entry that does not carry its own
                :py:attr:`~roboto.experimental.sessions.FileDeclaration.anchor_ns`.
            files: Files in the session, with the topics whose data each one carries. Each file must already be
                uploaded, and may appear at most once. :py:meth:`~roboto.experimental.sessions.Session.add_file` and
                :py:meth:`~roboto.experimental.sessions.Session.add_files` add files after creation.

        Returns:
            The new session, or the existing session this device holds under ``name``.

        Raises:
            TypeError: ``anchor`` is not one of the :py:const:`~roboto.time.Time` types.
            ValueError: ``anchor`` is a boolean, a negative number (an ``int``, ``float``, ``decimal.Decimal``, or
                numeric string), or a string that is neither a number of seconds nor an ISO 8601 timestamp. Raised
                before anything is sent to Roboto.
            OverflowError: ``anchor`` is an infinite ``float``, ``decimal.Decimal``, or string, such as ``"inf"``.
                Raised before anything is sent to Roboto.
            pydantic.ValidationError: ``name`` is empty or longer than 120 characters, ``anchor`` does not fall after
                the Unix epoch or is too large for a signed 64-bit integer of nanoseconds, a file appears in more than
                one entry, ``files`` declares more than 500 files and topics combined
                (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`), or representations name
                one file in two storage formats. Raised while the request is being built, before anything is sent to
                Roboto.
            RobotoInvalidRequestException: Roboto refuses the declaration, either because it contradicts data Roboto
                already holds or because it carries a value Roboto rejects, such as a ``custom_fields`` value that
                does not satisfy its field's declared type. No session, file attachment, topic, or time range is
                created; the topic identifiers and schema definitions the declaration resolved stay stored, and a
                resend reuses them.
            RobotoConflictException: Something the declaration was prepared against changed while it was being
                written. Nothing is created; resending is the fix.
            RobotoNotFoundException: This device is no longer registered; the ``file_id`` of a file entry, or of a
                representation one of its topics lists, does not name a file in this device's organization whose
                status is :py:attr:`~roboto.domain.files.FileStatus.Available`; or the declaration names something
                else that does not exist, such as a ``custom_fields`` key naming a custom field the organization does
                not define for sessions. Nothing is created.
            RobotoUnauthorizedException: The caller cannot create sessions on this device, or cannot edit a file the
                declaration declares topics on, a file it anchors, or a file a listed representation names, or lacks
                topic edit access in this device's organization while the declaration states
                ``is_default_for_reads`` on a timeline source.
            RobotoUnrecognizedErrorException: Roboto refuses the declaration under an error code this SDK release
                does not define. Carries the code and message Roboto sent.

        Examples:
            Create a session and add a file to it:

            >>> device = Device.from_id("robot_001", org_id="og_12345")
            >>> session = device.create_session(name="2024-05-01_morning_run")
            >>> session.add_file("fl_12345")

            Create a session placed at the wall-clock time it was recorded:

            >>> import datetime
            >>> session = device.create_session(
            ...     name="2024-05-01_morning_run",
            ...     anchor=datetime.datetime(2024, 5, 1, 9, 30, tzinfo=datetime.timezone.utc),
            ... )
        """
        # Pass SessionDeclaration only the arguments the caller supplied: the request body is serialized with
        # exclude_unset, so the rest stay out of the request.
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
        """Create many sessions on this device, each with its files, topics, and schemas, in one request.

        Each call accepts up to 100 declarations (:py:const:`~roboto.experimental.sessions.MAX_SESSIONS_PER_REQUEST`),
        one per session (such as the episodes of a LeRobot dataset), and up to 500 files and topics combined
        (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`), counted across every declaration;
        split anything larger across several calls. Every file a declaration names must
        already be uploaded; :py:meth:`~roboto.domain.datasets.Dataset.upload_files` returns the file IDs it creates,
        and files from any number of datasets may appear in one batch.

        Roboto decides which declarations to refuse before writing anything, then writes the rest together. A
        declaration's session, file attachments, topics, and time ranges are created together or not at all, and a
        declaration Roboto refuses leaves the others written as if it were absent. None of the declarations is
        written when a failure Roboto did not anticipate, such as a timeout, interrupts the call, or when a session a
        declaration reuses is deleted before the call completes, which raises
        :py:class:`~roboto.exceptions.RobotoNotFoundException`. Each declaration is written as it would be had the
        ones before it been sent as calls of their own: a later declaration anchoring data an earlier one holds moves
        the earlier session's time range with it. A refused declaration, or a call that fails, still leaves behind
        the topic identifiers and schema definitions it resolved, which a resend reuses.

        Check :py:attr:`~roboto.http.BatchResponse.failed` before treating the batch as done. Each entry there is the
        :py:class:`~roboto.exceptions.RobotoDomainException` Roboto refused a declaration with, so ``isinstance``
        tells the reasons apart; a refusal under an error code this SDK release does not define arrives as
        :py:class:`~roboto.exceptions.RobotoUnrecognizedErrorException`.

        Resending the same call is safe. This device and each declaration's ``name`` identify the session the
        declaration creates or reuses, so a resend fills in only what is missing rather than duplicating what an
        earlier attempt created.

        Declared times are stored exactly as given, in each file's own timestamps, and read as nanoseconds since the
        Unix epoch; Roboto never invents a wall-clock time. A recording whose timestamps start at 0 therefore sits at
        the epoch until it is anchored. To place a session at the wall-clock time it happened, supply
        :py:attr:`~roboto.experimental.sessions.SessionDeclaration.anchor_ns`, or call
        :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset` later.

        Args:
            sessions: One declaration per session to create. An empty sequence returns an empty response without
                contacting Roboto.

        Returns:
            A :py:class:`~roboto.http.BatchResponse` with one element per declaration, in request order, holding
            either the session the declaration created or why Roboto refused it. A declaration naming a session this
            device already holds yields that session rather than a second one.

        Raises:
            pydantic.ValidationError: More than 100 declarations are given, the batch declares more than 500 files and
                topics combined, the same session name is declared more than once, or representations name one file
                in two storage formats. Raised while the request body is built, before anything is sent to Roboto.
            RobotoInvalidRequestException: The batch is malformed. Nothing is created.
            RobotoNotFoundException: This device is no longer registered; the ``file_id`` of a file entry, or of a
                representation one of its topics lists, does not name a file in this device's organization whose
                status is :py:attr:`~roboto.domain.files.FileStatus.Available`; or a session a declaration reuses is
                deleted before the call completes. Nothing is created.
            RobotoUnauthorizedException: The caller cannot create sessions on this device, or cannot edit a file a
                declaration declares topics on, a file it anchors, or a file a listed representation names, or lacks
                topic edit access in this device's organization while a declaration states ``is_default_for_reads``
                on a timeline source.

        Examples:
            Register two chunks of one recording as a single session, each chunk's topic data read from the chunk
            itself:

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
            >>> dataset = Dataset.from_id("ds_12345")
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
        """Create an access token that makes requests as this device.

        Roboto returns the token's secret only in this response; it cannot be fetched again, so store it.

        Args:
            expiry_days: Number of days the token stays valid, counted from its creation.
            name: Human-readable name of the token. ``None`` names it ``<org_id>_<device_id>``.
            description: Human-readable description of the token.
            api_scopes: API scopes the token is limited to. ``None`` or an empty collection grants every scope. The
                token cannot be granted more than the credential creating it holds.

        Returns:
            ``(token, secret)``: the new token and its secret.

        Examples:
            Create a token that expires in 366 days:

            >>> device = Device.from_id("robot_001", org_id="og_12345")
            >>> token, secret = device.create_token()

            Create a token that expires in 30 days, with a name and description:

            >>> token, secret = device.create_token(
            ...     expiry_days=30, name="Monthly Upload Token", description="Token for automated monthly data uploads"
            ... )
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

    def delete(self, keep_configurations: bool = False) -> None:
        """Delete the device, with its access tokens and its configurations. This cannot be undone.

        The device's tokens are deleted with it. Its ``configurations`` are deleted shortly after this call returns,
        every version of each file. With ``keep_configurations=True`` they move to the organization's assets
        (:py:attr:`~roboto.domain.orgs.Org.assets`) instead, under ``devices/<universal_device_id>/``, keeping their
        file IDs and every version. Links among the device's
        configurations are deleted in both cases, and the files they point at are left alone.

        Shortly after this call returns, Roboto also clears the device's ID from the ``device_id`` of the
        organization's datasets and of every version of its files, unless a device with the same ID is created in the
        organization before then.

        Deleting a device that no longer exists succeeds and changes nothing.

        Args:
            keep_configurations: Whether to move the device's configurations to the organization's assets instead of
                deleting them.

        Raises:
            RobotoUnauthorizedException: ``keep_configurations`` is ``True`` and the caller cannot upload files to the
                organization.
            RobotoConflictException: ``keep_configurations`` is ``True`` and the organization's assets hold a file,
                not a directory, at ``devices`` or ``devices/<universal_device_id>``.

        Examples:
            Delete a device and its configurations:

            >>> device = Device.from_id("old_robot_001")
            >>> device.delete()

            Delete a device but keep its configurations in the organization's assets:

            >>> device = Device.from_id("old_robot_002")
            >>> device.delete(keep_configurations=True)
        """
        self.__roboto_client.delete(
            f"v1/devices/id/{self.encoded_device_id}",
            owner_org_id=self.org_id,
            query={"keep_configurations": "true"} if keep_configurations else None,
        )

    @experimental
    def list_sessions(self) -> collections.abc.Generator[Session, None, None]:
        """List the sessions on this device.

        Fetches the sessions a page at a time, as the generator is iterated.

        Examples:
            Print the name of every session on a device:

            >>> device = Device.from_id("robot_001", org_id="og_12345")
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
        """Set metadata keys on the device, adding new keys and overwriting existing ones.

        Keys the dict does not name keep their values.

        Args:
            metadata: Key-value metadata to set on the device.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.put_metadata({"firmware_version": "2.1.0", "location": "warehouse-b"})
            >>> print(updated_device.metadata["firmware_version"])
            2.1.0
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(put_fields=metadata)))

    def put_tags(self, tags: list[str]) -> "Device":
        """Add tags to the device, keeping its existing tags.

        A tag the device already has is not added again.

        Args:
            tags: Tags to add to the device.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.put_tags(["production", "warehouse-c"])
            >>> print("production" in updated_device.tags)
            True
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(put_tags=tags)))

    def remove_metadata(self, keys: list[str]) -> "Device":
        """Remove metadata keys from the device.

        Args:
            keys: Metadata keys to remove.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.remove_metadata(["old_field", "deprecated_key"])
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(remove_fields=keys)))

    def remove_tags(self, tags: list[str]) -> "Device":
        """Remove tags from the device.

        Args:
            tags: Tags to remove from the device.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> updated_device = device.remove_tags(["old_tag", "deprecated"])
        """
        return self.update(UpdateDeviceRequest(metadata_changeset=MetadataChangeset(remove_tags=tags)))

    def set_device_type(self, device_type_id: typing.Optional[str]) -> "Device":
        """Assign a device type to the device, or remove its type.

        The device's own configurations are unaffected. Listing them with ``include_inherited=True`` afterwards
        includes the new type's configurations, or only the device's own when the type was removed.

        Args:
            device_type_id: ID of a device type in the device's organization, beginning with ``dt_``. ``None``
                removes the device's type.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoInvalidRequestException: ``device_type_id`` is not ``None`` and the organization has no such device
                type.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> device.set_device_type("dt_12345").device_type_id
            'dt_12345'
            >>> device.set_device_type(None).device_type_id is None
            True
        """
        return self.update(UpdateDeviceRequest(device_type_id=device_type_id))

    @experimental
    def set_custom_field(self, name: str, value: typing.Any) -> "Device":
        """Set one custom-field value on the device.

        Args:
            name: Name of a custom field defined for devices in the device's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            value: Value to set, which must match the field's declared type.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for devices, or ``value`` does not
                match its type.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> device = device.set_custom_field("firmware_version", "2.1.0")
        """
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value})))

    @experimental
    def clear_custom_field(self, name: str) -> "Device":
        """Clear one custom-field value on the device, so the field reads back as ``None``.

        Args:
            name: Name of a ready custom field defined for devices in the device's organization.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for devices.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> device.clear_custom_field("firmware_version").custom_fields["firmware_version"] is None
            True
        """
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name])))

    @experimental
    def set_custom_fields(self, fields: dict[str, typing.Any]) -> "Device":
        """Set several custom-field values on the device. Fields not named keep their values.

        Args:
            fields: New values keyed by field name. Each name must be a custom field defined for devices in the
                device's organization, with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`,
                and each value must match that field's declared type.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for devices, or a value does not match
                its field's type.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> device = device.set_custom_fields({"firmware_version": "2.1.0", "site": "warehouse-b"})
        """
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(set_fields=fields)))

    @experimental
    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> "Device":
        """Clear several custom-field values on the device, so each field reads back as ``None``.

        Args:
            names: Names of ready custom fields defined for devices in the device's organization.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for devices.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> device = device.clear_custom_fields(["firmware_version", "site"])
        """
        return self.update(UpdateDeviceRequest(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names))))

    def tokens(self) -> collections.abc.Sequence[Token]:
        """Fetch the device's access tokens, expired ones included.

        The tokens come without their secrets, which Roboto returns only from ``create_token``. At most 1,000 tokens
        are returned.

        Examples:
            >>> device = Device.from_id("robot_001")
            >>> for token in device.tokens():
            ...     print(token.token_id)
        """
        records = self.__roboto_client.get(
            f"v1/devices/id/{self.encoded_device_id}/tokens", owner_org_id=self.org_id
        ).to_record_list(TokenRecord)
        return [Token(record=record, roboto_client=self.__roboto_client) for record in records]

    def update(self, request: UpdateDeviceRequest) -> "Device":
        """Update the device's properties.

        Args:
            request: Changes to apply. Each field left at its default leaves that property unchanged.

        Returns:
            A new ``Device`` holding the updated record. This instance keeps its earlier record.

        Raises:
            RobotoInvalidRequestException: ``request.device_type_id`` names no device type in the organization.
            RobotoIllegalArgumentException: The custom-field changeset names a field that is not a ready custom field
                for devices, or sets a value that does not match its field's type.

        Examples:
            >>> from roboto.domain.devices import UpdateDeviceRequest
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
