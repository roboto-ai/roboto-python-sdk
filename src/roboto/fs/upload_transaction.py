# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import pathlib
import sys
import types
import typing

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from ..association import Association
from ..env import RobotoEnv
from ..exceptions import RobotoInternalException
from ..http import RobotoClient
from ..logging import default_logger
from ..version import roboto_version
from .api_operations import BeginUploadRequest, BeginUploadResponse, ReportUploadProgressRequest
from .credentials import RobotoCredentials
from .object_store import (
    CredentialProvider,
    Credentials,
    FutureLike,
)

logger = default_logger()


class TransactionFile(typing.TypedDict):
    local_path: pathlib.Path
    destination_path: str
    file_size: int


class UploadableFile(typing.TypedDict):
    local_path: pathlib.Path
    destination_path: str
    upload_uri: str


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
        self.__device_id = device_id

        if origination is None:
            origination = RobotoEnv.default().roboto_env or f"roboto {roboto_version()}"
        self.__origination = origination

        self.__batch_size = batch_size if batch_size is not None else max(len(items), 1)

        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__caller_org_id = caller_org_id

        self.__transaction_id: typing.Optional[str] = None
        self.__upload_mappings: typing.Optional[dict[str, str]] = None

        self.__completed_upload_node_ids: list[str] = []

        self.__pending_uploads: list[tuple[UploadableFile, FutureLike[None]]] = []

    def __enter__(self) -> UploadTransaction:
        resource_manifest = {file["destination_path"]: file["file_size"] for file in self.__items}
        request = BeginUploadRequest(
            association=self.__association,
            origination=self.__origination,
            resource_manifest=resource_manifest,
            device_id=self.__device_id,
        )

        response = self.__roboto_client.post(
            "v1/files/upload",
            data=request,
            caller_org_id=self.__caller_org_id,
        ).to_record(BeginUploadResponse)

        self.__transaction_id = response.transaction_id
        self.__upload_mappings = response.upload_mappings

        return self

    def __exit__(
        self,
        exc_type: typing.Optional[typing.Type[BaseException]],
        exc_value: typing.Optional[BaseException],
        traceback: typing.Optional[types.TracebackType],
    ):
        if self.__pending_uploads:
            logger.warning(
                f"UploadTransaction exiting with {len(self.__pending_uploads)} "
                "pending uploads. Did you forget to call await_uploads()?"
            )

        if not exc_value:
            # GM(2025-11-18)
            # This matches current Dataset::upload behavior of only completing the transaction if there are no errors.
            self.__finalize()

    def __iter__(self) -> typing.Generator[UploadableFile, None, None]:
        """
        Yields files to upload in batches based on batch_size.

        After each batch is fully yielded, await_uploads() is called automatically
        to wait for all registered uploads in that batch to complete and report
        progress to the API.

        The caller must call register_upload() for each file after initiating
        the S3 transfer. The await_uploads() call at batch boundaries will handle
        waiting for completion and flushing progress.
        """
        for batch_start in range(0, len(self.__items), self.__batch_size):
            batch = self.__items[batch_start : batch_start + self.__batch_size]
            for item in batch:
                yield {
                    "local_path": item["local_path"],
                    "destination_path": item["destination_path"],
                    "upload_uri": self.upload_mappings[item["destination_path"]],
                }
            # After all files in batch are yielded and uploads registered,
            # wait for completion and report progress to API
            self.await_uploads()

    @property
    def completed_upload_node_ids(self) -> list[str]:
        return self.__completed_upload_node_ids

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

    def await_uploads(self) -> None:
        """
        Wait for all registered uploads to complete, then report progress to API.

        Must be called while still inside the object_store context manager,
        since the transfer manager may be shut down when that context exits.

        Raises:
            ExceptionGroup: If any uploads fail, an ExceptionGroup containing all
                           upload errors is raised after reporting successfully
                           completed uploads.
        """
        if not self.__pending_uploads:
            return

        completed: list[UploadableFile] = []
        errors: list[Exception] = []

        for file, future in self.__pending_uploads:
            try:
                future.result()
                completed.append(file)
            except Exception as e:
                logger.error("Upload failed: %s", file["destination_path"], exc_info=e)
                errors.append(e)

        # Report successfully completed uploads to the API
        if completed:
            self.__flush(completed)

        self.__pending_uploads.clear()

        # After reporting successes, raise all errors encountered
        if errors:
            raise ExceptionGroup("One or more uploads failed", errors)

    def make_credential_provider(self) -> CredentialProvider:
        def _get_upload_credentials() -> Credentials:
            response = self.__roboto_client.get(f"v1/files/upload/{self.transaction_id}/credentials").to_record_list(
                RobotoCredentials
            )

            if len(response) == 0:
                raise RobotoInternalException(f"Unable to get upload credentials for transaction {self.transaction_id}")

            creds = response[0]
            return creds.to_object_store_credentials()

        return _get_upload_credentials

    def register_upload(self, file: UploadableFile, future: FutureLike[None]) -> None:
        """
        Register a pending upload future.

        Call this immediately after initiating each S3 transfer.
        The future will be awaited when await_uploads() is called.
        """
        self.__pending_uploads.append((file, future))

    def __finalize(self):
        self.__roboto_client.put(f"v1/files/upload/{self.transaction_id}/complete")

    def __flush(self, batch: list[UploadableFile]):
        manifest_items = [file["upload_uri"] for file in batch]
        response = self.__roboto_client.put(
            f"v1/files/upload/{self.transaction_id}/progress",
            data=ReportUploadProgressRequest(
                manifest_items=manifest_items,
            ),
        )
        node_ids = response.to_string_list()
        self.__completed_upload_node_ids.extend(node_ids)
