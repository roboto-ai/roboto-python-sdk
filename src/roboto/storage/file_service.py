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
    """Service that uploads local files to Roboto and downloads files Roboto stores to local disk.

    :py:meth:`~roboto.domain.datasets.Dataset.upload_files`, :py:meth:`~roboto.domain.files.File.download` and the
    other upload and download methods transfer files through it, so most code never calls it. It moves file contents
    directly to and from the object store that holds them, such as an S3 bucket, with temporary credentials Roboto
    issues.

    Args:
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        object_store_registry: Registry that picks the object store for a storage URI by its scheme. Defaults to
            :py:class:`~roboto.storage.object_store.StoreRegistry`.
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
        """Upload local files to a dataset or another resource, and return the ID of the file each one created.

        The files upload in batches of ``batch_size``. Each batch is one upload transaction, which Roboto completes
        before the next batch begins.

        Args:
            files: Local files to upload.
            association: Resource to upload the files to: a dataset, device, device type, organization, or topic.
            destination_paths: Path within ``association`` to upload each local file to, keyed by local path. A file
                not in the mapping is uploaded to the root under its own name.
            batch_size: Maximum number of files per upload transaction.
            device_id: ID of the device that produced the files, which must be in the organization the files are
                uploaded to. ``None`` records the calling device when a device makes the request, and no device
                otherwise.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            on_progress: Function called with the number of bytes uploaded since its previous call. ``None`` reports
                no progress.

        Returns:
            ID of the file each local path was uploaded as, keyed by local path.

        Raises:
            ValueError: Two local files would be uploaded to the same path, which includes two files of the same name
                from different directories that ``destination_paths`` does not map. Raised before any upload starts.
            OSError: A local file does not exist or cannot be accessed. Raised before any upload starts.
            ExceptionGroup: One or more files in a batch failed to upload. It holds one exception per failed file.
                Roboto does not complete that batch's transaction, earlier batches stay uploaded, and later batches
                do not start.
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

        # Check every file before batching: each upload transaction sees only its own batch, so it could not detect
        # two files from different batches sharing a destination.
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

        # Each batch gets its own upload transaction, so no transaction registers more than batch_size files with
        # Roboto. Passing the same batch_size to UploadTransaction makes it upload its whole slice as one batch.
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
                # Assumes every file in a transaction uploads to the same object store, so the store for the first
                # upload URI serves them all.
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
        """Download files Roboto stores to local paths, retrying the files that fail.

        Downloads the files one bucket at a time, with read credentials Roboto issues for ``association``. A file
        that fails to download is tried again immediately, up to three attempts in all; files that succeeded are not
        downloaded again.

        Args:
            files: Files to download, each with its bucket, its storage URI, and the local path to save it to.
            association: Resource the files belong to, which Roboto issues the read credentials for.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            on_progress: Function called with the number of bytes downloaded since its previous call. ``None``
                reports no progress.

        Raises:
            RobotoNotFoundException: Roboto issues no credentials for a file's bucket, such as a bucket not
                registered with Roboto.
            ExceptionGroup: One or more files still failed after three attempts. It holds the last exception of each
                failed file. Files in buckets not yet reached are not downloaded.
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
            # Assumes every file in one bucket is in the same object store, so the store for the first file's URI
            # serves them all.
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
