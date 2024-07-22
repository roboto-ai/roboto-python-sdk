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
from ...updates import (
    MetadataChangeset,
    UpdateCondition,
)
from .record import (
    TransactionRecord,
    TransactionType,
)


class BeginSingleFileUploadRequest(pydantic.BaseModel):
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
    upload_id: str
    upload_url: str


class BeginManifestTransactionRequest(pydantic.BaseModel):
    origination: str
    resource_manifest: dict[str, int]


class BeginManifestTransactionResponse(pydantic.BaseModel):
    record: TransactionRecord
    upload_mappings: dict[str, str]


class CreateDatasetRequest(pydantic.BaseModel):
    description: typing.Optional[str] = pydantic.Field(
        default=None,
        description="An optional human-readable description for this dataset.",
    )
    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this dataset for discovery and search, e.g. "
        + "`{ 'softwareVersion': '3.1.4' }`",
    )
    tags: list[str] = pydantic.Field(
        default_factory=list,
        description="Initial tags to associate with this dataset for discovery and search, e.g. "
        + "`['sunny', 'campaign5']`",
    )

    def __init__(self, **data):
        super().__init__(**remove_non_noneable_init_args(data, self))


class QueryDatasetFilesRequest(pydantic.BaseModel):
    page_token: typing.Optional[str] = None
    include_patterns: typing.Optional[list[str]] = None
    exclude_patterns: typing.Optional[list[str]] = None


class QueryDatasetsRequest(pydantic.BaseModel):
    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class ReportTransactionProgressRequest(pydantic.BaseModel):
    manifest_items: list[str]


class UpdateDatasetRequest(pydantic.BaseModel):
    metadata_changeset: typing.Optional[MetadataChangeset] = None
    description: typing.Optional[str] = None
    conditions: typing.Optional[list[UpdateCondition]] = None


class BeginTransactionRequest(pydantic.BaseModel):
    transaction_type: TransactionType
    origination: str
    expected_resource_count: typing.Optional[int] = None


class TransactionCompletionResponse(pydantic.BaseModel):
    is_complete: bool


class DeleteDirectoriesRequest(pydantic.BaseModel):
    directory_paths: list[str]


class RenameFileRequest(pydantic.BaseModel):
    old_path: str
    new_path: str


class RenameDirectoryRequest(pydantic.BaseModel):
    new_path: str
    old_path: str
