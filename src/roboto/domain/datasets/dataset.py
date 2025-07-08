# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import functools
import importlib.metadata
import math
import os
import pathlib
import threading
import typing

import pathspec

from ...ai.summary import (
    AISummary,
    AISummaryStatus,
)
from ...association import Association
from ...env import RobotoEnv
from ...exceptions import (
    RobotoFailedToGenerateException,
)
from ...http import PaginatedList, RobotoClient
from ...logging import default_logger
from ...paths import excludespec_from_patterns
from ...query import QuerySpecification
from ...updates import (
    MetadataChangeset,
    StrSequence,
    UpdateCondition,
)
from ...waiters import Interval, wait_for
from ..files import (
    DirectoryRecord,
    File,
    FileRecord,
)
from ..files.file_creds import (
    FileCredentialsHelper,
)
from ..files.file_service import FileService
from ..files.progress import (
    NoopProgressMonitorFactory,
    ProgressMonitorFactory,
    TqdmProgressMonitorFactory,
)
from ..topics import Topic
from .operations import (
    BeginManifestTransactionRequest,
    BeginManifestTransactionResponse,
    CreateDatasetIfNotExistsRequest,
    CreateDatasetRequest,
    CreateDirectoryRequest,
    QueryDatasetFilesRequest,
    RenameDirectoryRequest,
    ReportTransactionProgressRequest,
    UpdateDatasetRequest,
)
from .record import DatasetRecord

logger = default_logger()


MAX_FILES_PER_MANIFEST = 500


