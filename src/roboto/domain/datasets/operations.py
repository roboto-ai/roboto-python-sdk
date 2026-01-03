# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic
from pydantic import ConfigDict

from ...pydantic import (
    remove_non_noneable_init_args,
)
from ...sentinels import NotSet, NotSetType
from ...updates import MetadataChangeset


class BeginSingleFileUploadRequest(pydantic.BaseModel):
    """
    Request payload to begin a single file upload
    """

    origination: typing.Optional[str] = pydantic.Field(
        description="Additional information about what uploaded the file, e.g. `roboto client v1.0.0`.",
        default=None,
    )
    file_path: str = pydantic.Field(
        description="The destination path to upload the file to in the dataset, e.g. `recording.bag`"
        + "or `path/to/metadata.json`.",
    )
    file_size: int = pydantic.Field(description="The size of the file in bytes.")


class BeginSingleFileUploadResponse(pydantic.BaseModel):
    """
    Response to a single file upload
    """

    upload_id: str
    upload_url: str


class BeginManifestTransactionRequest(pydantic.BaseModel):
    """
    Request payload to begin a manifest-based transaction
    """

    origination: str
    """Additional information about what uploaded the file, e.g. `roboto client v1.0.0`."""

    device_id: typing.Optional[str] = None
    """The ID of the device which created this dataset, if applicable."""

    resource_manifest: dict[str, int]
    """Dictionary mapping destination file paths to file sizes in bytes."""


class BeginManifestTransactionResponse(pydantic.BaseModel):
    """
    Response to a manifest-based transaction request
    """

    transaction_id: str
    upload_mappings: dict[str, str]


class CreateDatasetRequest(pydantic.BaseModel):
    """Request payload for creating a new dataset.

    Used to specify the initial properties of a dataset during creation,
    including optional metadata, tags, name, and description.
    """

    description: typing.Optional[str] = pydantic.Field(
        default=None,
        description="An optional human-readable description for this dataset.",
    )
    """Optional human-readable description of the dataset."""

    device_id: typing.Optional[str] = pydantic.Field(
        default=None,
        description="The ID of the device which created this dataset, if applicable.",
    )
    """Optional identifier of the device that generated this data."""

    name: typing.Optional[str] = pydantic.Field(
        default=None,
        description="A short name for this dataset. Must be under 120 characters or less.",
        max_length=120,
    )
    """Optional short name for the dataset (max 120 characters)."""

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this dataset for discovery and search, e.g. "
        + "`{ 'softwareVersion': '3.1.4' }`",
    )
    """Key-value metadata pairs to associate with the dataset for discovery and search."""

    tags: list[str] = pydantic.Field(
        default_factory=list,
        description="Initial tags to associate with this dataset for discovery and search, e.g. "
        + "`['sunny', 'campaign5']`",
    )
    """List of tags for dataset discovery and organization."""

    def __init__(self, **data):
        super().__init__(**remove_non_noneable_init_args(data, self))


class QueryDatasetFilesRequest(pydantic.BaseModel):
    """Request payload for querying files within a dataset.

    Used to retrieve files from a dataset with optional pattern-based filtering
    and pagination support. Supports gitignore-style patterns for flexible
    file selection.
    """

    page_token: typing.Optional[str] = None
    """Token for retrieving the next page of results in paginated queries."""

    include_patterns: typing.Optional[list[str]] = None
    """List of gitignore-style patterns for files to include in results."""

    exclude_patterns: typing.Optional[list[str]] = None
    """List of gitignore-style patterns for files to exclude from results."""


class QueryDatasetsRequest(pydantic.BaseModel):
    """Request payload for querying datasets with filters.

    Used to search for datasets based on various criteria such as metadata,
    tags, and other dataset properties. The filters are applied server-side
    to efficiently return matching datasets.
    """

    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Dictionary of filter criteria to apply when searching for datasets."""

    model_config = ConfigDict(extra="ignore")


class ReportTransactionProgressRequest(pydantic.BaseModel):
    """Request payload for reporting file upload transaction progress.

    Used to notify the platform about the completion status of individual
    files within a batch upload transaction. This enables progress tracking
    and partial completion handling for large file uploads.
    """

    manifest_items: list[str]
    """List of manifest item identifiers that have completed upload."""


class UpdateDatasetRequest(pydantic.BaseModel):
    """Request payload for updating dataset properties.

    Used to modify dataset metadata, description, name, and other properties.
    Only specified fields will be updated; others remain unchanged.
    """

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Metadata changes to apply (add, update, or remove fields/tags)."""

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New description for the dataset. Set to None to clear the description."""

    device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New device ID for the dataset. Set to None to clear the device association."""

    name: typing.Optional[
        typing.Union[typing.Annotated[str, pydantic.StringConstraints(max_length=120)], NotSetType]
    ] = NotSet
    """New name for the dataset (max 120 characters). Set to None to clear the name."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class BeginTransactionRequest(pydantic.BaseModel):
    """Request payload for beginning a file upload transaction.

    Used to initiate a transaction for uploading multiple files to a dataset.
    Transactions help coordinate batch uploads and provide progress tracking.
    """

    origination: str
    """Description of the upload source (e.g., 'roboto client v1.0.0')."""

    expected_resource_count: typing.Optional[int] = None
    """Optional expected number of resources to be uploaded in this transaction."""


class TransactionCompletionResponse(pydantic.BaseModel):
    """Response indicating the completion status of a transaction.

    Provides information about whether a file upload transaction has been
    fully completed, including all associated file processing.
    """

    is_complete: bool
    """Whether the transaction has been fully completed."""


class DeleteDirectoriesRequest(pydantic.BaseModel):
    """Request payload for deleting directories within a dataset.

    Used to remove entire directory structures and all contained files
    from a dataset. This is a bulk operation that affects multiple files.
    """

    directory_paths: list[str]
    """List of directory paths to delete from the dataset."""


class RenameDirectoryRequest(pydantic.BaseModel):
    """Request payload for renaming a directory within a dataset.

    Used to change the path of a directory and all its contained files
    within a dataset. This updates the logical organization without
    moving actual file content.
    """

    new_path: str
    """New path for the directory."""

    old_path: str
    """Current path of the directory to rename."""


class CreateDirectoryRequest(pydantic.BaseModel):
    """
    Request payload to create a directory in a dataset
    """

    name: str
    error_if_exists: bool = False
    parent_path: typing.Optional[str] = None
    origination: typing.Optional[str] = None
    create_intermediate_dirs: bool = False
    """If True, creates intermediate directories in the path if they don't exist.
    If False, requires all parent directories to already exist."""


class CreateDatasetIfNotExistsRequest(pydantic.BaseModel):
    """Request payload to create a dataset if no existing dataset matches
    the specified query.

    Searches for existing datasets using the provided RoboQL query. If a matching
    dataset is found, returns that dataset. If no match is found, creates a new
    dataset with the specified properties and returns it.
    """

    match_roboql_query: str
    create_request: CreateDatasetRequest
