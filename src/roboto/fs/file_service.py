# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

from ..association import Association
from ..http import RobotoClient
from .download_session import (
    DownloadableFile,
    DownloadSession,
)
from .object_store import (
    OnProgress,
    StoreRegistry,
)
from .upload_transaction import (
    TransactionFile,
    UploadTransaction,
)

_DEFAULT_UPLOAD_BATCH_SIZE = 500


class FileService:
    """Application service for performing upload and download to the Roboto Platform.

    Agnostic to object store provider.
    """

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        object_store_registry: typing.Optional[StoreRegistry] = None,
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__object_store_registry = object_store_registry or StoreRegistry

    def upload(
        self,
        files: collections.abc.Iterable[pathlib.Path],
        association: Association,
        destination_paths: collections.abc.Mapping[pathlib.Path, str] = {},
        batch_size: int = _DEFAULT_UPLOAD_BATCH_SIZE,
        device_id: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        on_progress: typing.Optional[OnProgress] = None,
    ) -> list[str]:
        items: list[TransactionFile] = []
        for local_path in files:
            try:
                file_size = local_path.stat().st_size
            except OSError as e:
                raise OSError(f"Cannot upload file '{local_path}': {str(e)}") from None

            items.append(
                {
                    "local_path": local_path,
                    "destination_path": destination_paths.get(local_path, local_path.name),
                    "file_size": file_size,
                }
            )

        if not items:
            return []

        # GM(2025-11-19)
        # For reasons related to OpenFGA scalability/throughput,
        # upload transactions are currently limited to 500 files.
        # Until that is fixed, implement batching by creating multiple transactions.
        # When that is lifted, batching is already handled by the UploadTransaction.
        completed_upload_node_ids: list[str] = []
        for batch_start in range(0, len(items), batch_size):
            item_batch = items[batch_start : batch_start + batch_size]

            with UploadTransaction(
                item_batch,
                association,
                device_id=device_id,
                batch_size=batch_size,
                roboto_client=self.__roboto_client,
                caller_org_id=caller_org_id,
            ) as txn:
                # Heuristic: all files in a transaction are located in the same object store.
                # When this no longer holds, this is the place to change it.
                first_file_uri = list(txn.upload_mappings.values())[0]

                object_store = self.__object_store_registry.get_store_for_uri(
                    first_file_uri, txn.make_credential_provider()
                )
                with object_store:
                    for file in txn:
                        future = object_store.put(file["local_path"], file["upload_uri"], on_progress=on_progress)
                        txn.register_upload(file, future)

                completed_upload_node_ids.extend(txn.completed_upload_node_ids)

        return completed_upload_node_ids

    def download(
        self,
        files: collections.abc.Sequence[DownloadableFile],
        association: Association,
        caller_org_id: typing.Optional[str] = None,
        on_progress: typing.Optional[OnProgress] = None,
    ) -> None:
        """Download files from the Roboto Platform.

        Args:
            files: Sequence of files to download, each with source_uri and destination_path.
            association: Association of the files to download.
            caller_org_id: Optional organization ID for cross-org access.
            on_progress: Optional callback to be periodically called with the number of bytes downloaded.
        """
        if not files:
            return

        files_grouped_by_bucket = collections.defaultdict(list)
        for file in files:
            files_grouped_by_bucket[file["bucket_name"]].append(file)

        for bucket_name, bucket_files in files_grouped_by_bucket.items():
            download_session = DownloadSession(
                items=bucket_files,
                association=association,
                roboto_client=self.__roboto_client,
                caller_org_id=caller_org_id,
            )
            # Heuristic: all files in the same bucket are located in the same object store
            first_file_uri = bucket_files[0]["source_uri"]
            object_store = self.__object_store_registry.get_store_for_uri(
                first_file_uri, download_session.make_credential_provider(bucket_name)
            )

            with object_store, download_session:
                for file in bucket_files:
                    future = object_store.get(file["source_uri"], file["destination_path"], on_progress=on_progress)
                    download_session.register_download(file, future)
