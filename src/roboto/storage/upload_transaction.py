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
from .api_operations import (
    BeginUploadRequest,
    BeginUploadResponse,
    ReportUploadProgressRequest,
    ReportUploadProgressResponseItem,
)
from .credentials import RobotoCredentials
from .object_store import (
    CredentialProvider,
    Credentials,
    FutureLike,
)

logger = default_logger()


class TransactionFile(typing.TypedDict):
    """A file to upload: the local file to read and the path to upload it to.

    Items of the ``items`` argument of ``UploadTransaction``.
    """

    local_path: pathlib.Path
    """Local path of the file to upload."""

    destination_path: str
    """Path within the association to upload the file to, such as ``logs/run.mcap``."""

    file_size: int
    """Size of the file in bytes."""


class UploadableFile(typing.TypedDict):
    """A file to upload, with the URI to write its bytes to.

    Yielded by iterating over an ``UploadTransaction``.
    """

    local_path: pathlib.Path
    """Local path of the file to upload."""

    destination_path: str
    """Path within the association to upload the file to, such as ``logs/run.mcap``."""

    upload_uri: str
    """URI to write the file's bytes to, from :py:attr:`~roboto.storage.BeginUploadResponse.upload_mappings`."""


class UploadTransaction:
    """An upload of one or more files to a dataset, device, device type, organization, or topic.

    The SDK's own code uses it; to upload files, use :py:meth:`~roboto.domain.datasets.Dataset.upload_files` or
    :py:meth:`~roboto.storage.FileService.upload` instead. To upload with one:

    1. Enter the transaction as a context manager, which begins the upload (see
       :py:class:`~roboto.storage.BeginUploadRequest`) and fetches the URI to write each file's bytes to.
    2. Build an object store from the provider ``make_credential_provider`` returns.
    3. Inside the store's ``with`` block, iterate over the transaction, start each yielded file's upload, and pass the
       future the store returns to ``register_upload``. After each batch of ``batch_size`` files, the iteration
       waits for the batch's uploads with ``await_uploads``, which reports the finished ones to Roboto.
    4. Leave the transaction's ``with`` block. Leaving it without an exception completes the upload, which marks
       every file not reported yet :py:attr:`~roboto.domain.files.FileStatus.Available`. Leaving it with an
       exception, such as the ``ExceptionGroup`` a failed upload raises, does not complete the upload, so a file
       whose bytes may be missing is never marked available.

    Leaving the ``with`` block with registered uploads that were never waited for logs a warning.

    Args:
        items: Files to upload, which iterating over the transaction yields.
        association: Resource to upload the files to: a dataset, device, device type, organization, or topic.
        device_id: ID of the device that produced the files. ``None`` records the calling device when a device makes
            the request, and no device otherwise.
        origination: What uploaded the files, such as ``roboto client v1.0.0``. ``None`` records the ``ROBOTO_ENV``
            environment variable when it is set, and ``roboto <version>`` with the SDK's version otherwise.
        batch_size: Number of files iteration yields before it waits for their uploads and reports them to Roboto.
            ``None`` puts every file in one batch.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
            otherwise the caller's only organization.
    """

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

        self.__completed_uploads: dict[pathlib.Path, str] = {}

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
            self.__finalize()

    def __iter__(self) -> typing.Generator[UploadableFile, None, None]:
        """Yield each file to upload with its upload URI, waiting for the registered uploads after each batch.

        Pass each file's upload to ``register_upload`` before taking the next file, so that the ``await_uploads`` call
        at the end of its batch of ``batch_size`` files waits for it.

        Raises:
            ExceptionGroup: One or more uploads in a batch failed. It surfaces during iteration, when that batch ends,
                after its successful uploads are reported, and holds each failed upload's exception.
            RobotoInternalException: Roboto's response to a batch's report does not match the reported uploads one
                to one. It surfaces during iteration, when that batch ends.
        """
        for batch_start in range(0, len(self.__items), self.__batch_size):
            batch = self.__items[batch_start : batch_start + self.__batch_size]
            for item in batch:
                yield {
                    "local_path": item["local_path"],
                    "destination_path": item["destination_path"],
                    "upload_uri": self.upload_mappings[item["destination_path"]],
                }
            self.await_uploads()

    @property
    def completed_uploads(self) -> dict[pathlib.Path, str]:
        """Mapping from each local path whose upload Roboto marked available to the ID of the file it was uploaded to.

        Holds every upload ``await_uploads`` has reported so far. Iterating over the transaction reports each batch's
        successful uploads at the end of the batch.
        """
        return self.__completed_uploads

    @property
    def transaction_id(self) -> str:
        """Unique ID of the upload, beginning with ``tx_``, which is the ``{upload_id}`` in the routes that continue it.

        Read from :py:attr:`~roboto.storage.BeginUploadResponse.transaction_id`. Raises ``Exception`` until the
        transaction is entered as a context manager.
        """
        if self.__transaction_id is None:
            raise Exception("An UploadTransaction must be used as a context manager.")

        return self.__transaction_id

    @property
    def upload_mappings(self) -> dict[str, str]:
        """URI to write each file's bytes to, such as ``s3://<bucket>/<key>``, keyed by the file's path.

        Read from :py:attr:`~roboto.storage.BeginUploadResponse.upload_mappings`. Raises ``Exception`` until the
        transaction is entered as a context manager.
        """
        if self.__upload_mappings is None:
            raise Exception("An UploadTransaction must be used as a context manager.")

        return self.__upload_mappings

    def await_uploads(self) -> None:
        """Wait for every registered upload to finish, then report the successful ones to Roboto.

        Roboto marks each reported file :py:attr:`~roboto.domain.files.FileStatus.Available`, and
        ``completed_uploads`` records its ID. Iterating over the transaction calls this at the end of each batch. Call
        it before the object store's ``with`` block exits, since the store may stop its transfers on exit.

        Raises:
            ExceptionGroup: One or more registered uploads failed. Raised after the successful uploads are reported,
                and holds each failed upload's exception.
            RobotoInternalException: Roboto's response to the report does not match the reported uploads one to one,
                so the uploaded paths cannot be matched to their files.
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

        if completed:
            self.__report_progress(completed)

        self.__pending_uploads.clear()

        if errors:
            raise ExceptionGroup("One or more uploads failed", errors)

    def make_credential_provider(self) -> CredentialProvider:
        """Return a callable that fetches credentials that can write this upload's files.

        Each call fetches fresh credentials from Roboto, so an object store can call it again to replace credentials
        that expire during a long upload.

        Returns:
            Credential provider for an object store.

        Raises:
            RobotoInternalException: Roboto issues no credentials for the upload. Raised when the returned function is
                called.
        """

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
        """Record a started upload, so that the next wait for uploads includes it.

        Args:
            file: File the upload writes, as iterating over the transaction yielded it.
            future: Future the object store returned when the upload started.
        """
        self.__pending_uploads.append((file, future))

    def __finalize(self):
        self.__roboto_client.put(f"v1/files/upload/{self.transaction_id}/complete")

    def __report_progress(self, batch: list[UploadableFile]):
        manifest_items = [file["upload_uri"] for file in batch]
        response = self.__roboto_client.put(
            f"v1/files/upload/{self.transaction_id}/progress",
            data=ReportUploadProgressRequest(
                manifest_items=manifest_items,
            ),
        )
        pairs = response.to_record_list(ReportUploadProgressResponseItem)

        # Every reported URI is one of the upload's own, so Roboto owes one (uri, file_id) pair for each. Raise
        # before recording any pair, so a mismatch fails the upload instead of leaving paths silently missing from
        # the mapping FileService.upload and Dataset.upload_files return.
        local_path_by_uri = {file["upload_uri"]: file["local_path"] for file in batch}
        unmatched_uris = sorted(pair.uri for pair in pairs if pair.uri not in local_path_by_uri)
        missing_uris = sorted(set(local_path_by_uri) - {pair.uri for pair in pairs})
        if unmatched_uris or missing_uris:
            raise RobotoInternalException(
                "The Roboto service's upload progress response does not correspond one-to-one with the "
                "uploads reported to it, so uploaded paths cannot be reliably matched to the file records "
                f"they created. Reported URIs with no response pair: {missing_uris or 'none'}. "
                f"Response URIs matching no reported upload: {unmatched_uris or 'none'}."
            )

        for pair in pairs:
            self.__completed_uploads[local_path_by_uri[pair.uri]] = pair.file_id
