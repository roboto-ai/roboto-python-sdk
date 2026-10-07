# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import pathlib
import typing
import urllib.parse

from ...association import Association
from ...exceptions import (
    RobotoIllegalArgumentException,
    RobotoNotFoundException,
)
from ...experimental import topics as experimental_topics
from ...experimental.ingest import (
    DeclaredTimelineSource,
    FileTopicDeclaration,
    RepresentationDeclaration,
    Schema,
    TopicRepresentations,
)
from ...experimental.ingest.operations import DeclareTopicsRequest, SetRepresentationsRequest
from ...http import (
    BatchRequest,
    BatchResponse,
    RobotoClient,
)
from ...progress import (
    NoopProgressMonitor,
    TqdmProgressMonitor,
)
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...storage import FileService
from ...time import Time, TimeUnit, to_epoch_nanoseconds
from ...updates import MetadataChangeset
from ...uri import RobotoUri
from ...warnings import experimental
from ..topics import (
    SetTimelineOffsetsRequest,
    TimelineExtentRecord,
    TimelineOffsetEntry,
    TimelineSourceRecord,
    Topic,
    TopicIdentityRecord,
)
from .operations import (
    ImportFileRequest,
    RenameFileRequest,
    UpdateFileRecordRequest,
)
from .record import FileRecord, IngestionStatus

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


