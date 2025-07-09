# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections
import typing

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType
from roboto.updates import MetadataChangeset

from .record import DirectoryRecord, FileRecord


class DeleteFileRequest(pydantic.BaseModel):
    """Request payload for deleting a file from the platform.

    This request is used internally by the platform to delete files and their
    associated data. The file is identified by its storage URI.
    """

    uri: str
    """Storage URI of the file to delete (e.g., 's3://bucket/path/to/file.bag')."""


class FileRecordRequest(pydantic.BaseModel):
    """Request payload for upserting a file record.

    Used to create or update file metadata records in the platform. This is
    typically used during file import or metadata update operations.
    """

    file_id: str
    """Unique identifier for the file."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """List of tags to associate with the file for discovery and organization."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata pairs to associate with the file."""


class ImportFileRequest(pydantic.BaseModel):
    """Request payload for importing an existing file into a dataset.

    Used to register files that already exist in storage (such as customer S3 buckets)
    with the Roboto platform. The file content remains in its original location while
    metadata is stored in Roboto for discovery and processing.
    """

    dataset_id: str
    """ID of the dataset to import the file into."""

    description: typing.Optional[str] = None
    """Optional human-readable description of the file."""

    tags: typing.Optional[list[str]] = None
    """Optional list of tags for file discovery and organization."""

    metadata: typing.Optional[dict[str, typing.Any]] = None
    """Optional key-value metadata pairs to associate with the file."""

    relative_path: str
    """Path of the file relative to the dataset root (e.g., `logs/session1.bag`)."""

    size: typing.Optional[int] = None
    """Size of the file in bytes. When importing a single file, you can omit the size, as Roboto will look up the size
    from the object store. When calling import_batch, you must provide the size explicitly."""

    uri: str
    """Storage URI where the file is located (e.g., `s3://bucket/path/to/file.bag`)."""


class QueryFilesRequest(pydantic.BaseModel):
    """Request payload for querying files with filters.

    Used to search for files based on various criteria such as metadata,
    tags, ingestion status, and other file properties. The filters are
    applied server-side to efficiently return matching files.
    """

    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Dictionary of filter criteria to apply when searching for files."""

    model_config = ConfigDict(extra="ignore")


class RenameFileRequest(pydantic.BaseModel):
    """Request payload for renaming a file within its dataset.

    Changes the relative path of a file within its dataset. This updates
    the file's logical location but does not move the actual file content
    in storage.
    """

    association_id: str
    """ID of the dataset containing the file to rename."""

    new_path: str
    """New relative path for the file within the dataset."""


class SignedUrlResponse(pydantic.BaseModel):
    """Response containing a signed URL for direct file access.

    Provides a time-limited URL that allows direct access to file content
    without requiring Roboto authentication. Used for file downloads and
    integration with external systems.
    """

    url: str
    """Signed URL that provides temporary direct access to the file."""


class UpdateFileRecordRequest(pydantic.BaseModel):
    """Request payload for updating file record properties.

    Used to modify file metadata, description, and ingestion status. Only
    specified fields are updated; others remain unchanged. Uses NotSet
    sentinel values to distinguish between explicit None values and
    fields that should not be modified.
    """

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New description for the file, or NotSet to leave unchanged."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Metadata changes to apply (add, update, or remove fields/tags), or NotSet to leave unchanged."""

    ingestion_complete: typing.Union[typing.Literal[True], NotSetType] = NotSet
    """Set to True to mark file as fully ingested, or NotSet to leave unchanged."""

    model_config = pydantic.ConfigDict(
        extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier
    )


class DirectoryContentsPage(pydantic.BaseModel):
    """Response containing the contents of a dataset directory page.

    Represents a paginated view of files and subdirectories within a dataset
    directory. Used when browsing dataset contents hierarchically.
    """

    files: collections.abc.Sequence[FileRecord]
    """Files contained in this directory page."""

    directories: collections.abc.Sequence[DirectoryRecord]
    """Subdirectories contained in this directory page."""

    next_token: typing.Optional[str] = None
    """Token for retrieving the next page of results, if any."""


class AbortTransactionsRequest(pydantic.BaseModel):
    """Request payload for aborting file upload transactions.

    Used to cancel ongoing file upload transactions, typically when uploads
    fail or are no longer needed. This cleans up any reserved resources
    and marks associated files as no longer pending.
    """

    transaction_ids: list[str]
    """List of transaction IDs to abort."""
