# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import pathlib
import typing
import urllib.parse

import boto3
import botocore.config
import botocore.credentials
import botocore.session

from ...ai.summary import (
    AISummary,
    AISummaryStatus,
)
from ...association import Association
from ...exceptions import (
    RobotoFailedToGenerateException,
)
from ...http import BatchRequest, RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...updates import MetadataChangeset
from ...waiters import Interval, wait_for
from ..topics import Topic
from .file_creds import (
    CredentialProvider,
    FileCredentialsHelper,
)
from .operations import (
    ImportFileRequest,
    RenameFileRequest,
    UpdateFileRecordRequest,
)
from .progress import (
    NoopProgressMonitorFactory,
    ProgressMonitorFactory,
)
from .record import FileRecord, IngestionStatus


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

    __record: FileRecord
    __roboto_client: RobotoClient

    @staticmethod
    def construct_s3_obj_arn(bucket: str, key: str, partition: str = "aws") -> str:
        """Construct an S3 object ARN from bucket and key components.

        Args:
            bucket: S3 bucket name.
            key: S3 object key (path within the bucket).
            partition: AWS partition name, defaults to "aws".

        Returns:
            Complete S3 object ARN string.

        Examples:
            >>> arn = File.construct_s3_obj_arn("my-bucket", "path/to/file.bag")
            >>> print(arn)
            'arn:aws:s3:::my-bucket/path/to/file.bag'
        """
        return f"arn:{partition}:s3:::{bucket}/{key}"

    @staticmethod
    def construct_s3_obj_uri(
        bucket: str, key: str, version: typing.Optional[str] = None
    ) -> str:
        """Construct an S3 object URI from bucket, key, and optional version.

        Args:
            bucket: S3 bucket name.
            key: S3 object key (path within the bucket).
            version: Optional S3 object version ID.

        Returns:
            Complete S3 object URI string.

        Examples:
            >>> uri = File.construct_s3_obj_uri("my-bucket", "path/to/file.bag")
            >>> print(uri)
            's3://my-bucket/path/to/file.bag'

            >>> versioned_uri = File.construct_s3_obj_uri("my-bucket", "path/to/file.bag", "abc123")
            >>> print(versioned_uri)
            's3://my-bucket/path/to/file.bag?versionId=abc123'
        """
        base_uri = f"s3://{bucket}/{key}"
        if version:
            base_uri += f"?versionId={version}"
        return base_uri

    @staticmethod
    def generate_s3_client(
        credential_provider: CredentialProvider, tcp_keepalive: bool = True
    ):
        """Generate a configured S3 client using Roboto credentials.

        Creates an S3 client with refreshable credentials obtained from the provided
        credential provider. The client is configured with the appropriate region
        and connection settings.

        Args:
            credential_provider: Function that returns AWS credentials for S3 access.
            tcp_keepalive: Whether to enable TCP keepalive for the S3 connection.

        Returns:
            Configured boto3 S3 client instance.

        Examples:
            >>> from roboto.domain.files.file_creds import FileCredentialsHelper
            >>> helper = FileCredentialsHelper(roboto_client)
            >>> cred_provider = helper.get_dataset_download_creds_provider("ds_123", "bucket")
            >>> s3_client = File.generate_s3_client(cred_provider)
        """
        creds = credential_provider()
        refreshable_credentials = (
            botocore.credentials.RefreshableCredentials.create_from_metadata(
                metadata=creds,
                refresh_using=credential_provider,
                method="roboto-api",
            )
        )
        botocore_session = botocore.session.get_session()
        botocore_session._credentials = refreshable_credentials
        botocore_session.set_config_variable("region", creds["region"])
        session = boto3.Session(botocore_session=botocore_session)

        return session.client(
            "s3", config=botocore.config.Config(tcp_keepalive=tcp_keepalive)
        )

    @classmethod
    def from_id(
        cls,
        file_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "File":
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
    ) -> "File":
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
    ) -> collections.abc.Sequence["File"]:
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
            ...         size=1024000
            ...     ),
            ...     ImportFileRequest(
            ...         dataset_id="ds_abc123",
            ...         relative_path="logs/session2.bag",
            ...         uri="s3://my-bucket/data/session2.bag",
            ...         size=2048000
            ...     )
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
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "File":
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
            ...     dataset_id="ds_abc123",
            ...     relative_path="logs/session1.bag",
            ...     uri="s3://my-bucket/data/session1.bag"
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
            ...     metadata={"sensor_type": "Velodyne", "resolution": "high"}
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
        )
        record = roboto_client.post("v1/files/import", data=request).to_record(
            FileRecord
        )
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator["File", None, None]:
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
            ...     condition=Condition(
            ...         field="tags",
            ...         comparator=Comparator.Contains,
            ...         value="sensor-data"
            ...     ))
            >>> for file in File.query(spec):
            ...     print(f"Found file: {file.relative_path}")
            Found file: logs/sensors_2024_01_01.bag
            Found file: logs/sensors_2024_01_02.bag

            >>> # Query with metadata filter
            >>> spec = QuerySpecification(
            ...     condition=Condition(
            ...         field="metadata.vehicle_id",
            ...         comparator=Comparator.Equals,
            ...         value="vehicle_001"
            ...     ))
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
            msg = (
                "are not known attributes of File"
                if plural
                else "is not a known attribute of File"
            )
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
        self, record: FileRecord, roboto_client: typing.Optional[RobotoClient] = None
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
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
    def dataset_id(self) -> str:
        """Identifier of the dataset that contains this file.

        Returns the unique identifier of the dataset that this file belongs to.
        Files are always associated with exactly one dataset.
        """
        return self.__record.association_id

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of this file.

        Returns the optional description text that provides details about the file's
        contents, purpose, or context. Can be None if no description was provided.
        """
        return self.__record.description

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
        """Path of this file relative to its dataset root.

        Returns the file path within the dataset, using forward slashes as
        separators regardless of the operating system. This path uniquely
        identifies the file within its dataset.
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
        credential_provider: typing.Optional[CredentialProvider] = None,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
    ):
        """Download this file to a local path.

        Downloads the file content from cloud storage to the specified local path.
        The parent directories are created automatically if they don't exist.

        Args:
            local_path: Local filesystem path where the file should be saved.
            credential_provider: Custom credentials for accessing the file storage.
                If None, uses default credentials for the file's dataset.
            progress_monitor_factory: Factory for creating progress monitors to track
                download progress. Defaults to no progress monitoring.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to download the file.
            FileNotFoundError: File content is not available in storage.

        Examples:
            >>> import pathlib
            >>> file = File.from_id("file_abc123")
            >>> local_path = pathlib.Path("/tmp/downloaded_file.bag")
            >>> file.download(local_path)
            >>> print(f"Downloaded to {local_path}")

            >>> # Download with progress monitoring
            >>> from roboto.domain.files.progress import TqdmProgressMonitorFactory
            >>> progress_factory = TqdmProgressMonitorFactory()
            >>> file.download(local_path, progress_monitor_factory=progress_factory)
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)

        defaulted_credential_provider: CredentialProvider
        if credential_provider is None:
            defaulted_credential_provider = FileCredentialsHelper(
                self.__roboto_client
            ).get_dataset_download_creds_provider(self.dataset_id, self.record.bucket)
        else:
            defaulted_credential_provider = credential_provider

        s3_client = File.generate_s3_client(defaulted_credential_provider)

        res = s3_client.head_object(Bucket=self.record.bucket, Key=self.record.key)
        download_bytes = int(res.get("ContentLength", 0))

        source = self.record.key.replace(f"{self.record.org_id}/datasets/", "")

        progress_monitor = progress_monitor_factory.download_monitor(
            source=source, size=download_bytes
        )
        try:
            s3_client.download_file(
                Bucket=self.record.bucket,
                Key=self.record.key,
                Filename=str(local_path),
                Callback=progress_monitor.update,
            )
        finally:
            progress_monitor.close()

    def generate_summary(self) -> AISummary:
        """
        Generate a new AI generated summary of this file. If a summary already exists, it will be overwritten.
        The results of this call are persisted and can be retrieved with `get_summary()`.

        Returns: An AISummary object containing the summary text and the creation timestamp.

        Example:
            >>> from roboto import File
            >>> fl = File.from_id("fl_abc123")
            >>> summary = fl.generate_summary()
            >>> print(summary.text)
            This file contains ...
        """
        return self.__roboto_client.post(f"v1/files/{self.file_id}/summary").to_record(
            AISummary
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

        Returns:
            Signed URL string that provides temporary access to the file.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to access the file.

        Examples:
            >>> file = File.from_id("file_abc123")
            >>> url = file.get_signed_url()
            >>> print(f"Direct access URL: {url}")

            >>> # Force download with custom filename
            >>> download_url = file.get_signed_url(
            ...     override_content_disposition="attachment; filename=data.bag"
            ... )
        """
        query_params: dict[str, str] = {}

        if override_content_disposition:
            query_params["override_content_disposition"] = override_content_disposition

        if override_content_type:
            query_params["override_content_type"] = override_content_type

        res = self.__roboto_client.get(
            f"v1/files/{self.file_id}/signed-url",
            query=query_params,
            owner_org_id=self.org_id,
        )
        return res.to_dict(json_path=["data", "url"])

    def get_summary(self) -> AISummary:
        """
        Get the latest AI generated summary of this file. If no summary exists, one will be generated, equivalent
        to a call to `generate_summary()`.

        After the first summary for a file is generated, it will be persisted and returned by this method until
        `generate_summary()` is explicitly called again. This applies even if the file or its topics/metadata change.

        Returns: An AISummary object containing the summary text and the creation timestamp.

        Example:
            >>> from roboto import File
            >>> fl = File.from_id("fl_abc123")
            >>> summary = fl.get_summary()
            >>> print(summary.text)
            This file contains ...
        """
        return self.__roboto_client.get(f"v1/files/{self.file_id}/summary").to_record(
            AISummary
        )

    def get_summary_sync(
        self,
        timeout: float = 60,  # 1 minute in seconds
        poll_interval: Interval = 2,
    ) -> AISummary:
        """
        Poll the summary endpoint until a summary's status is COMPLETED, or raise an exception if the status is FAILED
        or the configurable timeout is reached.

        This method will call `get_summary()` repeatedly until the summary reaches a terminal status.
        If no summary exists when this method is called, one will be generated automatically.

        Args:
            timeout: The maximum amount of time, in seconds, to wait for the summary to complete. Defaults to 1 minute.
            poll_interval: The amount of time, in seconds, to wait between polling iterations. Defaults to 2 seconds.

        Returns: An AI Summary object containing a full LLM summary of the file.

        Raises:
            RobotoFailedToGenerateException: If the summary status becomes FAILED.
            TimeoutError: If the timeout is reached before the summary completes.

        Example:
            >>> from roboto import File
            >>> fl = File.from_id("fl_abc123")
            >>> summary = fl.get_summary_sync(timeout=60)
            >>> print(summary.text)
            This file contains ...
        """

        def _check_summary_completion() -> bool:
            summary = self.get_summary()

            if summary.status == AISummaryStatus.Failed:
                raise RobotoFailedToGenerateException(
                    f"Summary generation failed for file {self.file_id}"
                )

            return summary.status == AISummaryStatus.Complete

        wait_for(
            _check_summary_completion,
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for summary completion for file '{self.file_id}'",
        )

        return self.get_summary()

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

    def mark_ingested(self) -> "File":
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

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "File":
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
            >>> updated_file = file.put_metadata({
            ...     "vehicle_id": "vehicle_001",
            ...     "session_type": "highway_driving",
            ...     "weather": "sunny"
            ... })
            >>> print(updated_file.metadata["vehicle_id"])
            'vehicle_001'
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "File":
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

    def refresh(self) -> "File":
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
        self.__record = self.__roboto_client.get(
            f"v1/files/record/{self.file_id}"
        ).to_record(FileRecord)
        return self

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:
        """Rename this file to a new path within its dataset.

        Changes the relative path of the file within its dataset. This updates
        the file's location identifier but does not move the actual file content.

        Args:
            file_id: File ID (currently unused, kept for API compatibility).
            new_path: New relative path for the file within the dataset.

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
                association_id=self.dataset_id,
                new_path=new_path,
            ),
        )

        return response.to_record(FileRecord)

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
    ) -> "File":
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
            >>> updated_file = file.update(
            ...     metadata_changeset=changeset,
            ...     ingestion_complete=True
            ... )
        """
        request = remove_not_set(
            UpdateFileRecordRequest(
                description=description,
                metadata_changeset=metadata_changeset,
                ingestion_complete=ingestion_complete,
            )
        )
        self.__record = self.__roboto_client.put(
            f"v1/files/record/{self.file_id}", data=request
        ).to_record(FileRecord)
        return self
