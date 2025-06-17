# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing
from typing import Any, Optional

import pydantic


def make_backwards_compatible_placeholder_storage_ctx() -> dict[str, typing.Any]:
    """
    Because of some overly aggressive pydantic model validation, we need to return a storage_context with our
    original S3 description in order to stop SDK clients prior to 0.10.0 from throwing errors.
    """
    return {
        "bucket_name": "NOT_SET",
        "iam_role_arn": "NOT_SET",
        "key_prefix": "NOT_SET",
    }


class DatasetRecord(pydantic.BaseModel):
    """Wire-transmissible representation of a dataset in the Roboto platform.

    DatasetRecord contains all the metadata and properties associated with a dataset,
    including its identification, timestamps, metadata, tags, and organizational
    information. This is the data structure used for API communication and persistence.

    DatasetRecord instances are typically created by the platform during dataset
    creation operations and are updated as datasets are modified. The Dataset domain
    class wraps DatasetRecord to provide a more convenient interface for dataset
    operations.

    The record includes audit information (created/modified timestamps and users),
    organizational context, and user-defined metadata and tags for discovery and
    organization purposes.
    """

    created: datetime.datetime
    """Timestamp when this dataset was created in the Roboto platform."""

    created_by: str
    """User ID or service account that created this dataset."""

    dataset_id: str
    """Unique identifier for this dataset within the Roboto platform."""

    description: Optional[str] = None
    """Human-readable description of the dataset's contents and purpose."""

    device_id: Optional[str] = None
    """Optional identifier of the device that generated this dataset's data."""

    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    """User-defined key-value pairs for storing additional dataset information."""

    modified: datetime.datetime
    """Timestamp when this dataset was last modified."""

    modified_by: str
    """User ID or service account that last modified this dataset."""

    name: Optional[str] = pydantic.Field(
        default=None,
        max_length=120,
    )
    """A short name for this dataset. This may be an org-specific unique ID that's more meaningful than the dataset_id,
    or a short summary of the dataset's contents. If provided, must be 120 characters or less."""

    org_id: str
    """Organization ID that owns this dataset."""

    roboto_record_version: int = 0  # A protected field, incremented on every update
    """Internal version number for this record, automatically incremented on updates."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """List of tags for categorizing and discovering this dataset."""

    # Because datasets may have files in many buckets, both customer provided and Roboto managed, having a single
    # storage location or a single administrator no longer makes sense.
    #
    # These fields are deprecated, and have defaulting strategies to maintain backwards compatibility with old
    # versions of the Roboto SDK, since this record defines the shape of the service's return payload.
    administrator: str = "Roboto"
    """Deprecated field maintained for backwards compatibility. Always defaults to 'Roboto'."""

    storage_ctx: dict[str, Any] = pydantic.Field(
        default_factory=make_backwards_compatible_placeholder_storage_ctx
    )
    """Deprecated storage context field maintained for backwards compatibility with SDK versions prior to 0.10.0."""

    storage_location: str = "S3"
    """Deprecated storage location field maintained for backwards compatibility. Always defaults to 'S3'."""
