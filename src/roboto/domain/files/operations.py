# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections
import collections.abc
import typing

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType
from roboto.updates import MetadataChangeset

from .record import DirectoryRecord, FileRecord


class CreateDirectoryRequest(pydantic.BaseModel):
    """Request payload to create a directory among the files of one association."""

    name: str
    error_if_exists: bool = False
    parent_path: typing.Optional[str] = None
    origination: typing.Optional[str] = None
    create_intermediate_dirs: bool = False
    """If True, creates intermediate directories in the path if they don't exist.
    If False, requires all parent directories to already exist."""


class CreateLinkRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/files/association/id/<association_id>/link``."""

    relative_path: str
    """Where the link sits among the association's files. Missing parent directories are created."""

    target_file_id: str
    """ID of the file the link points at. It must be a file, not a link or a directory, in the same org."""

    target_version: typing.Optional[int] = None
    """Version of the target to pin. Defaults to the target's current version."""


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

    device_id: typing.Optional[str] = None
    """Optional identifier of the device that generated this data."""

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

    device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New device ID for the file, or NotSet to leave unchanged."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Metadata changes to apply (add, update, or remove fields/tags), or NotSet to leave unchanged."""

    ingestion_complete: typing.Union[typing.Literal[True], NotSetType] = NotSet
    """Set to True to mark file as fully ingested, or NotSet to leave unchanged."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


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


class QueryDatasetFilesRequest(pydantic.BaseModel):
    """Request payload for listing the files associated with a dataset, an org, or a device.

    Supports gitignore-style patterns for flexible file selection and pagination. Despite
    the name, the same body lists the files of any association type.
    """

    page_token: typing.Optional[str] = None
    """Token for retrieving the next page of results in paginated queries."""

    include_patterns: typing.Optional[list[str]] = None
    """List of gitignore-style patterns for files to include in results."""

    exclude_patterns: typing.Optional[list[str]] = None
    """List of gitignore-style patterns for files to exclude from results."""

    limit: typing.Optional[int] = None
    """Maximum number of files to return per page."""

    sort_by: typing.Optional[str] = None
    """Field to sort results by. Defaults to 'created'."""

    sort_direction: typing.Optional[str] = None
    """Sort direction ('ASC' or 'DESC'). Defaults to 'DESC'."""


class RenameDirectoryRequest(pydantic.BaseModel):
    """Request payload for renaming a directory among the files of one association.

    Changes the path of a directory and all its contained files. This updates the
    logical organization without moving actual file content.
    """

    new_path: str
    """New path for the directory."""

    old_path: str
    """Current path of the directory to rename."""
