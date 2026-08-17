# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import sys
import typing

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from ..association import Association
from ..http import RobotoClient
from ..logging import default_logger
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

logger = default_logger()

_DEFAULT_UPLOAD_BATCH_SIZE = 500
_MAX_DOWNLOAD_ATTEMPTS = 3


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
    ) -> dict[pathlib.Path, str]:
        """Upload the given files and return which file record each one created.

        Returns:
            Mapping from each uploaded local path to the ID of the file record it created.

        Raises:
            ValueError: If two of the given files resolve to the same destination path: their
                uploads would overwrite each other and only one could appear in the returned
                mapping. Files without a ``destination_paths`` entry are destined for their own
                basename, so two like-named files from different directories collide unless given
                distinct destinations.
            OSError: If a given file cannot be read.
        """
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
            return {}

        # Destination collisions are checked over the full item list, before the loop below splits
        # it into batch_size slices; each UploadTransaction receives one slice, so no transaction
        # could see a collision that spans two batches. Two paths sharing one destination collapse
        # to a single upload URI: their transfers race for the same object and only one can appear
        # in the returned path -> file-ID mapping.
        local_paths_by_destination: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
        for item in items:
            local_paths_by_destination[item["destination_path"]].append(item["local_path"])
        collisions = {
            destination: local_paths
            for destination, local_paths in local_paths_by_destination.items()
            if len(local_paths) > 1
        }
        if collisions:
            details = "; ".join(
                f"{destination!r} <- {', '.join(str(local_path) for local_path in local_paths)}"
                for destination, local_paths in sorted(collisions.items())
            )
            raise ValueError(
                f"Multiple files resolve to the same upload destination: {details}. "
                "Give each file a distinct destination via destination_paths."
            )

        # GM(2025-11-19)
        # For reasons related to OpenFGA scalability/throughput,
        # upload transactions are currently limited to 500 files.
        # Until that is fixed, implement batching by creating multiple transactions.
        # When that is lifted, batching is already handled by the UploadTransaction.
        completed_uploads: dict[pathlib.Path, str] = {}
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

                completed_uploads.update(txn.completed_uploads)

        return completed_uploads

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

            with object_store:
                pending = list(bucket_files)
                for attempt in range(1, _MAX_DOWNLOAD_ATTEMPTS + 1):
                    for file in pending:
                        future = object_store.get(file["source_uri"], file["destination_path"], on_progress=on_progress)
                        download_session.register_download(file, future)

                    failed = download_session.await_downloads()
                    if not failed:
                        break

                    pending = [file for file, _ in failed]
                    if attempt < _MAX_DOWNLOAD_ATTEMPTS:
                        logger.warning(
                            "Retrying %d failed download(s) (attempt %d/%d)",
                            len(pending),
                            attempt + 1,
                            _MAX_DOWNLOAD_ATTEMPTS,
                        )

                if failed:
                    raise ExceptionGroup(
                        "One or more downloads failed after retries",
                        [exc for _, exc in failed],
                    )