class File:
    """Represents a file within the Roboto platform.

    Files are the fundamental data storage unit in Roboto. They can be uploaded to datasets,
    imported from external sources, or created as outputs from actions. Once in the platform,
    files can be tagged with metadata, post-processed by actions, added to collections,
    visualized in the web interface, and searched using the query system.

    Files contain structured data that can be ingested into topics for analysis and visualization.
    Common file formats include ROS bags, MCAP files, ULOG files, CSV files, and many others.
    Each file has an associated ingestion status that tracks whether its data has been processed
    and made available for querying.

    Files are versioned entities - each modification creates a new version while preserving
    the history. Files are associated with datasets and inherit access permissions from their
    parent dataset.

    The File class provides methods for downloading, updating metadata, managing tags,
    accessing topics, and performing other file operations. It serves as the primary interface
    for file manipulation in the Roboto SDK.
    """

    __file_service: FileService
    __record: FileRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        file_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> File:
        """Create a File instance from a file ID.

        Retrieves file information from the Roboto platform using the provided file ID
        and optionally a specific version.

        Args:
            file_id: Unique identifier for the file.
            version_id: Specific version of the file to retrieve. If None, gets the latest version.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            File instance representing the requested file.

        Raises:
            RobotoNotFoundException: File with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> print(file.relative_path)
            'data/sensor_logs.bag'

            >>> old_version = File.from_id("file_abc123", version_id=1)
            >>> print(old_version.version)
            1
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/files/record/{file_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_path_and_dataset_id(
        cls,
        file_path: typing.Union[str, pathlib.Path],
        dataset_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> File:
        """Create a File instance from a file path and dataset ID.

        Retrieves file information using the file's relative path within a specific dataset.
        This is useful when you know the file's location within a dataset but not its file ID.

        Args:
            file_path: Relative path of the file within the dataset.
            dataset_id: ID of the dataset containing the file.
            version_id: Specific version of the file to retrieve. If None, gets the latest version.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            File instance representing the requested file.

        Raises:
            RobotoNotFoundException: File at the given path does not exist in the dataset.
            RobotoUnauthorizedException: Caller lacks permission to access the file or dataset.

        Examples:
            >>> file = File.from_path_and_dataset_id("logs/session1.bag", "ds_abc123")
            >>> print(file.file_id)
            'file_xyz789'

            >>> file = File.from_path_and_dataset_id(pathlib.Path("data/sensors.csv"), "ds_abc123")
            >>> print(file.relative_path)
            'data/sensors.csv'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        url_quoted_file_path = urllib.parse.quote(str(file_path), safe="")
        record = roboto_client.get(
            f"v1/files/record/path/{url_quoted_file_path}/association/{dataset_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def import_batch(
        cls,
        requests: collections.abc.Sequence[ImportFileRequest],
        roboto_client: typing.Optional[RobotoClient] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Sequence[File]:
        """Import files from customer S3 bring-your-own buckets into Roboto datasets.

        This is the ingress point for importing data stored in customer-owned S3 buckets
        that have been registered as read-only bring-your-own bucket (BYOB) integrations with
        Roboto. Files remain in their original S3 locations while metadata is registered with
        Roboto for discovery, processing, and analysis.

        This method only works with S3 URIs from buckets that have been properly registered
        as BYOB integrations for your organization. It performs batch operations to efficiently
        import multiple files in a single API call, reducing overhead and improving performance.

        Args:
            requests: Sequence of import requests, each specifying file details and metadata.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            caller_org_id: Organization ID of the caller. Required for multi-org users.

        Returns:
            Sequence of File objects representing the imported files.

        Raises:
            RobotoInvalidRequestException: If any URI is not a valid S3 URI, if the batch
                exceeds 500 items, or if bucket integrations are not properly configured.
            RobotoUnauthorizedException: If the caller lacks upload permissions for target
                datasets or if buckets don't belong to the caller's organization.

        Notes:
            - Only works with S3 URIs from registered read-only BYOB integrations
            - Files are not copied; only metadata is imported into Roboto
            - Batch size is limited to 500 items per request
            - All S3 buckets must be registered to the caller's organization

        Examples:
            >>> from roboto.domain.files import ImportFileRequest
            >>> requests = [
            ...     ImportFileRequest(
            ...         dataset_id="ds_abc123",
            ...         relative_path="logs/session1.bag",
            ...         uri="s3://my-bucket/data/session1.bag",
            ...         size=1024000,
            ...     ),
            ...     ImportFileRequest(
            ...         dataset_id="ds_abc123",
            ...         relative_path="logs/session2.bag",
            ...         uri="s3://my-bucket/data/session2.bag",
            ...         size=2048000,
            ...     ),
            ... ]
            >>> files = File.import_batch(requests)
            >>> print(f"Imported {len(files)} files")
            Imported 2 files
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        # Requests explicitly need to be cast to list because of Pydantic serialization not working appropriately
        # with collections.abc
        request: BatchRequest[ImportFileRequest] = BatchRequest(requests=list(requests))

        records = roboto_client.post(
            "v1/files/import/batch",
            data=request,
            idempotent=True,
            caller_org_id=caller_org_id,
        ).to_record_list(FileRecord)
        return [cls(record, roboto_client) for record in records]

    @classmethod
    def import_one(
        cls,
        dataset_id: str,
        relative_path: str,
        uri: str,
        description: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        device_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> File:
        """Import a single file from an external bucket into a Roboto dataset. This currently only supports AWS S3.

        This is a convenience method for importing a single file from customer-owned buckets
        that have been registered as bring-your-own bucket (BYOB) integrations with
        Roboto. Unlike :py:meth:`import_batch`, this method automatically determines the file size
        by querying the object store and verifies that the object actually exists before
        importing, providing additional validation and convenience for single-file operations.

        The file remains in its original location while metadata is registered with Roboto
        for discovery, processing, and analysis. This method currently only works with S3 URIs from buckets
        that have been properly registered as BYOB integrations for your organization.

        Args:
            dataset_id: ID of the dataset to import the file into.
            relative_path: Path of the file relative to the dataset root (e.g., `logs/session1.bag`).
            uri: URI where the file is located (e.g., `s3://my-bucket/path/to/file.bag`).
                Must be from a registered BYOB integration.
            description: Optional human-readable description of the file.
            tags: Optional list of tags for file discovery and organization.
            metadata: Optional key-value metadata pairs to associate with the file.
            device_id: Optional identifier of the device that generated this data.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            File object representing the imported file.

        Raises:
            RobotoInvalidRequestException: If the URI is not a valid URI or if the bucket
                integration is not properly configured.
            RobotoNotFoundException: If the specified object does not exist.
            RobotoUnauthorizedException: If the caller lacks upload permissions for the target
                dataset or if the bucket doesn't belong to the caller's organization.

        Notes:
            - Only works with S3 URIs from registered BYOB integrations
            - File size is automatically determined from the object metadata
            - The file is not copied; only metadata is imported into Roboto
            - For importing multiple files efficiently, use :py:meth:`import_batch` instead

        Examples:
            Import a single ROS bag file:

            >>> from roboto.domain.files import File
            >>> file = File.import_one(
            ...     dataset_id="ds_abc123", relative_path="logs/session1.bag", uri="s3://my-bucket/data/session1.bag"
            ... )
            >>> print(f"Imported file: {file.relative_path}")
            Imported file: logs/session1.bag

            Import a file with metadata and tags:

            >>> file = File.import_one(
            ...     dataset_id="ds_abc123",
            ...     relative_path="sensors/lidar_data.pcd",
            ...     uri="s3://my-bucket/sensors/lidar_data.pcd",
            ...     description="LiDAR point cloud from highway test",
            ...     tags=["lidar", "highway", "test"],
            ...     metadata={"sensor_type": "Velodyne", "resolution": "high"},
            ... )
            >>> print(f"File size: {file.size} bytes")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = ImportFileRequest(
            dataset_id=dataset_id,
            relative_path=relative_path,
            uri=uri,
            description=description,
            tags=tags,
            metadata=metadata,
            device_id=device_id,
        )
        record = roboto_client.post("v1/files/import", data=request).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator[File, None, None]:
        """Query files using a specification with filters and pagination.

        Searches for files matching the provided query specification. Results are returned
        as a generator that automatically handles pagination, yielding File instances as
        they are retrieved from the API.

        Args:
            spec: Query specification with filters, sorting, and pagination options.
                If None, returns all accessible files.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            owner_org_id: Organization ID to scope the query. If None, uses caller's org.

        Yields:
            File instances matching the query specification.

        Raises:
            ValueError: Query specification references unknown file attributes.
            RobotoUnauthorizedException: Caller lacks permission to query files.

        Examples:
            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(field="tags", comparator=Comparator.Contains, value="sensor-data")
            ... )
            >>> for file in File.query(spec):
            ...     print(f"Found file: {file.relative_path}")
            Found file: logs/sensors_2024_01_01.bag
            Found file: logs/sensors_2024_01_02.bag

            >>> # Query with metadata filter
            >>> spec = QuerySpecification(
            ...     condition=Condition(field="metadata.vehicle_id", comparator=Comparator.Equals, value="vehicle_001")
            ... )
            >>> files = list(File.query(spec))
            >>> print(f"Found {len(files)} files for vehicle_001")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(FileRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # Support dot notation for nested fields
            # E.g., "metadata.SoftwareVersion"
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = "are not known attributes of File" if plural else "is not a known attribute of File"
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        while True:
            paginated_results = roboto_client.post(
                "v1/files/query", data=spec, owner_org_id=owner_org_id, idempotent=True
            ).to_paginated_list(FileRecord)

            for record in paginated_results.items:
                yield cls(record, roboto_client)

            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: FileRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        file_service: typing.Optional[FileService] = None,
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__file_service = file_service or FileService(self.__roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """Timestamp when this file was created.

        Returns the UTC datetime when this file was first uploaded or created
        in the Roboto platform. This timestamp is immutable.
        """
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Identifier of the user who created this file.

        Returns the user ID or identifier of the person or service that originally
        uploaded or created this file in the Roboto platform.
        """
        return self.__record.created_by

    @property
    def association(self) -> Association:
        """The dataset, device, or org this file is associated with.

        Every file has exactly one association, inferred from the prefix of its association ID. Read
        ``file.association.association_type`` to branch on it.
        """
        return Association.from_id(self.__record.association_id)

    @property
    def dataset_id(self) -> str:
        """Identifier of the dataset that contains this file.

        Valid only for a file associated with a dataset; files associated with a device or with the org
        itself have no dataset. Prefer :py:attr:`association`, which works for every file.

        Raises:
            RobotoIllegalArgumentException: This file is not associated with a dataset.
        """
        association = self.association
        if not association.is_dataset:
            raise RobotoIllegalArgumentException(
                f"File {self.file_id} is not in a dataset; its association is "
                f"{association.association_type.value} {association.association_id}. Use File.association instead."
            )
        return association.association_id

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of this file.

        Returns the optional description text that provides details about the file's
        contents, purpose, or context. Can be None if no description was provided.
        """
        return self.__record.description

    @property
    def device_id(self) -> typing.Optional[str]:
        """Identifier of the device that generated this data.

        Returns the optional identifier of the device that generated the data
        contained within this file. Can be None if the file was not generated
        by a device.
        """
        return self.__record.device_id

    @property
    def file_id(self) -> str:
        """Unique identifier for this file.

        Returns the globally unique identifier assigned to this file when it was
        created. This ID is immutable and used to reference the file across the
        Roboto platform.
        """
        return self.__record.file_id

    @property
    def ingestion_status(self) -> IngestionStatus:
        """Current ingestion status of this file.

        Returns the status indicating whether this file has been processed and
        its data extracted into topics. Used to track ingestion pipeline progress.
        """
        return self.__record.ingestion_status

    @property
    def is_link(self) -> bool:
        """Whether this file is a link to one version of another file.

        A link sits at its own path under its own dataset, device, or org, and stores no object.
        :py:meth:`download` and :py:meth:`get_signed_url` fetch the target at the version the link pins.
        """
        return self.__record.is_link

    @property
    def org_id(self) -> str:
        """Organization identifier that owns this file.

        Returns the unique identifier of the organization that owns and has
        primary access control over this file.
        """
        return self.__record.org_id

    @property
    def record(self) -> FileRecord:
        """Underlying data record for this file.

        Returns the raw :py:class:`~roboto.domain.files.FileRecord` that contains
        all the file's data fields. This provides access to the complete file
        state as stored in the platform.
        """
        return self.__record

    @property
    def relative_path(self) -> str:
        """Path of this file relative to the root of its association's files.

        Uses forward slashes as separators regardless of the operating system. This path
        uniquely identifies the file among the files of its dataset, device, or org.
        """
        return self.__record.relative_path

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Custom metadata associated with this file.

        Returns the file's metadata dictionary containing arbitrary key-value
        pairs for storing custom information. Supports nested structures and
        dot notation for accessing nested fields.
        """
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        """Timestamp when this file was last modified.

        Returns the UTC datetime when this file's metadata, tags, or other
        properties were most recently updated. The file content itself is
        immutable, but metadata can be modified.
        """
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Identifier of the user who last modified this file.

        Returns the user ID or identifier of the person who most recently updated
        this file's metadata, tags, or other mutable properties.
        """
        return self.__record.modified_by

    @property
    def tags(self) -> list[str]:
        """List of tags associated with this file.

        Returns the list of string tags that have been applied to this file
        for categorization and filtering purposes.
        """
        return self.__record.tags

    @property
    def uri(self) -> str:
        """Storage URI for this file's content.

        Returns the storage location URI where the file's actual content is stored.
        This is typically an S3 URI or similar cloud storage reference.
        """
        return self.__record.uri

    @property
    def version(self) -> int:
        """Version number of this file.

        Returns the version number that increments each time the file's metadata
        or properties are updated. The file content itself is immutable, but
        metadata changes create new versions.
        """
        return self.__record.version

    def add_topic(
        self,
        topic_name: str,
        df: "pandas.DataFrame",
        timestamp_column: typing.Optional[str] = None,
        timestamp_unit: typing.Optional[typing.Union[str, TimeUnit]] = None,
    ) -> Topic:
        """Create a Topic from a pandas DataFrame and associate it with this file.

        If a topic with the same name already exists for this file, it will be updated
        with the new data and schema.

        Args:
            topic_name: Name for the topic. Must be unique within this file.
            df: pandas DataFrame containing the data to ingest. Must include a timestamp
                column (either explicitly specified or automatically detectable).
            timestamp_column: Name of the column to use as the timestamp. If not provided,
                the method will attempt to automatically detect a timestamp column by looking
                for the first column that is a timezone-aware timestamp type.
            timestamp_unit: Unit of the timestamp column values. Required when timestamp_column
                contains numeric values (int, float, decimal).
                Valid values include "s", "ms", "us", "ns".
                Not needed for datetime columns or when timestamp_column is not specified.

        Returns:
            The created or updated Topic instance.

        Raises:
            IngestionException: If the timestamp column cannot be determined, is not present
                in the DataFrame, has an invalid type, or if the timestamp unit is required
                but not provided.
            ImportError: If pandas or pyarrow are not installed. Install with
                ``pip install roboto[ingestion]`` to use this feature.
            RobotoIllegalArgumentException: This file is associated with a device or with the org itself, not
                with a dataset; only a dataset's files hold topics.
            RobotoUnauthorizedException: If the caller lacks permission to create topics
                or upload files to this file's dataset.

        Notes:
            - Requires installing this package using the ``roboto[ingestion]`` extra
            - Topic names are unique within a file
            - Schema and statistics are automatically inferred from the DataFrame

        Examples:
            Create a topic with explicit timestamp column and unit:

            >>> import pandas as pd
            >>> from roboto import File
            >>> file = File.from_id("file_abc123")
            >>> df = pd.DataFrame(
            ...     {
            ...         "timestamp": [1763947309.4198897, 1763947316.7686195, 1763947335.0095527],
            ...         "temperature": [20.5, 21.0, 20.8],
            ...         "humidity": [45.2, 46.1, 45.8],
            ...     }
            ... )
            >>> topic = file.add_topic(
            ...     topic_name="sensor_data", df=df, timestamp_column="timestamp", timestamp_unit="s"
            ... )
            >>> print(f"Created topic: {topic.name}")
            Created topic: sensor_data

            Create a topic with automatic timestamp detection:

            >>> import pandas as pd
            >>> from roboto import File
            >>> file = File.from_id("file_abc123")
            >>> df = pd.DataFrame(
            ...     {
            ...         "ts": pd.date_range("2025-11-24", periods=3, freq="1s", tz="UTC"),
            ...         "velocity": [10.5, 11.2, 10.8],
            ...         "acceleration": [0.5, 0.3, -0.2],
            ...     }
            ... )
            >>> topic = file.add_topic("motion_data", df)

            Retrieve the data back

            >>> retrieved_df = topic.get_data_as_df()
            >>> print(f"Retrieved {len(retrieved_df)} rows")
            Retrieved 3 rows

            Add derived data as a new topic to the same file, using the original topic's timestamp index:

            >>> import pandas as pd
            >>> from roboto import File
            >>> file = File.from_id("file_abc123")
            >>> # Get existing topic data as DataFrame
            >>> original_topic = file.get_topic("sensor_data")
            >>> original_df = original_topic.get_data_as_df()
            >>> # Create derived data
            >>> derived_df = pd.DataFrame(
            ...     {
            ...         "temp_category": original_df["temperature"].apply(lambda x: "hot" if x > 25 else "not_hot"),
            ...     },
            ...     index=original_df.index,
            ... )
            >>> derived_topic = file.add_topic(
            ...     "temperature_categories",
            ...     derived_df,
            ... )
        """
        association = self.association
        if not association.is_dataset:
            raise RobotoIllegalArgumentException(
                f"File {self.file_id} is not in a dataset, so it cannot hold topics; its association is "
                f"{association.association_type.value} {association.association_id}."
            )
        return Topic.create_from_df(
            self.file_id,
            association.association_id,
            topic_name,
            df,
            timestamp_column=timestamp_column,
            timestamp_unit=timestamp_unit,
            caller_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    @experimental
    def declare_topic(
        self,
        topic_name: str,
        topic_schema: Schema,
        timeline_sources: collections.abc.Sequence[DeclaredTimelineSource],
        data_range: typing.Optional[tuple[int, int]] = None,
        anchor: typing.Optional[Time] = None,
        representations: collections.abc.Sequence[RepresentationDeclaration] = (),
    ) -> experimental_topics.Topic:
        """Register one topic this File contributes data to, without naming a Session.

        The singular form of :py:meth:`declare_topics`, taking the fields of one
        :py:class:`~roboto.experimental.ingest.FileTopicDeclaration` as separate arguments. That class
        documents what each field means; :py:meth:`declare_topics` documents what the platform does with it.

        Args:
            topic_name: Topic this File contributes data to. Topic names are unique within an org.
            topic_schema: Structure of the topic's data.
            timeline_sources: Timeline sources this File's topic data carries, each with the bounds it
                spans in this File, stated in the File's own timestamps.
            data_range: The part of the File this topic's data occupies, or ``None`` for the whole File.
            anchor: Optional wall-clock instant the data this declaration names was captured at: an ``int``
                of nanoseconds since the Unix epoch, or any other :py:data:`~roboto.time.Time`, read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime`` or ISO 8601 string is
                that instant; a ``float``, ``Decimal``, or numeric string is seconds since the epoch). Must fall
                after the Unix epoch.
            representations: The files a read of this topic's data opens, each with how it holds that data:
                this File, when its own bytes are readable, and other files when the data is read from them,
                such as files converted out of it. Empty lists none, and reads of a topic with no representations
                return no rows.

        Returns:
            The topic this declaration registered against.

        Raises:
            TypeError: If ``anchor`` is not one of the :py:data:`~roboto.time.Time` types.
            ValueError: If ``anchor`` is a boolean, a negative number (an ``int``, ``float``, ``Decimal``, or
                numeric string), or a string that is neither a number of seconds nor an ISO 8601 timestamp.
                Raised before anything is sent to the platform.
            OverflowError: If ``anchor`` is an infinite ``float``, ``Decimal``, or string, such as ``"inf"``.
                Raised before anything is sent to the platform.
            pydantic.ValidationError: If these arguments do not form a valid
                :py:class:`~roboto.experimental.ingest.FileTopicDeclaration`, for instance two representations of
                the whole topic, or of one field, sharing a storage format, content format and transformations,
                or any timeline source but :py:class:`~roboto.experimental.ingest.SchemaFieldSource` beside a
                ``PARQUET`` representation, or if ``representations`` names one file in two storage formats.
                Enforced before anything is sent to the platform.
            RobotoDomainException: Whatever the platform refused this declaration with.

        Examples:
            >>> from roboto.domain.files import File
            >>> from roboto.domain.topics import CanonicalDataType, RepresentationStorageFormat
            >>> from roboto.experimental.ingest import Field, RepresentationDeclaration, Schema, SchemaFieldSource
            >>> timestamp = Field(
            ...     name="timestamp",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Timestamp,
            ...     unit="s",
            ... )
            >>> file = File.from_id("fl_0123456789ab")
            >>> topic = file.declare_topic(
            ...     topic_name="observation.state",
            ...     topic_schema=Schema(
            ...         name="observation.state",
            ...         fields=[timestamp, Field(name="observation.state", data_type="float32")],
            ...     ),
            ...     timeline_sources=[
            ...         SchemaFieldSource(
            ...             field_path=["timestamp"],
            ...             min_file_timestamp_ns=0,
            ...             max_file_timestamp_ns=4_000,
            ...         )
            ...     ],
            ...     representations=[
            ...         RepresentationDeclaration(
            ...             file_id=file.file_id,
            ...             storage_format=RepresentationStorageFormat.PARQUET,
            ...         )
            ...     ],
            ... )
            >>> print(topic.topic_id)
        """
        declaration = FileTopicDeclaration(
            topic_name=topic_name,
            topic_schema=topic_schema,
            timeline_sources=list(timeline_sources),
            data_range=data_range,
            anchor_ns=None if anchor is None else to_epoch_nanoseconds(anchor),
            representations=list(representations),
        )
        return self.declare_topics([declaration]).single()

    @experimental
    def declare_topics(
        self,
        topics: collections.abc.Sequence[FileTopicDeclaration],
    ) -> BatchResponse[experimental_topics.Topic]:
        """Register the topic data this File carries, without naming a Session.

        One call states everything the platform needs to serve this File's topic data: for each topic, the
        structure of its rows, the timeline sources those rows carry with the bounds they span in this File,
        and, when the File packs its data into slices, which slice the topic occupies. The platform does not
        open the File when topics are declared on it, so this declaration is all it knows about the File's
        contents.

        The platform applies each declaration on its own: one it refuses leaves the others registered, and
        the response says what became of each. Nothing about the call involves a Session, so declarations on
        the Files of one recording can run concurrently, and a File's topic data can be registered before the
        Session holding it exists. A Session takes that data on by attaching the File, through
        :py:meth:`~roboto.experimental.sessions.Session.add_file` or a
        :py:class:`~roboto.experimental.sessions.SessionFile` carrying no topics. A Session already holding
        the File takes on what this call declares before the call returns, with its time bounds recomputed to
        cover the newly declared data.

        Resending the same call is safe: the platform identifies the data a declaration registers by the
        topic plus the slice of the File that declaration names, so a resend converges on what the first
        attempt registered rather than duplicating it, and a corrected redeclaration replaces what it
        corrects.

        A declaration states its bounds in the File's own timestamps, read as nanoseconds since the Unix
        epoch; the platform never invents a wall-clock time. Data whose timestamps start at 0 therefore sits
        at the epoch until it is anchored. To place it at the wall-clock time it was captured, supply
        :py:attr:`~roboto.experimental.ingest.FileTopicDeclaration.anchor_ns`, which anchors the whole slice
        it names rather than the one topic declaring it, so the topics sharing a slice must agree on it.

        The topic data belongs to this File: its bounds, anchors and slices are stated against it, and a
        Session holding this File holds the data. What makes the data readable is each topic's
        :py:attr:`~roboto.experimental.ingest.TopicDeclaration.representations`: the files a read opens to get
        it, each decoded in the storage format its representation states. A file's name and extension are not
        used. A topic lists this File when its own bytes are readable, and other files when the data is read
        from them, such as the per-topic MCAPs converted out of a PX4 ULog. A topic with no representations is
        still registered and still counts toward the bounds of the Sessions holding the File,
        but reads of it return no rows. :py:class:`~roboto.experimental.ingest.RepresentationDeclaration` states
        what a representation's file must hold and when a read can decode an ``MCAP`` representation's file.

        Redeclaring a topic adds the representations listed to the ones it has, each taking the place of the
        stored ones it matches, as :py:attr:`~roboto.experimental.ingest.TopicDeclaration.representations`
        describes. To remove a representation, or to replace a topic's representations outright,
        use :py:meth:`set_representations`.

        Args:
            topics: One declaration per topic and slice of this File. An empty sequence returns an empty
                response without contacting the platform.

        Returns:
            One element per declaration, in request order, holding either the topic it registered against or
            why the platform refused it.

        Raises:
            pydantic.ValidationError: If more than
                :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST` topics are given, one
                topic is declared twice over the same slice, two topics anchor one slice at different
                instants, or representations name one file in two storage formats. These are enforced when the
                request body is constructed, before anything is sent to the platform; each declaration's own
                rules are enforced earlier, when the caller builds it.
            RobotoNotFoundException: If this File no longer exists, or a representation names a file that does
                not exist in this File's org or whose status is not
                :py:attr:`~roboto.domain.files.FileStatus.Available`. Nothing is registered.
            RobotoUnauthorizedException: If the caller lacks edit access to this File or to a file a listed
                representation names, or lacks topic edit access in this File's org while a declaration states
                ``is_default_for_reads`` on a timeline source.

        Examples:
            Register the two topics a LeRobot episode file carries, each read from the file's own bytes:

            >>> from roboto.domain.files import File
            >>> from roboto.domain.topics import CanonicalDataType, RepresentationStorageFormat
            >>> from roboto.experimental.ingest import (
            ...     Field,
            ...     FileTopicDeclaration,
            ...     RepresentationDeclaration,
            ...     Schema,
            ...     SchemaFieldSource,
            ... )
            >>> timestamp = Field(
            ...     name="timestamp",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Timestamp,
            ...     unit="s",
            ... )
            >>> file = File.from_id("fl_0123456789ab")
            >>> from_file = RepresentationDeclaration(
            ...     file_id=file.file_id,
            ...     storage_format=RepresentationStorageFormat.PARQUET,
            ... )
            >>> registered = file.declare_topics(
            ...     [
            ...         FileTopicDeclaration(
            ...             topic_name="observation.state",
            ...             topic_schema=Schema(
            ...                 name="observation.state",
            ...                 fields=[timestamp, Field(name="observation.state", data_type="float32")],
            ...             ),
            ...             timeline_sources=[
            ...                 SchemaFieldSource(
            ...                     field_path=["timestamp"],
            ...                     min_file_timestamp_ns=0,
            ...                     max_file_timestamp_ns=4_000,
            ...                 )
            ...             ],
            ...             representations=[from_file],
            ...         ),
            ...         FileTopicDeclaration(
            ...             topic_name="action",
            ...             topic_schema=Schema(
            ...                 name="action",
            ...                 fields=[timestamp, Field(name="action", data_type="float32")],
            ...             ),
            ...             timeline_sources=[
            ...                 SchemaFieldSource(
            ...                     field_path=["timestamp"],
            ...                     min_file_timestamp_ns=0,
            ...                     max_file_timestamp_ns=4_000,
            ...                 )
            ...             ],
            ...             representations=[from_file],
            ...         ),
            ...     ],
            ... )
            >>> print([topic.topic_id for topic in registered.succeeded])

            Register a topic over the slice of a shared file that holds one episode, anchored at the
            instant that episode was recorded:

            >>> registered = file.declare_topics(
            ...     [
            ...         FileTopicDeclaration(
            ...             topic_name="observation.state",
            ...             topic_schema=Schema(
            ...                 name="observation.state",
            ...                 fields=[timestamp, Field(name="observation.state", data_type="float32")],
            ...             ),
            ...             timeline_sources=[
            ...                 SchemaFieldSource(
            ...                     field_path=["timestamp"],
            ...                     min_file_timestamp_ns=0,
            ...                     max_file_timestamp_ns=4_000,
            ...                 )
            ...             ],
            ...             data_range=(0, 80),
            ...             anchor_ns=1_785_974_400_000_000_000,
            ...             representations=[from_file],
            ...         ),
            ...     ],
            ... )
        """
        if not topics:
            return BatchResponse[experimental_topics.Topic](responses=[])

        registered = self.__roboto_client.post(
            f"v1/files/id/{self.file_id}/topics",
            data=DeclareTopicsRequest(topics=list(topics)),
        ).to_record(BatchResponse[TopicIdentityRecord])
        return registered.map_data(
            lambda record: experimental_topics.Topic.from_record(record, roboto_client=self.__roboto_client)
        )

    def delete(self) -> None:
        """Delete this file from the Roboto platform.

        Permanently removes the file and all its associated data, including topics
        and metadata. This operation cannot be undone.

        For files that were imported from customer S3 buckets (read-only BYOB
        integrations), this method does not delete the file content from S3. It
        only removes the metadata and references within the Roboto platform.

        Raises:
            RobotoNotFoundException: File does not exist or has already been deleted.
            RobotoUnauthorizedException: Caller lacks permission to delete the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> file.delete()
            # File is now permanently deleted
        """
        self.__roboto_client.delete(f"/v1/files/{self.file_id}")

    def download(
        self,
        local_path: pathlib.Path,
        print_progress: bool = True,
    ):
        """Download this file to a local path.

        Downloads the file content from cloud storage to the specified local path.
        The parent directories are created automatically if they don't exist.

        For a link, downloads the version of the target file that the link pins.

        Args:
            local_path: Local filesystem path where the file should be saved.
            print_progress: Whether to show a progress bar during download.

        Raises:
            RobotoNotFoundException: This file is a link whose target, at the pinned version, no longer exists.
            RobotoUnauthorizedException: Caller lacks permission to download the file, or a link's target.
            FileNotFoundError: File content is not available in storage.

        Examples:
            >>> import pathlib
            >>> file = File.from_id("file_abc123")
            >>> local_path = pathlib.Path("/tmp/downloaded_file.bag")
            >>> file.download(local_path)
            >>> print(f"Downloaded to {local_path}")
        """
        source = self._resolve_link()
        progress_monitor = (
            TqdmProgressMonitor(
                total=source.record.size,
                desc=f"Downloading {self.relative_path}",
            )
            if print_progress
            else NoopProgressMonitor()
        )

        with progress_monitor:
            self.__file_service.download(
                files=[
                    {
                        "bucket_name": source.record.bucket,
                        "source_uri": source.record.uri,
                        "destination_path": local_path,
                    }
                ],
                # The object lives under the source's association, so read credentials for it come from there.
                association=source.association,
                caller_org_id=source.org_id,
                on_progress=progress_monitor.update,
            )

    def get_signed_url(
        self,
        override_content_type: typing.Optional[str] = None,
        override_content_disposition: typing.Optional[str] = None,
    ) -> str:
        """Generate a signed URL for direct access to this file.

        Creates a time-limited URL that allows direct access to the file content
        without requiring Roboto authentication. Useful for sharing files or
        integrating with external systems.

        Args:
            override_content_type: Custom MIME type to set in the response headers.
            override_content_disposition: Custom content disposition header value
                (e.g., "attachment; filename=myfile.bag").

        For a link, the URL is for the version of the target file that the link pins.

        Returns:
            Signed URL string that provides temporary access to the file.

        Raises:
            RobotoNotFoundException: This file is a link whose target, at the pinned version, no longer exists.
            RobotoUnauthorizedException: Caller lacks permission to access the file, or a link's target.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> url = file.get_signed_url()
            >>> print(f"Direct access URL: {url}")

            >>> # Force download with custom filename
            >>> download_url = file.get_signed_url(override_content_disposition="attachment; filename=data.bag")
        """
        query_params: dict[str, str] = {}

        if override_content_disposition:
            query_params["override_content_disposition"] = override_content_disposition

        if override_content_type:
            query_params["override_content_type"] = override_content_type

        source = self._resolve_link()
        if source is not self:
            query_params["version_id"] = str(source.version)

        res = self.__roboto_client.get(
            f"v1/files/{source.file_id}/signed-url",
            query=query_params,
            owner_org_id=source.org_id,
        )
        return res.to_dict(json_path=["data", "url"])

    def get_topic(self, topic_name: str) -> Topic:
        """Get a specific topic from this file by name.

        Retrieves a topic with the specified name that is associated with this file.
        Topics contain the structured data extracted from the file during ingestion.

        Args:
            topic_name: Name of the topic to retrieve (e.g., "/camera/image", "/imu/data").

        Returns:
            Topic instance for the specified topic name.

        Raises:
            RobotoNotFoundException: Topic with the given name does not exist in this file.
            RobotoUnauthorizedException: Caller lacks permission to access the topic.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> camera_topic = file.get_topic("/camera/image")
            >>> print(f"Topic schema: {camera_topic.schema}")

            >>> # Access topic data
            >>> for record in camera_topic.get_data():
            ...     print(f"Timestamp: {record['timestamp']}")
        """
        return Topic.from_name_and_file(
            topic_name=topic_name,
            file_id=self.file_id,
            owner_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def get_topics(
        self,
        include: typing.Optional[collections.abc.Sequence[str]] = None,
        exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> collections.abc.Generator["Topic", None, None]:
        """Get all topics associated with this file, with optional filtering.

        Retrieves all topics that were extracted from this file during ingestion.
        Topics can be filtered by name using include/exclude patterns.

        Args:
            include: If provided, only topics with names in this sequence are yielded.
            exclude: If provided, topics with names in this sequence are skipped.

        Yields:
            Topic instances associated with this file, filtered according to the parameters.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> for topic in file.get_topics():
            ...     print(f"Topic: {topic.name}")
            Topic: /camera/image
            Topic: /imu/data
            Topic: /gps/fix

            >>> # Only get camera topics
            >>> camera_topics = list(file.get_topics(include=["/camera/image", "/camera/info"]))
            >>> print(f"Found {len(camera_topics)} camera topics")

            >>> # Exclude diagnostic topics
            >>> data_topics = list(file.get_topics(exclude=["/diagnostics"]))
        """
        for topic in Topic.get_by_file(
            owner_org_id=self.org_id,
            file_id=self.file_id,
            roboto_client=self.__roboto_client,
        ):
            if include is not None and topic.name not in include:
                continue

            if exclude is not None and topic.name in exclude:
                continue

            yield topic

    def mark_ingested(self) -> File:
        """Mark this file as fully ingested and ready for post-processing.

        Updates the file's ingestion status to indicate that all data has been
        successfully processed and extracted into topics. This enables triggers
        and other automated workflows that depend on complete ingestion.

        Returns:
            Updated File instance with ingestion status set to Ingested.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the file.

        Notes:
            This method is typically called by ingestion actions after they have
            successfully processed all data in the file. Once marked as ingested,
            the file becomes eligible for additional post-processing actions.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> print(file.ingestion_status)
            IngestionStatus.NotIngested
            >>> updated_file = file.mark_ingested()
            >>> print(updated_file.ingestion_status)
            IngestionStatus.Ingested
        """
        return self.update(ingestion_complete=True)

    def put_metadata(self, metadata: dict[str, typing.Any]) -> File:
        """Add or update metadata fields for this file.

        Adds new metadata fields or updates existing ones. Existing fields not
        specified in the metadata dict are preserved.

        Args:
            metadata: Dictionary of metadata key-value pairs to add or update.

        Returns:
            Updated File instance with the new metadata.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> updated_file = file.put_metadata(
            ...     {"vehicle_id": "vehicle_001", "session_type": "highway_driving", "weather": "sunny"}
            ... )
            >>> print(updated_file.metadata["vehicle_id"])
            'vehicle_001'
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> File:
        """Add or update tags for this file.

        Replaces the file's current tags with the provided list. To add tags
        while preserving existing ones, retrieve current tags first and combine them.

        Args:
            tags: List of tag strings to set on the file.

        Returns:
            Updated File instance with the new tags.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> updated_file = file.put_tags(["sensor-data", "highway", "sunny"])
            >>> print(updated_file.tags)
            ['sensor-data', 'highway', 'sunny']
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> File:
        """Refresh this file instance with the latest data from the platform.

        Fetches the current state of the file from the Roboto platform and updates
        this instance's data. Useful when the file may have been modified by other
        processes or users.

        Returns:
            This File instance with refreshed data.

        Raises:
            RobotoNotFoundException: File no longer exists.
            RobotoUnauthorizedException: Caller lacks permission to access the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> # File may have been updated by another process
            >>> refreshed_file = file.refresh()
            >>> print(f"Current version: {refreshed_file.version}")
        """
        self.__record = self.__roboto_client.get(f"v1/files/record/{self.file_id}").to_record(FileRecord)
        return self

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:
        """Rename this file to a new path within its dataset, device, or org.

        Changes the relative path of the file among the files of its association. This updates
        the file's location identifier but does not move the actual file content.

        Args:
            file_id: File ID (currently unused, kept for API compatibility).
            new_path: New relative path for the file, relative to the root of its association's files.

        Returns:
            Updated FileRecord with the new path.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to rename the file.
            RobotoInvalidRequestException: New path is invalid or conflicts with existing file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> print(file.relative_path)
            'old_logs/session1.bag'
            >>> updated_record = file.rename_file("file_abc123", "logs/session1.bag")
            >>> print(updated_record.relative_path)
            'logs/session1.bag'
        """
        response = self.__roboto_client.put(
            f"v1/files/{self.file_id}/rename",
            data=RenameFileRequest(
                association_id=self.__record.association_id,
                new_path=new_path,
            ),
        )

        return response.to_record(FileRecord)

    def set_device_id(self, device_id: str) -> File:
        """Set the device ID for this file.

        Args:
            device_id: The device ID to set for this file.

        Returns:
            Updated File instance with the new device ID.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the file.
            RobotoDeviceNotFoundException: The specified device ID does not exist.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> updated_file = file.set_device_id("device_xyz789")
        """
        return self.update(device_id=device_id)

    @experimental
    def set_representations(self, topics: collections.abc.Sequence[TopicRepresentations]) -> None:
        """Replace the representations the named topics' data on this File is read from.

        This File is the one the topics were declared on, through :py:meth:`declare_topics` or a Session. Each
        topic listed ends up with exactly the representations listed, over the part of this File its entry's
        ``data_range`` names; its other representations there are removed, whether they cover the whole topic
        or one field of it. Topics and slices not listed keep theirs. Nothing else about the topics changes:
        their schemas, timeline sources, bounds, anchors and slices stay as declared, and so do the time bounds
        of every Session holding this File, which do not depend on which files the data is read from.

        Use it for what redeclaring a topic cannot do:

        1. Remove a representation.
        2. Replace a representation with one that names another file and differs from it in what it covers,
           its storage format, its content format or its transformations. Those four identify a representation,
           as :py:class:`~roboto.experimental.ingest.RepresentationDeclaration` describes,
           so declaring the new one adds it beside the first.
        3. Stop a topic being read at all, by listing no representations for it.

        The platform checks every entry before writing any, and one refused entry refuses the whole call.

        Args:
            topics: One entry per topic and slice, at most
                :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`; split a larger set
                across several calls. An empty sequence returns without contacting the platform.

        Raises:
            pydantic.ValidationError: ``topics`` is longer than the cap, lists one topic and slice twice, or
                lists representations naming one file in two storage formats. Raised before any request is made.
                The rules for one topic's own representations are enforced earlier, when the caller builds its
                :py:class:`~roboto.experimental.ingest.TopicRepresentations`.
            RobotoNotFoundException: This File does not exist, a topic is not declared on it, an entry's
                ``data_range`` is not one the topic is declared over on it, or a representation names a file that
                does not exist in this File's org or whose status is not
                :py:attr:`~roboto.domain.files.FileStatus.Available`. Nothing is written.
            RobotoInvalidRequestException: A topic declared with a timeline source other than
                :py:class:`~roboto.experimental.ingest.SchemaFieldSource` (MCAP log or publish time, MP4
                presentation time) would get a ``PARQUET`` representation, a topic declared over a ``data_range``
                would be left with a representation that cannot be read by row position and none that can
                covering the same fields, as
                :py:attr:`~roboto.experimental.ingest.RepresentationDeclaration.transformations` describes,
                or a representation's ``field_path`` names no field of the schema the topic is declared under on
                this File. Nothing is written.
            RobotoUnauthorizedException: The caller cannot edit this File or a file a listed representation names.

        Examples:
            Replace a camera topic's representation re-encoded as JPEG with one downsampled and re-encoded as
            PNG, keeping the untransformed one that names the recording, and stop reading a debug topic at all:

            >>> from roboto.domain.files import File
            >>> from roboto.domain.topics import RepresentationStorageFormat
            >>> from roboto.experimental.ingest import RepresentationDeclaration, TopicRepresentations
            >>> recording = File.from_id("fl_recording_0412_mcap")
            >>> recording.set_representations(
            ...     [
            ...         TopicRepresentations(
            ...             topic_name="/camera/front/image_raw",
            ...             representations=[
            ...                 RepresentationDeclaration(
            ...                     file_id=recording.file_id,
            ...                     storage_format=RepresentationStorageFormat.MCAP,
            ...                 ),
            ...                 RepresentationDeclaration(
            ...                     file_id="fl_front_png",
            ...                     storage_format=RepresentationStorageFormat.MCAP,
            ...                     content_format="png",
            ...                     transformations=["downsample:0.5", "encode:png"],
            ...                 ),
            ...             ],
            ...         ),
            ...         TopicRepresentations(topic_name="/debug/raw_dump", representations=[]),
            ...     ]
            ... )
        """
        if not topics:
            return

        self.__roboto_client.put(
            f"v1/files/id/{self.file_id}/representations",
            data=SetRepresentationsRequest(topics=list(topics)),
        )

    @experimental
    def set_timeline_offset(
        self,
        offset: Time,
        *,
        topic: typing.Optional[Topic] = None,
        topic_name: typing.Optional[str] = None,
        timeline_source: typing.Optional[TimelineSourceRecord] = None,
        timeline_source_name: typing.Optional[str] = None,
    ) -> list[TimelineExtentRecord]:
        """Calibrate this file's timeline to Unix-epoch wall-clock, optionally scoped to a topic and/or source.

        Contract:

        1. The offset, in nanoseconds, is added to stored partition time to produce session wall-clock:
           ``session_time_ns = stored_time_ns + offset_ns``. An offset given as an instant, such as a
           ``datetime``, is the nanoseconds since the Unix epoch at which stored time 0 occurred.
        2. ``topic`` / ``topic_name`` scopes the update to a single topic in this file;
           ``timeline_source`` / ``timeline_source_name`` scopes it to a single source.
           With no selectors, the offset applies to every timeline on the file.

        Use :meth:`set_timeline_offsets` to send several offsets in one atomic request.

        Args:
            offset: Offset to apply: an ``int`` of nanoseconds, or any other :py:data:`~roboto.time.Time`, read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime`` or ISO 8601 string is that
                instant; a ``float``, ``Decimal``, or numeric string is seconds). Must not be negative, and must fit in
                a signed 64-bit integer of nanoseconds.
            topic: Topic to scope the update to. Mutually exclusive with ``topic_name``.
            topic_name: Topic name to scope the update to (e.g. ``"/imu/raw"``). Mutually exclusive with ``topic``.
            timeline_source: Source record to scope the update to. Mutually exclusive with ``timeline_source_name``.
            timeline_source_name: Source name to scope the update to (e.g. ``"header.stamp"``). Mutually exclusive
                with ``timeline_source``.

        Returns:
            The updated :class:`TimelineExtentRecord` objects returned by the server.

        Raises:
            TypeError: ``offset`` is not one of the :py:data:`~roboto.time.Time` types.
            ValueError: ``offset`` is a boolean, a negative number (an ``int``, ``float``, ``Decimal``, or numeric
                string), or a string that is neither seconds nor ISO 8601; or both of a mutually exclusive pair of
                selectors are given. Raised before any request is made.
            OverflowError: ``offset`` is an infinite ``float``, ``Decimal``, or string, such as ``"inf"``. Raised
                before any request is made.
            pydantic.ValidationError: ``offset`` converts to a negative number of nanoseconds, or to more than a signed
                64-bit integer holds. A subclass of ``ValueError``, raised before any request is made.
            RobotoUnauthorizedException: The caller cannot edit this file.
            RobotoNotFoundException: The file carries no timeline data, or the selectors match none of it.
            RobotoInvalidRequestException: The offset would place the data it reaches, or a session time range
                declared over that data, before the Unix epoch or past the largest storable Unix-epoch nanosecond
                value. Nothing is written.

        Examples:
            Apply a file-wide offset:

            >>> file = File.from_id("file_abc123")
            >>> file.set_timeline_offset(1_700_000_000_000_000_000)

            Apply the same offset as a ``datetime``, the instant stored time 0 occurred:

            >>> import datetime
            >>> file.set_timeline_offset(datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.timezone.utc))

            Apply an offset to a single topic by name:

            >>> file.set_timeline_offset(1_700_000_000_000_000_000, topic_name="/imu/raw")

            Apply an offset to a specific source on a topic:

            >>> file.set_timeline_offset(
            ...     500_000_000,
            ...     topic_name="data",
            ...     timeline_source_name="ts",
            ... )
        """
        if topic is not None and topic_name is not None:
            raise ValueError("Specify at most one of topic, topic_name.")
        if timeline_source is not None and timeline_source_name is not None:
            raise ValueError("Specify at most one of timeline_source, timeline_source_name.")

        entry = TimelineOffsetEntry(
            unix_epoch_offset_ns=to_epoch_nanoseconds(offset),
            topic_name=topic.topic_name if topic is not None else topic_name,
            timeline_source_id=(timeline_source.timeline_source_id if timeline_source is not None else None),
            timeline_source_name=timeline_source_name,
        )
        return self.set_timeline_offsets([entry])

    @experimental
    def set_timeline_offsets(
        self,
        offsets: list[TimelineOffsetEntry],
    ) -> list[TimelineExtentRecord]:
        """Apply multiple timeline offsets to this file in one atomic request.

        Each entry carries a ``unix_epoch_offset_ns`` and optional selectors (``topic_name``,
        ``timeline_source_id``, ``timeline_source_name``) that narrow where the offset is applied.
        An entry with no selectors targets every timeline on the file.

        Use :meth:`set_timeline_offset` for the single-offset convenience form.

        Args:
            offsets: Offset entries to apply, each with its own selectors.

        Returns:
            The updated :class:`TimelineExtentRecord` objects returned by the server.

        Raises:
            pydantic.ValidationError: ``offsets`` is empty. Raised before any request is made.
            RobotoUnauthorizedException: The caller cannot edit this file.
            RobotoNotFoundException: The file carries no timeline data, or the selectors of every entry together
                match none of it.
            RobotoInvalidRequestException: An entry's offset would place the data it reaches, or a session time range
                declared over that data, before the Unix epoch or past the largest storable Unix-epoch nanosecond
                value. The whole request is refused and nothing is written.

        Examples:
            Apply per-topic offsets in a single request:

            >>> from roboto.domain.topics import TimelineOffsetEntry
            >>> file = File.from_id("file_abc123")
            >>> file.set_timeline_offsets(
            ...     [
            ...         TimelineOffsetEntry(unix_epoch_offset_ns=1_700_000_000_000_000_000, topic_name="/imu/raw"),
            ...         TimelineOffsetEntry(unix_epoch_offset_ns=1_700_000_000_000_000_000, topic_name="/camera/image"),
            ...     ]
            ... )
        """
        request = SetTimelineOffsetsRequest(offsets=offsets)
        return self.__roboto_client.post(
            f"v1/files/id/{self.file_id}/timeline-offsets",
            data=request,
        ).to_record_list(TimelineExtentRecord)

    def to_association(self) -> Association:
        """Convert this file to an Association reference.

        Creates an Association object that can be used to reference this file
        in other contexts, such as when creating collections or specifying
        action inputs.

        Returns:
            Association object referencing this file and its current version.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> association = file.to_association()
            >>> print(f"Association: {association.association_type}:{association.association_id}")
            Association: file:file_abc123
        """
        return Association.file(self.file_id, self.version)

    def to_dict(self) -> dict[str, typing.Any]:
        """Convert this file to a dictionary representation.

        Returns the file's data as a JSON-serializable dictionary containing
        all file attributes and metadata.

        Returns:
            Dictionary representation of the file data.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> file_dict = file.to_dict()
            >>> print(file_dict["relative_path"])
            'logs/session1.bag'
            >>> print(file_dict["metadata"])
            {'vehicle_id': 'vehicle_001', 'session_type': 'highway'}
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        ingestion_complete: typing.Union[typing.Literal[True], NotSetType] = NotSet,
        device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
    ) -> File:
        """Update this file's properties.

        Updates various properties of the file including description, metadata,
        and ingestion status. Only specified parameters are updated; others
        remain unchanged.

        Args:
            description: New description for the file. Use NotSet to leave unchanged.
            metadata_changeset: Metadata changes to apply (add, update, or remove fields/tags).
                Use NotSet to leave metadata unchanged.
            ingestion_complete: Set to True to mark the file as fully ingested.
                Use NotSet to leave ingestion status unchanged.
            device_id: New device ID for the file. Use NotSet to leave unchanged.

        Returns:
            Updated File instance with the new properties.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> updated_file = file.update(description="Updated sensor data from highway test")
            >>> print(updated_file.description)
            'Updated sensor data from highway test'

            >>> # Update metadata and mark as ingested
            >>> from roboto.updates import MetadataChangeset
            >>> changeset = MetadataChangeset(put_fields={"processed": True})
            >>> updated_file = file.update(metadata_changeset=changeset, ingestion_complete=True)
        """
        request = remove_not_set(
            UpdateFileRecordRequest(
                description=description,
                metadata_changeset=metadata_changeset,
                ingestion_complete=ingestion_complete,
                device_id=device_id,
            )
        )
        self.__record = self.__roboto_client.put(f"v1/files/record/{self.file_id}", data=request).to_record(FileRecord)
        return self

    def _resolve_link(self) -> File:
        """Return this file, or for a link, its target at the pinned version.

        Follows a link by parsing its ``roboto://`` uri, which :py:class:`FileRecord` also parses, to name the target
        when it refuses a link's bucket or key. ``FileSystem.download_files`` and ``ActionInputResolver`` call it
        from outside the class, so it takes one leading underscore rather than a name-mangled two.

        Raises:
            RobotoNotFoundException: This file is a link whose target, at the pinned version, no longer exists.
        """
        if not self.is_link:
            return self
        pointer = RobotoUri.parse(self.__record.uri)
        try:
            return File.from_id(pointer.id, version_id=pointer.version, roboto_client=self.__roboto_client)
        except RobotoNotFoundException:
            raise RobotoNotFoundException(
                f"'{self.relative_path}' is a link to {self.__record.uri}, which could not be found"
            ) from None