class Dataset:
    """Represents a dataset within the Roboto platform.

    A dataset is a logical container for files organized in a directory structure.
    Datasets are the primary organizational unit in Roboto, typically containing
    files from a single robot activity such as a drone flight, autonomous vehicle
    mission, or sensor data collection session. However, datasets are versatile
    enough to serve as a general-purpose assembly of files.

    Datasets provide functionality for:

    - File upload and download operations
    - Metadata and tag management
    - File organization and directory operations
    - Topic data access and analysis
    - AI-powered content summarization
    - Integration with automated workflows and triggers

    Files within a dataset can be processed by actions, visualized in the web interface,
    and searched using the query system. Datasets inherit access permissions from
    their organization and can be shared with other users and systems.

    The Dataset class serves as the primary interface for dataset operations in the
    Roboto SDK, providing methods for file management, metadata operations, and
    content analysis.
    """

    UPLOAD_REPORTING_BATCH_COUNT: typing.ClassVar[int] = 10
    """
    Number of batches to break a large upload into for the purpose of reporting progress.
    """
    UPLOAD_REPORTING_MIN_BATCH_SIZE: typing.ClassVar[int] = 10
    """
    Minimum number of files that must be uploaded before reporting progress.
    """

    __roboto_client: RobotoClient
    __record: DatasetRecord
    __file_service: FileService
    __file_creds_helper: FileCredentialsHelper
    __transaction_completed_unreported_items: dict[str, set[str]]
    __transaction_completed_mutex: threading.Lock

    @classmethod
    def create(
        cls,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        name: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Dataset":
        """Create a new dataset in the Roboto platform.

        Creates a new dataset with the specified properties and returns a Dataset
        instance for interacting with it. The dataset will be created in the caller's
        organization unless a different organization is specified.

        Args:
            description: Optional human-readable description of the dataset.
            metadata: Optional key-value metadata pairs to associate with the dataset.
            name: Optional short name for the dataset (max 120 characters).
            tags: Optional list of tags for dataset discovery and organization.
            caller_org_id: Organization ID to create the dataset in. Required for multi-org users.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Dataset instance representing the newly created dataset.

        Raises:
            RobotoInvalidRequestException: Invalid dataset parameters.
            RobotoUnauthorizedException: Caller lacks permission to create datasets.

        Examples:
            >>> dataset = Dataset.create(
            ...     name="Highway Test Session",
            ...     description="Autonomous vehicle highway driving test data",
            ...     tags=["highway", "autonomous", "test"],
            ...     metadata={"vehicle_id": "vehicle_001", "test_type": "highway"}
            ... )
            >>> print(dataset.dataset_id)
            ds_abc123

            >>> # Create minimal dataset
            >>> dataset = Dataset.create()
            >>> print(f"Created dataset: {dataset.dataset_id}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDatasetRequest(
            description=description, metadata=metadata or {}, name=name, tags=tags or []
        )
        record = roboto_client.post(
            "v1/datasets", data=request, caller_org_id=caller_org_id
        ).to_record(DatasetRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def create_if_not_exists(
        cls,
        match_roboql_query: str,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        name: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Dataset":
        """Create a dataset if no existing dataset matches the specified query.

        Searches for existing datasets using the provided RoboQL query. If a matching
        dataset is found, returns that dataset. If no match is found, creates a new
        dataset with the specified properties and returns it.

        Args:
            match_roboql_query: RoboQL query string to search for existing datasets.
                If this query matches any dataset, that dataset will be returned
                instead of creating a new one.
            description: Optional human-readable description of the dataset.
            metadata: Optional key-value metadata pairs to associate with the dataset.
            name: Optional short name for the dataset (max 120 characters).
            tags: Optional list of tags for dataset discovery and organization.
            caller_org_id: Organization ID to create the dataset in. Required for multi-org users.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Dataset instance representing either the existing matched dataset or the newly created dataset.

        Raises:
            RobotoInvalidRequestException: Invalid dataset parameters or malformed RoboQL query.
            RobotoUnauthorizedException: Caller lacks permission to create datasets or search existing ones.

        Examples:
            Create a dataset only if no dataset with specific metadata exists:

            >>> dataset = Dataset.create_if_not_exists(
            ...     match_roboql_query="dataset.metadata.vehicle_id = 'vehicle_001'",
            ...     name="Vehicle 001 Test Session",
            ...     description="Test data for vehicle 001",
            ...     metadata={"vehicle_id": "vehicle_001", "test_type": "highway"},
            ...     tags=["vehicle_001", "highway"]
            ... )
            >>> print(dataset.dataset_id)
            ds_abc123

            Create a dataset only if no dataset with specific tags exists:

            >>> dataset = Dataset.create_if_not_exists(
            ...     match_roboql_query="dataset.tags CONTAINS 'unique_session_id_xyz'",
            ...     name="Unique Test Session",
            ...     tags=["unique_session_id_xyz", "test"]
            ... )
            >>> # If a dataset with tag 'unique_session_id_xyz' already exists,
            >>> # that dataset is returned instead of creating a new one
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateDatasetIfNotExistsRequest(
            match_roboql_query=match_roboql_query,
            create_request=CreateDatasetRequest(
                description=description,
                metadata=metadata or {},
                name=name,
                tags=tags or [],
            ),
        )
        record = roboto_client.post(
            "v1/datasets/create_if_not_exists",
            data=request,
            caller_org_id=caller_org_id,
        ).to_record(DatasetRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls, dataset_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "Dataset":
        """Create a Dataset instance from a dataset ID.

        Retrieves dataset information from the Roboto platform using the provided
        dataset ID and returns a Dataset instance for interacting with it.

        Args:
            dataset_id: Unique identifier for the dataset.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Dataset instance representing the requested dataset.

        Raises:
            RobotoNotFoundException: Dataset with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> print(dataset.name)
            'Highway Test Session'
            >>> print(len(list(dataset.list_files())))
            42
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/datasets/{dataset_id}").to_record(DatasetRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator["Dataset", None, None]:
        """Query datasets using a specification with filters and pagination.

        Searches for datasets matching the provided query specification. Results are
        returned as a generator that automatically handles pagination, yielding Dataset
        instances as they are retrieved from the API.

        Args:
            spec: Query specification with filters, sorting, and pagination options.
                If None, returns all accessible datasets.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            owner_org_id: Organization ID to scope the query. If None, uses caller's org.

        Yields:
            Dataset instances matching the query specification.

        Raises:
            ValueError: Query specification references unknown dataset attributes.
            RobotoUnauthorizedException: Caller lacks permission to query datasets.

        Examples:
            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(
            ...         field="name",
            ...         comparator=Comparator.Contains,
            ...         value="Roboto"
            ...     ))
            >>> for dataset in Dataset.query(spec):
            ...     print(f"Found dataset: {dataset.name}")
            Found dataset: Roboto Test
            Found dataset: Other Roboto Test
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec if spec is not None else QuerySpecification()

        known = set(DatasetRecord.model_fields.keys())
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
                "are not known attributes of Dataset"
                if plural
                else "is not a known attribute of Dataset"
            )
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        while True:
            paginated_results = roboto_client.post(
                "v1/datasets/query",
                data=spec,
                owner_org_id=owner_org_id,
                idempotent=True,
            ).to_paginated_list(DatasetRecord)

            for record in paginated_results.items:
                yield cls(record, roboto_client)

            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dataset):
            return False
        return self.record == other.record

    def __init__(
        self, record: DatasetRecord, roboto_client: typing.Optional[RobotoClient] = None
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__file_service = FileService(self.__roboto_client)
        self.__file_creds_helper = FileCredentialsHelper(self.__roboto_client)
        self.__record = record
        self.__transaction_completed_unreported_items = {}
        self.__transaction_completed_mutex = threading.Lock()

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        """Timestamp when this dataset was created.

        Returns the UTC datetime when this dataset was first created in the Roboto platform. This property is immutable.
        """
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Identifier of the user who created this dataset.

        Returns the identifier of the person or service which originally created this dataset in the Roboto platform.
        """
        return self.__record.created_by

    @property
    def dataset_id(self) -> str:
        """Unique identifier for this dataset.

        Returns the globally unique identifier assigned to this dataset when it was
        created. This ID is immutable and used to reference the dataset across the
        Roboto platform. It is always prefixed with 'ds_' to distinguish it from other
        Roboto resource IDs.
        """
        return self.__record.dataset_id

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of this dataset.

        Returns the optional description text that provides details about the dataset's
        contents, purpose, or context. Can be None if no description was provided.
        """
        return self.__record.description

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Custom metadata associated with this dataset.

        Returns a copy of the dataset's metadata dictionary containing arbitrary
        key-value pairs for storing custom information. Supports nested structures
        and dot notation for accessing nested fields.
        """
        return self.__record.metadata.copy()

    @property
    def modified(self) -> datetime.datetime:
        """Timestamp when this dataset was last modified.

        Returns the UTC datetime when this dataset was most recently updated.
        This includes changes to metadata, tags, description, or other properties.
        """
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Identifier of the user or service which last modified this dataset.

        Returns the identifier of the person or service which most recently updated
        this dataset's metadata, tags, description, or other properties.
        """
        return self.__record.modified_by

    @property
    def name(self) -> typing.Optional[str]:
        """Human-readable name of this dataset.

        Returns the optional display name for this dataset. Can be None if no name was provided during creation. For
        users whose organizations have their own idiomatic internal dataset IDs, it's recommended to set the name to
        the organization's internal dataset ID, since the Roboto dataset_id property is randomly generated.
        """
        return self.__record.name

    @property
    def org_id(self) -> str:
        """Organization identifier that owns this dataset.

        Returns the unique identifier of the organization that owns and has
        primary access control over this dataset.
        """
        return self.__record.org_id

    @property
    def record(self) -> DatasetRecord:
        """Underlying data record for this dataset.

        Returns the raw :py:class:`~roboto.domain.datasets.DatasetRecord` that contains
        all the dataset's data fields. This provides access to the complete dataset
        state as stored in the platform.
        """
        return self.__record

    @property
    def tags(self) -> list[str]:
        """List of tags associated with this dataset.

        Returns a copy of the list of string tags that have been applied to this
        dataset for categorization and filtering purposes.
        """
        return self.__record.tags.copy()

    def create_directory(
        self,
        name: str,
        error_if_exists: bool = False,
        create_intermediate_dirs: bool = False,
        parent_path: typing.Optional[pathlib.Path] = None,
        origination: typing.Optional[str] = None,
    ) -> DirectoryRecord:
        """Create a directory within the dataset.

        Args:
            name: Name of the directory to create.
            error_if_exists: If True, raises an exception if the directory already exists.
            parent_path: Path of the parent directory. If None, creates the directory in the root of the dataset.
            origination: Optional string describing the source or context of the directory creation.
            create_intermediate_dirs: If True, creates intermediate directories in the path if they don't exist.
                If False, requires all parent directories to already exist.

        Raises:
            RobotoConflictException: If the directory already exists and error_if_exists is True.
            RobotoUnauthorizedException: If the caller lacks permission to create the directory.
            RobotoInvalidRequestException: If the directory name is invalid or the parent path does not exist
                (when create_intermediate_dirs is False).

        Returns:
            DirectoryRecord of the created directory.

        Examples:
            Create a simple directory:

            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset.from_id(...)
            >>> directory = dataset.create_directory("foo")
            >>> print(directory.relative_path)
            foo

            Create a directory with intermediate directories:

            >>> directory = dataset.create_directory(
            ...     name="final",
            ...     parent_path="path/to/deep",
            ...     create_intermediate_dirs=True
            ... )
            >>> print(directory.relative_path)
            path/to/deep/final

        """

        if origination is None:
            package_version = self.__retrieve_roboto_version()
            origination = RobotoEnv.default().roboto_env or f"roboto {package_version}"

        request = CreateDirectoryRequest(
            name=name,
            error_if_exists=error_if_exists,
            parent_path=str(parent_path) if parent_path is not None else None,
            origination=origination,
            create_intermediate_dirs=create_intermediate_dirs,
        )
        return self.__roboto_client.put(
            f"v1/datasets/{self.dataset_id}/directory", data=request
        ).to_record(DirectoryRecord)

    def delete(self) -> None:
        """Delete this dataset from the Roboto platform.

        Permanently removes the dataset and all its associated files, metadata, and topics. This operation cannot
        be undone.

        If a dataset's files are hosted in Roboto managed S3 buckets or customer read/write bring-your-own-buckets,
        the files in this dataset will be deleted from S3 as well. For files hosted in customer read-only buckets,
        the files will not be deleted from S3, but the dataset record and all associated metadata will be deleted.

        Raises:
            RobotoNotFoundException: Dataset does not exist or has already been deleted.
            RobotoUnauthorizedException: Caller lacks permission to delete the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.delete()
            # Dataset and all its files are now permanently deleted
        """
        self.__roboto_client.delete(f"v1/datasets/{self.dataset_id}")

    def delete_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> None:
        """Delete files from this dataset based on pattern matching.

        Deletes files that match the specified include patterns while excluding
        those that match exclude patterns. Uses gitignore-style pattern matching
        for flexible file selection.

        Args:
            include_patterns: List of gitignore-style patterns for files to include.
                If None, all files are considered for deletion.
            exclude_patterns: List of gitignore-style patterns for files to exclude
                from deletion. Takes precedence over include patterns.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to delete files.

        Notes:
            Pattern matching follows gitignore syntax. See https://git-scm.com/docs/gitignore
            for detailed pattern format documentation.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> # Delete all PNG files except those in back_camera directory
            >>> dataset.delete_files(
            ...     include_patterns=["**/*.png"],
            ...     exclude_patterns=["**/back_camera/**"]
            ... )

            >>> # Delete all log files
            >>> dataset.delete_files(include_patterns=["**/*.log"])
        """
        for file in self.list_files(include_patterns, exclude_patterns):
            file.delete()

    def download_files(
        self,
        out_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> list[tuple[FileRecord, pathlib.Path]]:
        """Download files from this dataset to a local directory.

        Downloads files that match the specified patterns to the given local directory.
        The directory structure from the dataset is preserved in the download location.
        If the output directory doesn't exist, it will be created.

        Args:
            out_path: Local directory path where files should be downloaded.
            include_patterns: List of gitignore-style patterns for files to include.
                If None, all files are downloaded.
            exclude_patterns: List of gitignore-style patterns for files to exclude
                from download. Takes precedence over include patterns.

        Returns:
            List of tuples containing (FileRecord, local_path) for each downloaded file.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to download files.

        Notes:
            Pattern matching follows gitignore syntax. See https://git-scm.com/docs/gitignore
            for detailed pattern format documentation.

        Examples:
            >>> import pathlib
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> downloaded = dataset.download_files(
            ...     pathlib.Path("/tmp/dataset_download"),
            ...     include_patterns=["**/*.bag"],
            ...     exclude_patterns=["**/test/**"]
            ... )
            >>> print(f"Downloaded {len(downloaded)} files")
            Downloaded 5 files

            >>> # Download all files
            >>> all_files = dataset.download_files(pathlib.Path("/tmp/all_files"))
        """
        if not out_path.is_dir():
            out_path.mkdir(parents=True)

        all_files = list(self.list_files(include_patterns, exclude_patterns))

        files_by_bucket: dict[str, list[tuple[FileRecord, pathlib.Path]]] = (
            collections.defaultdict(list)
        )
        for file in all_files:
            files_by_bucket[file.record.bucket].append(
                (file.record, out_path / file.relative_path)
            )

        for bucket_name, bucket_files in files_by_bucket.items():
            self.__file_service.download_files(
                file_generator=(file for file in bucket_files),
                credential_provider=self.__file_creds_helper.get_dataset_download_creds_provider(
                    self.dataset_id, bucket_name
                ),
                progress_monitor_factory=TqdmProgressMonitorFactory(
                    concurrency=1,
                    ctx={
                        "base_path": self.dataset_id,
                        "total_file_count": len(all_files),
                    },
                ),
                max_concurrency=8,
            )

        return [item for val in files_by_bucket.values() for item in val]

    def get_file_by_path(
        self,
        relative_path: typing.Union[str, pathlib.Path],
        version_id: typing.Optional[int] = None,
    ) -> File:
        """Get a File instance for a file at the specified path in this dataset.

        Retrieves a file by its relative path within the dataset. Optionally
        retrieves a specific version of the file.

        Args:
            relative_path: Path of the file relative to the dataset root.
            version_id: Specific version of the file to retrieve. If None, gets the latest version.

        Returns:
            File instance representing the file at the specified path.

        Raises:
            RobotoNotFoundException: File at the given path does not exist in the dataset.
            RobotoUnauthorizedException: Caller lacks permission to access the file.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> file = dataset.get_file_by_path("logs/session1.bag")
            >>> print(file.file_id)
            file_xyz789

            >>> # Get specific version
            >>> old_file = dataset.get_file_by_path("data/sensors.csv", version_id=1)
            >>> print(old_file.version)
            1
        """
        return File.from_path_and_dataset_id(
            file_path=relative_path,
            dataset_id=self.dataset_id,
            version_id=version_id,
            roboto_client=self.__roboto_client,
        )

    def generate_summary(self) -> AISummary:
        """Generate a new AI-powered summary of this dataset.

        Creates a new AI-generated summary that analyzes the dataset's contents,
        including files, metadata, and topics. If a summary already exists, it will
        be overwritten. The results are persisted and can be retrieved later with
        get_summary().

        Returns:
            AISummary object containing the generated summary text and creation timestamp.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to generate summaries.
            RobotoInvalidRequestException: Dataset is not suitable for summarization.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> summary = dataset.generate_summary()
            >>> print(summary.text)
            This dataset contains autonomous vehicle sensor data from a highway
            driving session, including camera images, LiDAR point clouds, and
            GPS coordinates collected over a 30-minute period.
            >>> print(summary.created)
            2024-01-15 10:30:00+00:00
        """
        return self.__roboto_client.post(
            f"v1/datasets/{self.dataset_id}/summary"
        ).to_record(AISummary)

    def get_summary(self) -> AISummary:
        """Get the latest AI-generated summary of this dataset.

        Retrieves the most recent AI-generated summary for this dataset. If no summary
        exists, one will be automatically generated (equivalent to calling generate_summary()).

        Once a summary is generated, it persists and is returned by this method until
        generate_summary() is explicitly called again. The summary does not automatically
        update when the dataset or its files change.

        Returns:
            AISummary object containing the summary text and creation timestamp.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to access summaries.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> summary = dataset.get_summary()
            >>> print(summary.text)
            This dataset contains autonomous vehicle sensor data from a highway
            driving session, including camera images, LiDAR point clouds, and
            GPS coordinates collected over a 30-minute period.

            >>> # Summary is cached - subsequent calls return the same summary
            >>> cached_summary = dataset.get_summary()
            >>> assert summary.created == cached_summary.created
        """
        return self.__roboto_client.get(
            f"v1/datasets/{self.dataset_id}/summary"
        ).to_record(AISummary)

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

        Returns: An AI Summary object containing a full LLM summary of the dataset.

        Raises:
            RobotoFailedToGenerateException: If the summary status becomes FAILED.
            TimeoutError: If the timeout is reached before the summary completes.

        Example:
            >>> from roboto import Dataset
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> summary = dataset.get_summary_sync(timeout=60)
            >>> print(summary.text)
            This dataset contains ...
        """

        def _check_summary_completion() -> bool:
            summary = self.get_summary()

            if summary.status == AISummaryStatus.Failed:
                raise RobotoFailedToGenerateException(
                    f"Summary generation failed for dataset {self.dataset_id}"
                )

            return summary.status == AISummaryStatus.Complete

        wait_for(
            _check_summary_completion,
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for summary completion for dataset '{self.dataset_id}'",
        )

        return self.get_summary()

    def get_topics(
        self,
        include: typing.Optional[collections.abc.Sequence[str]] = None,
        exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> collections.abc.Generator[Topic, None, None]:
        """Get all topics associated with files in this dataset, with optional filtering.

        Retrieves all topics that were extracted from files in this dataset during
        ingestion. If multiple files have topics with the same name (e.g., chunked
        files with the same schema), they are returned as separate topic objects.

        Topics can be filtered by name using include/exclude patterns. Topics specified
        on both the inclusion and exclusion lists will be excluded.

        Args:
            include: If provided, only topics with names in this sequence are yielded.
            exclude: If provided, topics with names in this sequence are skipped.
                Takes precedence over include list.

        Yields:
            Topic instances associated with files in this dataset, filtered according to the parameters.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for topic in dataset.get_topics():
            ...     print(f"Topic: {topic.name}")
            Topic: /camera/image
            Topic: /imu/data
            Topic: /gps/fix

            >>> # Only get camera topics
            >>> camera_topics = list(dataset.get_topics(include=["/camera/image", "/camera/info"]))
            >>> print(f"Found {len(camera_topics)} camera topics")

            >>> # Exclude diagnostic topics
            >>> data_topics = list(dataset.get_topics(exclude=["/diagnostics"]))
        """

        for topic in Topic.get_by_dataset(self.dataset_id, self.__roboto_client):
            if include is not None and topic.name not in include:
                continue

            if exclude is not None and topic.name in exclude:
                continue

            yield topic

    def get_topics_by_file(
        self, relative_path: typing.Union[str, pathlib.Path]
    ) -> collections.abc.Generator[Topic, None, None]:
        """Get all topics associated with a specific file in this dataset.

        Retrieves all topics that were extracted from the specified file during
        ingestion. This is a convenience method that combines file lookup and
        topic retrieval.

        Args:
            relative_path: Path of the file relative to the dataset root.

        Yields:
            Topic instances associated with the specified file.

        Raises:
            RobotoNotFoundException: File at the given path does not exist in the dataset.
            RobotoUnauthorizedException: Caller lacks permission to access the file or its topics.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for topic in dataset.get_topics_by_file("logs/session1.bag"):
            ...     print(f"Topic: {topic.name}")
            Topic: /camera/image
            Topic: /imu/data
            Topic: /gps/fix
        """
        file = self.get_file_by_path(relative_path)
        return file.get_topics()

    def list_directories(
        self,
    ) -> collections.abc.Generator[DirectoryRecord, None, None]:
        page_token: typing.Optional[str] = None
        while True:
            paginated_results = self.__roboto_client.get(
                f"v1/files/association/id/{self.dataset_id}/directories",
                query={"page_token": page_token},
            ).to_record(PaginatedList[DirectoryRecord])
            for record in paginated_results.items:
                yield record
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def list_files(
        self,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> collections.abc.Generator[File, None, None]:
        """List files in this dataset with optional pattern-based filtering.

        Returns all files in the dataset that match the specified include patterns
        while excluding those that match exclude patterns. Uses gitignore-style
        pattern matching for flexible file selection.

        Args:
            include_patterns: List of gitignore-style patterns for files to include.
                If None, all files are considered.
            exclude_patterns: List of gitignore-style patterns for files to exclude.
                Takes precedence over include patterns.

        Yields:
            File instances that match the specified patterns.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to list files.

        Notes:
            Pattern matching follows gitignore syntax. See https://git-scm.com/docs/gitignore
            for detailed pattern format documentation.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> for file in dataset.list_files():
            ...     print(file.relative_path)
            logs/session1.bag
            data/sensors.csv
            images/camera_001.jpg

            >>> # List only image files, excluding back camera
            >>> for file in dataset.list_files(
            ...     include_patterns=["**/*.png", "**/*.jpg"],
            ...     exclude_patterns=["**/back_camera/**"]
            ... ):
            ...     print(file.relative_path)
            images/front_camera_001.jpg
            images/side_camera_001.jpg
        """

        page_token: typing.Optional[str] = None
        while True:
            paginated_results = self.__list_files_page(
                page_token=page_token,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
            for record in paginated_results.items:
                yield File(record, self.__roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def put_metadata(
        self,
        metadata: dict[str, typing.Any],
    ) -> None:
        """Add or update metadata fields for this dataset.

        Sets each key-value pair in the provided dictionary as dataset metadata.
        If a key doesn't exist, it will be created. If it exists, the value will
        be overwritten. Keys must be strings and dot notation is supported for
        nested keys.

        Args:
            metadata: Dictionary of metadata key-value pairs to add or update.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.put_metadata({
            ...     "vehicle_id": "vehicle_001",
            ...     "test_type": "highway_driving",
            ...     "weather.condition": "sunny",
            ...     "weather.temperature": 25
            ... })
            >>> print(dataset.metadata["vehicle_id"])
            'vehicle_001'
            >>> print(dataset.metadata["weather"]["condition"])
            'sunny'
        """
        self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(
        self,
        tags: StrSequence,
    ) -> None:
        """Add or update tags for this dataset.

        Adds each tag in the provided sequence to the dataset. If a tag already
        exists, it will not be duplicated. This operation replaces the current
        tag list with the provided tags.

        Args:
            tags: Sequence of tag strings to set on the dataset.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset.put_tags(["highway", "autonomous", "test", "sunny"])
            >>> print(dataset.tags)
            ['highway', 'autonomous', 'test', 'sunny']
        """
        self.update(
            metadata_changeset=MetadataChangeset(put_tags=tags),
        )

    def refresh(self) -> "Dataset":
        """Refresh this dataset instance with the latest data from the platform.

        Fetches the current state of the dataset from the Roboto platform and updates
        this instance's data. Useful when the dataset may have been modified by other
        processes or users.

        Returns:
            This Dataset instance with refreshed data.

        Raises:
            RobotoNotFoundException: Dataset no longer exists.
            RobotoUnauthorizedException: Caller lacks permission to access the dataset.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> # Dataset may have been updated by another process
            >>> refreshed_dataset = dataset.refresh()
            >>> print(f"Current file count: {len(list(refreshed_dataset.list_files()))}")
        """
        self.__record = self.__roboto_client.get(
            f"v1/datasets/{self.dataset_id}"
        ).to_record(DatasetRecord)
        return self

    def remove_metadata(
        self,
        metadata: StrSequence,
    ) -> None:
        """
        Remove each key in this sequence from dataset metadata if it exists.
        Keys must be strings. Dot notation is supported for nested keys.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.remove_metadata(["foo", "baz.qux"])
        """
        self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(
        self,
        tags: StrSequence,
    ) -> None:
        """Remove each tag in this sequence if it exists"""
        self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    def to_association(self) -> Association:
        return Association.dataset(self.dataset_id)

    def to_dict(self) -> dict[str, typing.Any]:
        """Convert this dataset to a dictionary representation.

        Returns the dataset's data as a JSON-serializable dictionary containing
        all dataset attributes and metadata.

        Returns:
            Dictionary representation of the dataset data.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> dataset_dict = dataset.to_dict()
            >>> print(dataset_dict["name"])
            'Highway Test Session'
            >>> print(dataset_dict["metadata"])
            {'vehicle_id': 'vehicle_001', 'test_type': 'highway'}
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        conditions: typing.Optional[list[UpdateCondition]] = None,
        description: typing.Optional[str] = None,
        metadata_changeset: typing.Optional[MetadataChangeset] = None,
        name: typing.Optional[str] = None,
    ) -> "Dataset":
        """Update this dataset's properties.

        Updates various properties of the dataset including name, description,
        and metadata. Only specified parameters are updated; others remain unchanged.
        Optionally supports conditional updates based on current field values.

        Args:
            conditions: Optional list of conditions that must be met for the update to proceed.
            description: New description for the dataset.
            metadata_changeset: Metadata changes to apply (add, update, or remove fields/tags).
            name: New name for the dataset.

        Returns:
            Updated Dataset instance with the new properties.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to update the dataset.
            RobotoConditionalUpdateFailedException: Update conditions were not met.

        Examples:
            >>> dataset = Dataset.from_id("ds_abc123")
            >>> updated_dataset = dataset.update(
            ...     name="Updated Highway Test Session",
            ...     description="Updated description with more details"
            ... )
            >>> print(updated_dataset.name)
            'Updated Highway Test Session'

            >>> # Update with metadata changes
            >>> from roboto.updates import MetadataChangeset
            >>> changeset = MetadataChangeset(put_fields={"processed": True})
            >>> updated_dataset = dataset.update(metadata_changeset=changeset)
        """
        request = UpdateDatasetRequest(
            conditions=conditions,
            description=description,
            name=name,
            metadata_changeset=metadata_changeset,
        )

        self.__record = self.__roboto_client.put(
            f"/v1/datasets/{self.dataset_id}",
            data=request,
        ).to_record(DatasetRecord)
        return self

    def rename_directory(self, old_path: str, new_path: str) -> DirectoryRecord:
        response = self.__roboto_client.put(
            f"v1/datasets/{self.dataset_id}/directory/rename",
            data=RenameDirectoryRequest(
                old_path=old_path,
                new_path=new_path,
            ),
        )

        return response.to_record(DirectoryRecord)

    def upload_directory(
        self,
        directory_path: pathlib.Path,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
        delete_after_upload: bool = False,
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
        print_progress: bool = True,
    ) -> None:
        """
        Uploads all files and directories recursively from the specified directory path. You can use
        `include_patterns` and `exclude_patterns` to control what files and directories are uploaded, and can
        use `delete_after_upload` to clean up your local filesystem after the uploads succeed.

        Example:
            >>> from roboto import Dataset
            >>> dataset = Dataset(...)
            >>> dataset.upload_directory(
            ...     pathlib.Path("/path/to/directory"),
            ...     exclude_patterns=[
            ...         "__pycache__/",
            ...         "*.pyc",
            ...         "node_modules/",
            ...         "**/*.log",
            ...     ],
            ... )

        Notes:
            - Both `include_patterns` and `exclude_patterns` follow the 'gitignore' pattern format described
              in https://git-scm.com/docs/gitignore#_pattern_format.
            - If both `include_patterns` and `exclude_patterns` are provided, files matching
              `exclude_patterns` will be excluded even if they match `include_patterns`.
        """
        include_spec: typing.Optional[pathspec.PathSpec] = excludespec_from_patterns(
            include_patterns
        )
        exclude_spec: typing.Optional[pathspec.PathSpec] = excludespec_from_patterns(
            exclude_patterns
        )
        all_files = self.__list_directory_files(
            directory_path, include_spec=include_spec, exclude_spec=exclude_spec
        )
        file_destination_paths = {
            path: os.path.relpath(path, directory_path) for path in all_files
        }

        self.upload_files(
            all_files, file_destination_paths, max_batch_size, print_progress
        )

        if delete_after_upload:
            for file in all_files:
                if file.is_file():
                    file.unlink()

    def upload_file(
        self,
        file_path: pathlib.Path,
        file_destination_path: typing.Optional[str] = None,
        print_progress: bool = True,
    ) -> None:
        """
        Upload a single file to the dataset.
        If `file_destination_path` is not provided, the file will be uploaded to the top-level of the dataset.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.upload_file(
            ...     pathlib.Path("/path/to/file.txt"),
            ...     file_destination_path="foo/bar.txt",
            ... )
        """
        if not file_destination_path:
            file_destination_path = file_path.name

        self.upload_files(
            [file_path],
            {file_path: file_destination_path},
            print_progress=print_progress,
        )

    def upload_files(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        file_destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
        max_batch_size: int = MAX_FILES_PER_MANIFEST,
        print_progress: bool = True,
    ):
        """
        Upload multiple files to the dataset.
        If `file_destination_paths` is not provided, files will be uploaded to the top-level of the dataset.

        Example:
            >>> from roboto.domain import datasets
            >>> dataset = datasets.Dataset(...)
            >>> dataset.upload_files(
            ...     [
            ...         pathlib.Path("/path/to/file.txt"),
            ...         ...
            ...     ],
            ...     file_destination_paths={
            ...         pathlib.Path("/path/to/file.txt"): "foo/bar.txt",
            ...     },
            ... )
        """
        working_set: list[pathlib.Path] = []

        for file in files:
            working_set.append(file)

            if len(working_set) >= max_batch_size:
                self.__upload_files_batch(
                    working_set, file_destination_paths, print_progress
                )
                working_set = []

        if len(working_set) > 0:
            self.__upload_files_batch(
                working_set, file_destination_paths, print_progress
            )

    def _complete_manifest_transaction(self, transaction_id: str) -> None:
        """
        Marks a transaction as 'completed', which allows the Roboto Platform to evaluate triggers
        for automatic action on incoming data. This also aids reporting on partial upload failure cases.

        This should be considered private.

        It is loosely exposed (single underscore instead of double) because of a niche, administrative use-case.
        """
        self.__roboto_client.put(
            f"v2/datasets/{self.dataset_id}/batch_uploads/{transaction_id}/complete"
        )

    def _create_manifest_transaction(
        self,
        origination: str,
        resource_manifest: dict[str, int],
    ) -> tuple[str, dict[str, str]]:
        """
        This should be considered private.

        It is loosely exposed (single underscore instead of double) because of a niche, administrative use-case.
        """
        request = BeginManifestTransactionRequest(
            origination=origination,
            resource_manifest=resource_manifest,
        )

        result = self.__roboto_client.post(
            f"v2/datasets/{self.dataset_id}/batch_uploads",
            data=request,
            caller_org_id=self.org_id,
        ).to_record(BeginManifestTransactionResponse)

        return result.transaction_id, dict(result.upload_mappings)

    def _flush_manifest_item_completions(
        self,
        transaction_id: str,
        manifest_items: list[str],
    ) -> None:
        """
        This should be considered private.

        It is loosely exposed (single underscore instead of double) because of a niche, administrative use-case.
        """
        self.__roboto_client.put(
            f"v2/datasets/{self.dataset_id}/batch_uploads/{transaction_id}/progress",
            data=ReportTransactionProgressRequest(
                manifest_items=manifest_items,
            ),
        )

    def __list_directory_files(
        self,
        directory_path: pathlib.Path,
        include_spec: typing.Optional[pathspec.PathSpec] = None,
        exclude_spec: typing.Optional[pathspec.PathSpec] = None,
    ) -> collections.abc.Iterable[pathlib.Path]:
        all_files = set()

        for root, _, files in os.walk(directory_path):
            for file in files:
                should_include = include_spec is None or include_spec.match_file(file)
                should_exclude = exclude_spec is not None and exclude_spec.match_file(
                    file
                )

                if should_include and not should_exclude:
                    all_files.add(pathlib.Path(root, file))

        return all_files

    def __list_files_page(
        self,
        page_token: typing.Optional[str] = None,
        include_patterns: typing.Optional[list[str]] = None,
        exclude_patterns: typing.Optional[list[str]] = None,
    ) -> PaginatedList[FileRecord]:
        """
        List files associated with dataset.

        Files are associated with datasets in an eventually-consistent manner,
        so there will likely be delay between a file being uploaded and it appearing in this list.
        """
        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = str(page_token)

        request = QueryDatasetFilesRequest(
            page_token=page_token,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        return self.__roboto_client.post(
            f"v1/datasets/{self.dataset_id}/files/query",
            data=request,
            query=query_params,
            idempotent=True,
        ).to_paginated_list(FileRecord)

    def __on_manifest_item_complete(
        self,
        transaction_id: str,
        total_file_count: int,
        manifest_item_identifier: str,
    ) -> None:
        """
        This method is used as a callback (a "subscriber") for S3 TransferManager,
        which is used to upload files to S3.

        TransferManager uses thread-based concurrency under the hood,
        so any instance state accessed or modified here must be synchronized.
        """
        with self.__transaction_completed_mutex:
            if transaction_id not in self.__transaction_completed_unreported_items:
                self.__transaction_completed_unreported_items[transaction_id] = set()

            self.__transaction_completed_unreported_items[transaction_id].add(
                manifest_item_identifier
            )

            completion_count = len(
                self.__transaction_completed_unreported_items[transaction_id]
            )
            if self.__sufficient_uploads_completed_to_report_progress(
                completion_count, total_file_count
            ):
                self._flush_manifest_item_completions(
                    transaction_id=transaction_id,
                    manifest_items=list(
                        self.__transaction_completed_unreported_items[transaction_id]
                    ),
                )
                self.__transaction_completed_unreported_items[transaction_id] = set()

    def __retrieve_roboto_version(self) -> str:
        try:
            return importlib.metadata.version("roboto")
        except importlib.metadata.PackageNotFoundError:
            return "version_not_found"

    def __sufficient_uploads_completed_to_report_progress(
        self, completion_count: int, total_file_count: int
    ):
        """
        Determine if there are a sufficient number of files that have already been uploaded
        to S3 to report progress to the Roboto Platform.

        If the total count of files to upload is below the reporting threshold,
        or if for whatever other reason a batch is not large enough to report progress,
        file records will still be finalized as part of the upload finalization routine.
        See, e.g., :py:meth:`~roboto.domain.datasets.dataset.Dataset._complete_manifest_transaction`
        """
        batch_size = math.ceil(total_file_count / Dataset.UPLOAD_REPORTING_BATCH_COUNT)
        return (
            completion_count >= batch_size
            and completion_count >= Dataset.UPLOAD_REPORTING_MIN_BATCH_SIZE
        )

    def __upload_files_batch(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        file_destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
        print_progress: bool = True,
    ):
        package_version = self.__retrieve_roboto_version()

        origination = RobotoEnv.default().roboto_env or f"roboto {package_version}"
        file_manifest = {
            file_destination_paths.get(path, path.name): path.stat().st_size
            for path in files
        }

        total_file_count = len(file_manifest)
        total_file_size = sum(file_manifest.values())

        transaction_id, create_upload_mappings = self._create_manifest_transaction(
            origination=origination,
            resource_manifest=file_manifest,
        )

        file_path_to_manifest_mappings = {
            file_destination_paths.get(path, path.name): path for path in files
        }
        upload_mappings = {
            file_path_to_manifest_mappings[src_path]: dest_uri
            for src_path, dest_uri in create_upload_mappings.items()
        }

        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory()
        if print_progress:
            progress_monitor_factory = TqdmProgressMonitorFactory(
                concurrency=1,
                ctx={
                    "expected_file_count": total_file_count,
                    "expected_file_size": total_file_size,
                },
            )

        with progress_monitor_factory.upload_monitor(
            source=f"{total_file_count} file" + ("s" if total_file_count != 1 else ""),
            size=total_file_size,
        ) as progress_monitor:
            self.__file_service.upload_many_files(
                file_generator=upload_mappings.items(),
                credential_provider=self.__file_creds_helper.get_dataset_upload_creds_provider(
                    self.dataset_id, transaction_id
                ),
                on_file_complete=functools.partial(
                    self.__on_manifest_item_complete,
                    transaction_id,
                    total_file_count,
                ),
                progress_monitor=progress_monitor,
                max_concurrency=8,
            )

        self._complete_manifest_transaction(
            transaction_id,
        )
