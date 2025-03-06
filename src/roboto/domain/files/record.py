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


class FileStatus(str, enum.Enum):
    """
    At the initiation of an upload, a file's status is marked as ``Reserved``.
    Once the upload completes successfully, it is set to ``Available``,
    and is made visible when listing files in a dataset or searching files.
    A file's status may be temporarily set to ``Deleted`` if its deletion is in progress.
    """

    Available = "available"
    Deleted = "deleted"
    Reserved = "reserved"


class IngestionStatus(str, enum.Enum):
    """
    A file is considered ``Ingested`` if all topics stored in that file have been read and recorded by Roboto.
    A file is considered ``PartlyIngested`` if it has at least one associated topic record.

    File ingestion happens as a post-upload processing step, and Roboto supports
    a number of common robotics log formats (such as ROS bags, MCAP files, and ULOG files) out-of-the-box.

    If you write your own ingestion action, be sure to update the files you ingest to mark them as
    fully ingested. This will allow you to use the Roboto platform to trigger actions on your
    ingested file.

    An ingested file generally has first-class visualization support.
    """

    NotIngested = "not_ingested"
    """
    None of the topics on this file have been read or recorded by Roboto.
    """

    PartlyIngested = "partly_ingested"
    """
    This file has been partly ingested and Roboto is able to visualize some of its topics.
    """

    Ingested = "ingested"
    """
    This file has been fully ingested and Roboto is able to schedule additional post-processing of its topics.
    """


class FileStorageType(str, enum.Enum):
    """
    File storage type enum
    """

    S3Imported = "imported"
    """
    This file was imported from a read-only customer bucket.
    """

    S3Uploaded = "uploaded"
    """
    This file was explicitly uploaded to either a Roboto managed bucket or a read/write customer bring-your-own bucket.
    """


class FileRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of a file.
    """

    association_id: (
        str  # e.g. dataset_id, collection_id, etc.; GSI PK of "association_id" index.
    )
    created: datetime.datetime
    created_by: str = ""
    description: typing.Optional[str] = None
    device_id: typing.Optional[str] = None
    file_id: str
    ingestion_status: IngestionStatus = IngestionStatus.NotIngested
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    modified: datetime.datetime
    modified_by: str
    org_id: str
    origination: str = ""  # Defaulted for compatibility
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
    """
    FileTag enum
    """

    DatasetId = "dataset_id"
    OrgId = "org_id"
    # Path to file relative to common prefix
    CommonPrefix = "common_prefix"
    TransactionId = "transaction_id"


class DirectoryRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of a dataset directory.
    """

    name: str
