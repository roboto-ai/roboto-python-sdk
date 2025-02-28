# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

import pydantic

from ...auth import Permissions
from ...exceptions import RobotoInternalException
from ...http.roboto_client import RobotoClient
from ...time import utcnow


class S3Credentials(typing.TypedDict):
    """
    This interface is driven by botocore.credentials.RefreshableCredentials
    """

    access_key: str
    secret_key: str
    token: str
    region: str
    expiry_time: typing.Optional[str]


class DatasetCredentials(pydantic.BaseModel):
    """
    Handle credentials for dataset file access
    """

    access_key_id: str
    bucket: str
    expiration: datetime.datetime
    secret_access_key: str
    session_token: str
    region: str
    required_prefix: str

    def is_expired(self) -> bool:
        return utcnow() >= self.expiration

    def to_dict(self) -> dict[str, typing.Any]:
        return self.model_dump(mode="json")

    def to_s3_credentials(self) -> S3Credentials:
        return {
            "access_key": self.access_key_id,
            "secret_key": self.secret_access_key,
            "token": self.session_token,
            "expiry_time": self.expiration.isoformat(),
            "region": self.region,
        }


CredentialProvider: typing.TypeAlias = typing.Callable[[], S3Credentials]


class FileCredentialsHelper:
    """
    Helper class for retrieving credentials used to download and upload files to/from Roboto.
    """

    __roboto_client: RobotoClient

    def __init__(self, roboto_client: RobotoClient):
        self.__roboto_client = roboto_client

    def get_dataset_creds(
        self,
        dataset_id: str,
        permissions: Permissions,
        transaction_id: typing.Optional[str] = None,
    ) -> collections.abc.Sequence[DatasetCredentials]:
        query_params = {"mode": permissions.value}

        if transaction_id:
            query_params["transaction_id"] = transaction_id

        return self.__roboto_client.get(
            f"v1/datasets/id/{dataset_id}/credentials", query=query_params
        ).to_record_list(DatasetCredentials)

    def get_dataset_download_creds_provider(
        self, dataset_id: str, bucket_name: str
    ) -> CredentialProvider:
        def _wrapped():
            all_creds = self.get_dataset_creds(dataset_id, Permissions.ReadOnly)
            filtered = [cred for cred in all_creds if cred.bucket == bucket_name]

            if len(filtered) == 0:
                raise RobotoInternalException(
                    f"Dataset {dataset_id} has no read creds for bucket {bucket_name}."
                )

            return filtered[0].to_s3_credentials()

        return _wrapped

    def get_dataset_upload_creds_provider(self, dataset_id: str, transaction_id: str):
        def _wrapped():
            all_creds = self.get_dataset_creds(
                dataset_id=dataset_id,
                permissions=Permissions.ReadWrite,
                transaction_id=transaction_id,
            )

            if len(all_creds) == 0:
                raise RobotoInternalException(
                    f"Dataset {dataset_id} has no write creds."
                )

            return all_creds[0].to_s3_credentials()

        return _wrapped
