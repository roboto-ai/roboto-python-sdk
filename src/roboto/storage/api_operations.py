# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ..association import Association


class AbortTransactionsRequest(pydantic.BaseModel):
    """Request payload for aborting file upload transactions.

    Used to cancel ongoing file upload transactions, typically when uploads
    fail or are no longer needed. This cleans up any reserved resources
    and marks associated files as no longer pending.
    """

    transaction_ids: list[str]
    """List of transaction IDs to abort."""


class BeginUploadRequest(pydantic.BaseModel):
    """Request payload to begin a batch file upload transaction.

    Used to initiate a multi-file upload transaction for any association type
    (dataset, topic, etc.). Returns a transaction ID and upload mappings that
    specify where each file should be uploaded.
    """

    association: Association
    """The entity these files will be associated with (e.g., dataset, topic)."""

    origination: str
    """Description of the upload source (e.g., 'roboto-sdk v1.0.0')."""

    resource_manifest: dict[str, int]
    """Dictionary mapping destination file paths to file sizes in bytes."""

    device_id: typing.Optional[str] = None
    """Optional identifier of the device that generated this data."""


class BeginUploadResponse(pydantic.BaseModel):
    """Response from beginning a batch upload transaction.

    Contains the transaction ID needed for subsequent progress reporting
    and completion calls, plus mappings from file paths to their upload URIs.
    """

    transaction_id: str
    """Unique identifier for this upload transaction."""

    upload_mappings: dict[str, str]
    """Dictionary mapping file paths to their S3 upload URIs."""


class BeginSignedUrlUploadRequest(pydantic.BaseModel):
    """Request payload to begin a single file upload with a signed URL.

    Used for simpler upload scenarios where a pre-signed URL is preferred
    over temporary credentials. The returned URL can be used directly for
    uploading the file content.
    """

    association: Association
    """The entity this file will be associated with (e.g., dataset, topic)."""

    file_path: str
    """Destination path for the file within the association."""

    file_size: int
    """Size of the file in bytes."""

    origination: typing.Optional[str] = None
    """Optional description of the upload source."""


class BeginSignedUrlUploadResponse(pydantic.BaseModel):
    """Response from beginning a single file upload.

    Contains the upload ID for completing the transaction and a pre-signed
    URL that can be used to upload the file content directly.
    """

    upload_id: str
    """Unique identifier for this upload transaction."""

    upload_url: str
    """Pre-signed URL for uploading the file content."""


class ReportUploadProgressRequest(pydantic.BaseModel):
    """Request payload for reporting file upload progress.

    Used to notify the platform about the completion status of individual
    files within a batch upload transaction. This enables progress tracking
    and partial completion handling for large file uploads.
    """

    manifest_items: list[str]
    """List of file URIs that have completed upload."""
