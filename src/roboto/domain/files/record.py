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

# Python 3.8/3.9 compatible import of TypeAlias
try:
    from typing import TypeAlias
except ImportError:
    try:
        from typing_extensions import TypeAlias
    except ImportError:
        pass


class FileStatus(str, enum.Enum):
    Available = "available"
    Deleted = "deleted"
    Reserved = "reserved"


class IngestionStatus(str, enum.Enum):
    NotIngested = "not_ingested"
    Ingested = "ingested"


class FileRecord(pydantic.BaseModel):
    association_id: (
        str  # e.g. dataset_id, collection_id, etc.; GSI PK of "association_id" index.
    )
    device_id: typing.Optional[str] = None
    file_id: str  # Table PK
    modified: datetime.datetime  # Persisted as ISO 8601 string in UTC
    relative_path: (
        str  # path relative to some common prefix. Used as local path when downloaded.
    )
    size: int  # bytes
    org_id: str
    uri: str  # GSI PK of "uri" index; GSI SK of "association_id" index
    status: FileStatus = FileStatus.Available
    upload_id: str = "NO_ID"  # Defaulted for backwards compatability
    origination: str = ""  # Defaulted for compatibility
    created_by: str = ""
    tags: list[str] = pydantic.Field(default_factory=list)
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    description: typing.Optional[str] = None
    ingestion_status: IngestionStatus = IngestionStatus.NotIngested

    @property
    def bucket(self) -> str:
        parsed_uri = urllib.parse.urlparse(self.uri)
        return parsed_uri.netloc

    @property
    def key(self) -> str:
        parsed_uri = urllib.parse.urlparse(self.uri)
        return parsed_uri.path.lstrip("/")


class FileTag(enum.Enum):
    DatasetId = "dataset_id"
    OrgId = "org_id"
    # Path to file relative to common prefix
    CommonPrefix = "common_prefix"
    TransactionId = "transaction_id"


class S3Credentials(typing.TypedDict):
    """
    This interface is driven by botocore.credentials.RefreshableCredentials
    """

    access_key: str
    secret_key: str
    token: str
    region: str
    expiry_time: typing.Optional[str]


CredentialProvider: TypeAlias = typing.Callable[[], S3Credentials]


class DirectoryRecord(pydantic.BaseModel):
    name: str
