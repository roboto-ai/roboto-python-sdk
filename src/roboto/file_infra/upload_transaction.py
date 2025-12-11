# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import pathlib
import types
import typing

import pydantic

from ..association import Association
from ..auth import Permissions
from ..env import RobotoEnv
from ..exceptions import RobotoInternalException
from ..http import RobotoClient
from ..version import roboto_version
from .object_store import (
    CredentialProvider,
    Credentials,
)


class TransactionFile(typing.TypedDict):
    local_path: pathlib.Path
    destination_path: str
    file_size: int


class UploadableFile(typing.TypedDict):
    local_path: pathlib.Path
    destination_path: str
    upload_uri: str


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


class ReportTransactionProgressRequest(pydantic.BaseModel):
    """Request payload for reporting file upload transaction progress.

    Used to notify the platform about the completion status of individual
    files within a batch upload transaction. This enables progress tracking
    and partial completion handling for large file uploads.
    """

    manifest_items: list[str]
    """List of manifest item identifiers that have completed upload."""


class RobotoCredentials(pydantic.BaseModel):
    """
    Credentials returned from the Roboto Platform
    """

    access_key_id: str
    expiration: datetime.datetime
    secret_access_key: str
    session_token: str
    region: str

    def to_upload_credentials(self) -> Credentials:
        return {
            "access_key": self.access_key_id,
            "secret_key": self.secret_access_key,
            "token": self.session_token,
            "expiry_time": self.expiration.isoformat(),
            "region": self.region,
        }


class UploadTransaction:
    def __init__(
        self,
        items: collections.abc.Sequence[TransactionFile],
        association: Association,
        device_id: typing.Optional[str] = None,
        origination: typing.Optional[str] = None,
        batch_size: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        caller_org_id: typing.Optional[str] = None,
    ):
        self.__items = items

        self.__association = association
        if not self.__association.is_dataset:
            raise ValueError("Roboto currently only supports uploading files to datasets.")

        self.__device_id = device_id

        if origination is None:
            origination = RobotoEnv.default().roboto_env or f"roboto {roboto_version()}"
        self.__origination = origination

        self.__batch_size = batch_size if batch_size is not None else len(items)

        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__caller_org_id = caller_org_id

        self.__transaction_id: typing.Optional[str] = None
        self.__upload_mappings: typing.Optional[dict[str, str]] = None

        self.__completed_upload_node_ids: list[str] = []

    def __enter__(self) -> UploadTransaction:
        resource_manifest = {file["destination_path"]: file["file_size"] for file in self.__items}
        request = BeginManifestTransactionRequest(
            origination=self.__origination,
            resource_manifest=resource_manifest,
            device_id=self.__device_id,
        )

        response = self.__roboto_client.post(
            f"v2/datasets/{self.__dataset_id}/batch_uploads",
            data=request,
            caller_org_id=self.__caller_org_id,
        ).to_record(BeginManifestTransactionResponse)

        self.__transaction_id = response.transaction_id
        self.__upload_mappings = response.upload_mappings

        return self

    def __exit__(
        self,
        exc_type: typing.Optional[typing.Type[BaseException]],
        exc_value: typing.Optional[BaseException],
        traceback: typing.Optional[types.TracebackType],
    ):
        if not exc_value:
            # GM(2025-11-18)
            # This matches current Dataset::upload behavior of only completing the transaction if there are no errors.
            self.__finalize()

    def __iter__(self) -> typing.Generator[UploadableFile, None, None]:
        for batch_start in range(0, len(self.__items), self.__batch_size):
            txn_batch = self.__items[batch_start : batch_start + self.__batch_size]
            uploaded: list[UploadableFile] = []
            for path in txn_batch:
                uploadable: UploadableFile = {
                    "local_path": path["local_path"],
                    "destination_path": path["destination_path"],
                    "upload_uri": self.upload_mappings[path["destination_path"]],
                }
                yield uploadable
                uploaded.append(uploadable)

            self.__flush(uploaded)

    @property
    def completed_upload_node_ids(self) -> list[str]:
        return self.__completed_upload_node_ids

    @property
    def credential_provider(self) -> CredentialProvider:
        def _get_upload_credentials() -> Credentials:
            query_params = {
                "mode": Permissions.ReadWrite.value,
                "transaction_id": self.transaction_id,
            }
            response = self.__roboto_client.get(
                f"v1/datasets/id/{self.__dataset_id}/credentials", query=query_params
            ).to_record_list(RobotoCredentials)

            if len(response) == 0:
                raise RobotoInternalException(f"Unable to get upload credentials for {self.__association!r}")

            creds = response[0]
            return creds.to_upload_credentials()

        return _get_upload_credentials

    @property
    def transaction_id(self) -> str:
        if self.__transaction_id is None:
            raise Exception("An UploadTransaction must be used as a context manager.")

        return self.__transaction_id

    @property
    def upload_mappings(self) -> dict[str, str]:
        if self.__upload_mappings is None:
            raise Exception("An UploadTransaction must be used as a context manager.")

        return self.__upload_mappings

    @property
    def __dataset_id(self) -> str:
        dataset_id = self.__association.dataset_id
        if dataset_id is None:
            raise ValueError("Roboto currently only supports uploading files to datasets.")
        return dataset_id

    def __finalize(self):
        self.__roboto_client.put(f"v2/datasets/{self.__dataset_id}/batch_uploads/{self.transaction_id}/complete")

    def __flush(self, batch: list[UploadableFile]):
        manifest_items = [file["upload_uri"] for file in batch]
        response = self.__roboto_client.put(
            f"v2/datasets/{self.__dataset_id}/batch_uploads/{self.transaction_id}/progress",
            data=ReportTransactionProgressRequest(
                manifest_items=manifest_items,
            ),
        )
        node_ids = response.to_string_list()
        self.__completed_upload_node_ids.extend(node_ids)
