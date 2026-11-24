# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ..association import Association


class AbortTransactionsRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/files/transactions/abort``, which abandons uploads.

    Each file an aborted upload wrote returns to its latest
    :py:attr:`~roboto.domain.files.FileStatus.Available` version, if it has one. IDs that match no upload are
    ignored.
    """

    transaction_ids: list[str]
    """IDs of the uploads to abort.

    Each is a ``BeginUploadResponse.transaction_id`` or a ``BeginSignedUrlUploadResponse.upload_id``.
    """


class BeginUploadRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/files/upload``, which begins an upload of one or more files.

    Sent by :py:meth:`~roboto.storage.FileService.upload`, through
    :py:class:`~roboto.storage.upload_transaction.UploadTransaction`. Roboto creates a file for each path in
    ``resource_manifest``, or a new version of the file already at that path, and holds it in the
    :py:attr:`~roboto.domain.files.FileStatus.Reserved` state until its upload completes.
    """

    association: Association
    """Resource to upload the files to: a dataset, device, device type, organization, or topic.

    Any other kind raises ``RobotoInvalidRequestException``.
    """

    origination: str
    """What uploaded the files, such as ``roboto client v1.0.0``."""

    resource_manifest: dict[str, int]
    """Size in bytes of each file to upload, keyed by its path within ``association``, such as ``logs/run.mcap``."""

    device_id: typing.Optional[str] = None
    """ID of the device that produced the files, which must be in the organization the files are uploaded to.

    ``None`` records the calling device when a device makes the request, and no device otherwise.
    """


class BeginUploadResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/files/upload``.

    Read by :py:meth:`~roboto.storage.FileService.upload`, through
    :py:class:`~roboto.storage.upload_transaction.UploadTransaction`. To finish the upload:

    1. Write each file's bytes to its URI in ``upload_mappings``, with credentials from
       ``GET /v1/files/upload/{upload_id}/credentials``.
    2. Optionally, report files as they finish with ``PUT /v1/files/upload/{upload_id}/progress``, which marks them
       :py:attr:`~roboto.domain.files.FileStatus.Available`.
    3. Complete the upload with ``PUT /v1/files/upload/{upload_id}/complete``, which marks available every file
       not reported yet.
    """

    transaction_id: str
    """Unique ID of the upload, beginning with ``tx_``, which is the ``{upload_id}`` in the routes that continue it."""

    upload_mappings: dict[str, str]
    """URI to write each file's bytes to, such as ``s3://<bucket>/<key>``, keyed by the file's path.

    The keys are the paths of ``BeginUploadRequest.resource_manifest``.
    """


class BeginSignedUrlUploadRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/files/signed_url_upload``, which begins an upload of one file to a pre-signed URL.

    Roboto creates the file, or a new version of the file already at ``file_path``, and holds it in the
    :py:attr:`~roboto.domain.files.FileStatus.Reserved` state until its upload completes.
    """

    association: Association
    """Resource to upload the file to: a dataset, device, device type, organization, or topic.

    Any other kind raises ``RobotoInvalidRequestException``.
    """

    file_path: str
    """Path within ``association`` to upload the file to, such as ``path/to/metadata.json``."""

    file_size: int
    """Size of the file in bytes."""

    origination: typing.Optional[str] = None
    """What uploaded the file, such as ``roboto client v1.0.0``. ``None`` records the caller's user ID."""


class BeginSignedUrlUploadResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/files/signed_url_upload``.

    Send the file's bytes to ``upload_url`` with an HTTP PUT, then complete the upload with
    ``PUT /v1/files/upload/{upload_id}/complete``.
    """

    upload_id: str
    """Unique ID of the upload, beginning with ``tx_``."""

    upload_url: str
    """Pre-signed URL that accepts the file's bytes in an HTTP PUT."""


class ReportUploadProgressRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.storage.upload_transaction.UploadTransaction.await_uploads`.

    Sent to ``PUT /v1/files/upload/{upload_id}/progress`` to mark the files of an upload that finished before the
    whole upload completes. Each reported file becomes :py:attr:`~roboto.domain.files.FileStatus.Available`.
    """

    manifest_items: list[str]
    """URIs of the files whose bytes are fully written.

    Each is a value of ``BeginUploadResponse.upload_mappings``.
    """


class ReportUploadProgressResponseItem(pydantic.BaseModel):
    """Item of the response body of ``PUT /v1/files/upload/{upload_id}/progress``.

    Each item is one file marked available. Read by
    :py:meth:`~roboto.storage.upload_transaction.UploadTransaction.await_uploads`. Roboto returns one item per reported
    URI that matched a file of the upload, and omits URIs that matched none without failing the request.
    ``await_uploads`` reports only URIs from the upload's own ``upload_mappings``, so it raises
    ``RobotoInternalException`` when the items do not match the URIs it reported one to one.
    """

    uri: str
    """URI of the file, one of the request's ``ReportUploadProgressRequest.manifest_items``."""

    file_id: str
    """ID of the file marked available, beginning with ``fl_``."""
