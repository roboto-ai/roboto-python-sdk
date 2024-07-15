# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing
from typing import Any, Optional

import pydantic

from ...time import utcnow
from ..files import S3Credentials


class DatasetBucketAdministrator(str, enum.Enum):
    # Other supported type would be "Customer"
    Roboto = "Roboto"


class DatasetCredentials(pydantic.BaseModel):
    access_key_id: str
    bucket: str
    expiration: datetime.datetime
    secret_access_key: str
    session_token: str
    region: str
    required_prefix: str

    def is_expired(self) -> bool:
        return utcnow() >= self.expiration

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_s3_credentials(self) -> S3Credentials:
        return {
            "access_key": self.access_key_id,
            "secret_key": self.secret_access_key,
            "token": self.session_token,
            "expiry_time": self.expiration.isoformat(),
            "region": self.region,
        }


class DatasetStorageLocation(str, enum.Enum):
    # Other supported locations might be "GCP" or "Azure"
    S3 = "S3"


class DatasetS3StorageCtx(pydantic.BaseModel):
    bucket_name: str
    iam_role_arn: str
    key_prefix: str


# https://www.google.com/search?q=pydantic.Field+default_factory+not+evaluated+in+parse_obj&rlz=1C5CHFA_enUS1054US1054&oq=pydantic.Field+default_factory+not+evaluated+in+parse_obj&aqs=chrome..69i57j33i160.6235j0j7&sourceid=chrome&ie=UTF-8
StorageCtxType = typing.Optional[DatasetS3StorageCtx]


class DatasetRecord(pydantic.BaseModel):
    administrator: DatasetBucketAdministrator
    created: datetime.datetime
    created_by: str
    dataset_id: str  # sort key
    description: Optional[str] = None
    device_id: Optional[str] = None
    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    modified: datetime.datetime
    modified_by: str
    org_id: str  # partition key
    roboto_record_version: int = 0  # A protected field, incremented on every update
    storage_ctx: StorageCtxType = None
    storage_location: DatasetStorageLocation
    tags: list[str] = pydantic.Field(default_factory=list)

    @staticmethod
    def storage_ctx_from_dict(ctx_dict: dict[str, typing.Any]) -> StorageCtxType:
        """
        Used to cast a dict representation of StorageCtxType into an appropriate pydantic model. Will return None
        if the empty dict (default representation) is provided, and will throw an exception if some fields are set,
        but they don't match a known storage ctx pydantic model.
        """
        if ctx_dict == {}:
            return None

        return DatasetS3StorageCtx.model_validate(ctx_dict)


class TransactionType(str, enum.Enum):
    FileUpload = "file_upload"


class TransactionStatus(str, enum.Enum):
    Pending = "pending"
    Completed = "completed"


class TransactionRecordV1(pydantic.BaseModel):
    """
    This is the model that is returned by the v1 API.
    It is deprecated and should not be used.
    Use TransactionRecord instead.
    """

    org_id: str
    transaction_id: str
    transaction_type: TransactionType
    transaction_status: TransactionStatus  # This field is deprecated
    origination: str
    resource_count: int = 0
    expected_resource_count: typing.Optional[int] = None
    created: datetime.datetime
    created_by: str
    modified: datetime.datetime
    modified_by: str = "This field is deprecated"


class TransactionRecord(pydantic.BaseModel):
    org_id: str
    transaction_id: str
    transaction_type: TransactionType
    origination: str
    expected_resource_count: typing.Optional[int] = None
    resource_manifest: typing.Optional[set[str]] = None
    created: datetime.datetime
    created_by: str
    modified: datetime.datetime
