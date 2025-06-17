# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing
import urllib.parse

import pydantic

# Python 3.8/3.9 compatible import of TypeGuard
try:
    from typing import TypeGuard
except ImportError:
    try:
        from typing_extensions import TypeGuard
    except ImportError:
        pass


class FileStatus(str, enum.Enum):
    """Enumeration of possible file status values in the Roboto platform.

    File status tracks the lifecycle state of a file from initial upload through
    to availability for use. This status is managed automatically by the platform
    and affects file visibility and accessibility.

    The typical file lifecycle is: Reserved → Available → (optionally) Deleted.
    """

    Available = "available"
    """File upload is complete and the file is ready for use.

    Files with this status are visible in dataset listings, searchable through
    the query system, and available for download and processing by actions.
    """

    Deleted = "deleted"
    """File is marked for deletion and is no longer accessible.

    Files with this status are not visible in listings and cannot be accessed.
    This status may be temporary during the deletion process.
    """

    Reserved = "reserved"
    """File upload has been initiated but not yet completed.

    Files with this status are not yet available for use and are not visible
    in dataset listings. This is the initial status when an upload begins.
    """


class IngestionStatus(str, enum.Enum):
    """Enumeration of file ingestion status values in the Roboto platform.

    Ingestion status tracks whether a file's data has been processed and extracted
    into topics for analysis and visualization. This status determines what platform
    features are available for the file and whether it can trigger automated workflows.

    File ingestion happens as a post-upload processing step. Roboto supports many
    common robotics log formats (ROS bags, MCAP files, ULOG files, etc.) out-of-the-box.
    Custom ingestion actions can be written for other formats.

    When writing custom ingestion actions, be sure to update the file's ingestion
    status to mark it as fully ingested. This enables triggers and other automated
    workflows that depend on complete ingestion.

    Ingested files have first-class visualization support and can be queried
    through the topic data system.
    """

    NotIngested = "not_ingested"
    """No topics from this file have been processed or recorded.

    Files with this status have not undergone data extraction. They cannot be
    visualized through the topic system and are not eligible for topic-based
    triggers or analysis workflows.
    """

    PartlyIngested = "partly_ingested"
    """Some but not all topics from this file have been processed.

    Files with this status have at least one topic record but ingestion is
    incomplete. Some visualization and analysis features may be available,
    but the file is not yet eligible for post-ingestion triggers.
    """

    Ingested = "ingested"
    """All topics from this file have been fully processed and recorded.

    Files with this status have complete topic data available for visualization,
    analysis, and querying. They are eligible for post-ingestion triggers and
    automated workflows that depend on complete data extraction.
    """


class FileStorageType(str, enum.Enum):
    """Enumeration of file storage types in the Roboto platform.

    Storage type indicates how the file was added to the platform and affects
    access patterns and permissions. This information is used internally for
    credential management and access control.
    """

    S3Imported = "imported"
    """File was imported from a read-only customer-managed S3 bucket.

    These files remain in the customer's bucket and are accessed using
    customer-provided credentials. The customer retains full control over
    the file storage and access permissions.
    """

    S3Uploaded = "uploaded"
    """File was uploaded to a Roboto-managed or customer read/write bucket.

    These files were explicitly uploaded through the Roboto platform to either
    a Roboto-managed bucket or a customer's bring-your-own read/write bucket.
    Access is managed through Roboto's credential system.
    """

    S3Directory = "directory"
    """
    This node is a virtual directory.
    """


class FSType(str, enum.Enum):
    """
    File system type enum
    """

    File = "file"
    Directory = "directory"


class FileRecord(pydantic.BaseModel):
    """Wire-transmissible representation of a file in the Roboto platform.

    FileRecord contains all the metadata and properties associated with a file,
    including its location, status, ingestion state, and user-defined metadata.
    This is the data structure used for API communication and persistence.

    FileRecord instances are typically created by the platform during file import
    or upload operations, and are updated as files are processed and modified.
    The File domain class wraps FileRecord to provide a more convenient interface
    for file operations.
    """

    association_id: (
        str  # e.g. dataset_id, collection_id, etc.; GSI PK of "association_id" index.
    )
    created: datetime.datetime
    created_by: str = ""
    description: typing.Optional[str] = None
    device_id: typing.Optional[str] = None
    file_id: str
    fs_type: FSType = FSType.File
    ingestion_status: IngestionStatus = IngestionStatus.NotIngested
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    modified: datetime.datetime
    modified_by: str
    name: str
    org_id: str
    origination: str = ""  # Defaulted for compatibility
    parent_id: typing.Optional[str] = None
    relative_path: (
        str  # path relative to some common prefix. Used as local path when downloaded.
    )
    size: int  # bytes
    status: FileStatus = FileStatus.Available
    storage_type: FileStorageType = FileStorageType.S3Uploaded
    tags: list[str] = pydantic.Field(default_factory=list)
    upload_id: str = "NO_ID"  # Defaulted for backwards compatibility
    uri: str
    version: int

    @property
    def bucket(self) -> str:
        parsed_uri = urllib.parse.urlparse(self.uri)
        return parsed_uri.netloc

    @property
    def key(self) -> str:
        parsed_uri = urllib.parse.urlparse(self.uri)
        return parsed_uri.path.lstrip("/")


class FileTag(enum.Enum):
    """Enumeration of system-defined file tag types.

    These tags are used internally by the platform for indexing and organizing
    files. They are automatically applied during file operations and should not
    be manually modified by users.
    """

    DatasetId = "dataset_id"
    """Tag containing the ID of the dataset that contains this file."""

    OrgId = "org_id"
    """Tag containing the organization ID that owns this file."""

    CommonPrefix = "common_prefix"
    """Tag containing the common path prefix for files in a batch operation."""

    TransactionId = "transaction_id"
    """Tag containing the transaction ID for files uploaded in a batch."""


class DirectoryRecord(pydantic.BaseModel):
    """Wire-transmissible representation of a directory within a dataset.

    DirectoryRecord represents a logical directory structure within a dataset,
    containing metadata about the directory's location and contents. Directories
    are used to organize files hierarchically within datasets.

    Directory records are typically returned when browsing dataset contents
    or when performing directory-based operations like bulk deletion.
    """

    association_id: (
        str  # e.g. dataset_id, collection_id, etc.; GSI PK of "association_id" index.
    )
    created: datetime.datetime
    created_by: str
    description: typing.Optional[str] = None
    directory_id: str
    fs_type: FSType = FSType.Directory
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    modified: datetime.datetime
    modified_by: str
    name: str
    """Name of the directory (the final component of the path)."""

    org_id: str
    origination: str
    parent_id: typing.Optional[str] = None
    relative_path: str
    status: FileStatus = FileStatus.Available
    storage_type: FileStorageType = FileStorageType.S3Directory
    tags: list[str] = pydantic.Field(default_factory=list)
    upload_id: str


def is_directory(record: FileRecord | DirectoryRecord) -> TypeGuard[DirectoryRecord]:
    return record.fs_type == FSType.Directory


def is_file(record: FileRecord | DirectoryRecord) -> TypeGuard[FileRecord]:
    return record.fs_type == FSType.File
