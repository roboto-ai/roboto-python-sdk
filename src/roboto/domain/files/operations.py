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
    uri: str


class FileRecordRequest(pydantic.BaseModel):
    """Upsert a file record."""

    file_id: str
    tags: list[str] = pydantic.Field(default_factory=list)
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class ImportFileRequest(pydantic.BaseModel):
    dataset_id: str
    description: typing.Optional[str] = None
    relative_path: str
    size: int
    uri: str


class QueryFilesRequest(pydantic.BaseModel):
    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class RenameFileRequest(pydantic.BaseModel):
    association_id: str
    new_path: str


class SignedUrlResponse(pydantic.BaseModel):
    url: str


class UpdateFileRecordRequest(pydantic.BaseModel):
    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet

    model_config = pydantic.ConfigDict(
        extra="forbid", json_schema_extra=NotSetType.openapi_schema_modifier
    )


class DirectoryContentsPage(pydantic.BaseModel):
    files: collections.abc.Sequence[FileRecord]
    directories: collections.abc.Sequence[DirectoryRecord]
    next_token: typing.Optional[str] = None
