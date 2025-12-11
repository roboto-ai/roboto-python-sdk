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
from .object_store import (
    FutureLike,
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
                # Heuristic: all files in a transaction are uploaded to the same object store.
                first_file_uri = list(txn.upload_mappings.values())[0]

                object_store = self.__object_store_registry.get_store_for_uri(first_file_uri, txn.credential_provider)
                with object_store:
                    futures: list[FutureLike[None]] = []
                    for file in txn:
                        future = object_store.put(file["local_path"], file["upload_uri"])
                        futures.append(future)

                    for future in futures:
                        future.result()

                completed_upload_node_ids.extend(txn.completed_upload_node_ids)

        return completed_upload_node_ids
