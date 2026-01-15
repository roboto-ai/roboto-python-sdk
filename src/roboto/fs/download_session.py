# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import pathlib
import sys
import typing

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from ..association import Association
from ..auth import Permissions
from ..exceptions import RobotoInternalException, RobotoNotFoundException
from ..http import RobotoClient
from ..logging import default_logger
from .credentials import RobotoCredentials
from .object_store import (
    CredentialProvider,
    Credentials,
    FutureLike,
)

logger = default_logger()


class DownloadableFile(typing.TypedDict):
    """A file to be downloaded from the Roboto Platform."""

    bucket_name: str
    """Name of the bucket where the file is stored."""

    source_uri: str
    """Full URI of the file in cloud storage (e.g., 's3://bucket/key')."""

    destination_path: pathlib.Path
    """Local path where the file should be saved."""


class DownloadSession:
    """Manages a batch of file downloads with shared credentials.

    Provides credential lifecycle management and async operation coordination
    for downloading files from a dataset. Unlike UploadTransaction, this does
    not manage an API transaction since downloads don't require server-side
    state tracking.

    Example:
        >>> session = DownloadSession(
        ...     items=[
        ...         {"bucket_name": "bucket", "source_uri": "s3://bucket/key", "destination_path": Path("/tmp/file")}
        ...     ],
        ...     association=Association.dataset("ds_123"),
        ... )
        >>> object_store = registry.get_store_for_uri(uri, session.credential_provider)
        >>> with object_store:
        ...     for file in session:
        ...         future = object_store.get(file["source_uri"], file["destination_path"])
        ...         session.register_download(file, future)
    """

    def __init__(
        self,
        items: collections.abc.Sequence[DownloadableFile],
        association: Association,
        roboto_client: typing.Optional[RobotoClient] = None,
        caller_org_id: typing.Optional[str] = None,
    ):
        """Initialize a download session.

        Args:
            items: Sequence of files to download.
            association: Association of the files to download.
            roboto_client: Optional Roboto client for API calls.
            caller_org_id: Optional organization ID for cross-org access.
        """
        self.__items = items
        self.__association = association
        if not self.__association.is_dataset:
            raise ValueError("Roboto currently only supports downloading files from datasets.")

        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__caller_org_id = caller_org_id

        self.__pending_downloads: list[tuple[DownloadableFile, FutureLike[None]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.await_downloads()

    def __iter__(self) -> typing.Generator[DownloadableFile, None, None]:
        """Yield files to download."""
        for item in self.__items:
            yield item

        self.await_downloads()

    def make_credential_provider(self, bucket_name: typing.Optional[str] = None) -> CredentialProvider:
        """Return a credential provider for read-only access to the dataset."""

        def _get_download_credentials() -> Credentials:
            query_params: dict[str, str] = {"mode": Permissions.ReadOnly.value}
            response = self.__roboto_client.get(
                f"v1/datasets/id/{self.__dataset_id}/credentials",
                query=query_params,
                caller_org_id=self.__caller_org_id,
            ).to_record_list(RobotoCredentials)

            if len(response) == 0:
                raise RobotoInternalException(f"Unable to get credentials for {self.__association!r}")

            if bucket_name is None:
                return response[0].to_object_store_credentials()
            else:
                for creds in response:
                    if creds.bucket == bucket_name:
                        return creds.to_object_store_credentials()

                raise RobotoNotFoundException(
                    f"Unable to get credentials for bucket {bucket_name}. "
                    "Is it properly registered with the Roboto platform?"
                )

        return _get_download_credentials

    @property
    def __dataset_id(self) -> str:
        dataset_id = self.__association.dataset_id
        if dataset_id is None:
            raise ValueError("Roboto currently only supports downloading files from datasets.")
        return dataset_id

    def await_downloads(self) -> None:
        """Wait for all registered downloads to complete.

        Must be called while still inside the object_store context manager,
        since the transfer manager may be shut down when that context exits.

        Raises:
            ExceptionGroup: If any downloads fail, an ExceptionGroup containing all
                           download errors is raised.
        """
        if not self.__pending_downloads:
            return

        errors: list[Exception] = []

        for file, future in self.__pending_downloads:
            try:
                future.result()
            except Exception as e:
                logger.error("Download failed: %s", file["source_uri"], exc_info=e)
                errors.append(e)

        self.__pending_downloads.clear()

        if errors:
            raise ExceptionGroup("One or more downloads failed", errors)

    def register_download(self, file: DownloadableFile, future: FutureLike[None]) -> None:
        """Register a pending download future.

        Call this immediately after initiating each download transfer.
        The future will be awaited when await_downloads() is called.
        """
        self.__pending_downloads.append((file, future))
