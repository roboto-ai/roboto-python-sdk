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
    """
    A wire-transmissible representation of a dataset.
    """

    created: datetime.datetime
    created_by: str
    dataset_id: str  # sort key
    description: Optional[str] = None
    device_id: Optional[str] = None
    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    modified: datetime.datetime
    modified_by: str
    name: Optional[str] = pydantic.Field(
        default=None,
        max_length=120,
    )
    """A short name for this dataset. This may be an org-specific unique ID that's more meaningful than the dataset_id,
    or a short summary of the dataset's contents. If provided, must be 120 characters or less."""
    org_id: str  # partition key
    roboto_record_version: int = 0  # A protected field, incremented on every update
    tags: list[str] = pydantic.Field(default_factory=list)

    # Because datasets may have files in many buckets, both customer provided and Roboto managed, having a single
    # storage location or a single administrator no longer makes sense.
    #
    # These fields are deprecated, and have defaulting strategies to maintain backwards compatibility with old
    # versions of the Roboto SDK, since this record defines the shape of the service's return payload.
    administrator: str = "Roboto"
    storage_ctx: dict[str, Any] = pydantic.Field(
        default_factory=make_backwards_compatible_placeholder_storage_ctx
    )
    storage_location: str = "S3"
