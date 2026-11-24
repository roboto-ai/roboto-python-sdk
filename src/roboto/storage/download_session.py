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
    """A file to download: the object that holds its content and the local path to write it to.

    Items of the ``files`` argument of :py:meth:`~roboto.storage.FileService.download`.
    """

    bucket_name: str
    """Name of the bucket holding the file's object."""

    source_uri: str
    """Location of the object that holds the file's content, such as ``s3://<bucket>/<key>``."""

    destination_path: pathlib.Path
    """Local path to write the file's content to."""


class DownloadSession:
    """A batch of downloads of one association's files that share read-only credentials.

    The SDK's own code uses it; to download files, use :py:meth:`~roboto.domain.datasets.Dataset.download_files`
    or :py:meth:`~roboto.domain.files.File.download` instead. Roboto keeps no record of a session: its only
    requests fetch credentials. To download with one:

    1. Build an object store from the provider ``make_credential_provider`` returns.
    2. Inside the store's ``with`` block, start each file's download and pass the future the store returns to
       ``register_download``.
    3. Before that block exits, wait for the downloads with ``await_downloads``, which returns the failures. Ending
       an iteration over the session, or leaving the session's own ``with`` block, also waits, and raises
       ``ExceptionGroup`` holding each failed download's exception.

    Args:
        items: Files to download, which iterating over the session yields.
        association: Dataset, device, device type, or organization whose files to download. Roboto issues
            read-only credentials for its files.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
            otherwise the caller's only organization.
    """

    def __init__(
        self,
        items: collections.abc.Sequence[DownloadableFile],
        association: Association,
        roboto_client: typing.Optional[RobotoClient] = None,
        caller_org_id: typing.Optional[str] = None,
    ):
        self.__items = items
        self.__association = association
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__caller_org_id = caller_org_id

        self.__pending_downloads: list[tuple[DownloadableFile, FutureLike[None]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__await_downloads_or_raise()

    def __iter__(self) -> typing.Generator[DownloadableFile, None, None]:
        """Yield each file to download, then wait for the registered downloads.

        Raises:
            ExceptionGroup: One or more registered downloads failed. It surfaces during iteration, when the last file
                has been yielded, and holds each failed download's exception.
        """
        for item in self.__items:
            yield item

        self.__await_downloads_or_raise()

    def __await_downloads_or_raise(self) -> None:
        failures = self.await_downloads()
        if failures:
            raise ExceptionGroup(
                "One or more downloads failed",
                [exc for _, exc in failures],
            )

    def make_credential_provider(self, bucket_name: typing.Optional[str] = None) -> CredentialProvider:
        """Build a callable that fetches read-only credentials for the association's files.

        Each call fetches fresh credentials from Roboto, so an object store can call it again to replace credentials
        that expire during a long download.

        Args:
            bucket_name: Bucket whose credentials to fetch. ``None`` takes the first credentials Roboto issues.

        Returns:
            Credential provider for an object store.

        Raises:
            RobotoNotFoundException: Roboto issues no credentials for ``bucket_name``. Raised when the returned
                function is called.
        """
        association_id = self.__association.association_id
        credentials_route = (
            f"v1/datasets/id/{association_id}/credentials"
            if self.__association.is_dataset
            else f"v1/files/association/id/{association_id}/credentials"
        )

        def _get_download_credentials() -> Credentials:
            query_params: dict[str, str] = {"mode": Permissions.ReadOnly.value}
            response = self.__roboto_client.get(
                credentials_route,
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

    def await_downloads(self) -> list[tuple[DownloadableFile, Exception]]:
        """Wait for every registered download to finish, and return the ones that failed.

        Call it before the object store's ``with`` block exits, since the store may stop its transfers on exit. Any
        exception a download raised is logged and returned, not raised. The registered downloads are then forgotten,
        so the next call waits only for downloads registered after this one, such as retries of the failures.

        Returns:
            ``(file, exception)`` pairs for the downloads that failed; empty when every download succeeded.
        """
        if not self.__pending_downloads:
            return []

        failed: list[tuple[DownloadableFile, Exception]] = []

        for file, future in self.__pending_downloads:
            try:
                future.result()
            except Exception as e:
                logger.error("Download failed: %s", file["source_uri"], exc_info=e)
                failed.append((file, e))

        self.__pending_downloads.clear()

        return failed

    def register_download(self, file: DownloadableFile, future: FutureLike[None]) -> None:
        """Record a started download, so that the next wait for downloads includes it.

        Args:
            file: File the download writes.
            future: Future the object store returned when the download started.
        """
        self.__pending_downloads.append((file, future))
