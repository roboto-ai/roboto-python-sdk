# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing
from typing import Any, Optional

import pydantic

from ...pydantic.serializers import field_serializer_custom_field_values


def make_backwards_compatible_placeholder_storage_ctx() -> dict[str, typing.Any]:
    """Deprecated. Return the placeholder ``storage_ctx`` that SDK versions before 0.10.0 require on dataset records.

    Pydantic calls this while it builds a ``DatasetRecord`` without a ``storage_ctx``, as that field's default, which
    Roboto does whenever it creates or returns a dataset; nothing replaces it. Those versions reject a dataset record
    whose ``storage_ctx`` lacks the ``bucket_name``, ``iam_role_arn``, and ``key_prefix`` keys, so each key is present
    with the value ``"NOT_SET"``.
    """
    return {
        "bucket_name": "NOT_SET",
        "iam_role_arn": "NOT_SET",
        "key_prefix": "NOT_SET",
    }


class DatasetRecord(pydantic.BaseModel):
    """Data record of a dataset, as the Roboto API returns it.

    A dataset is a container of files in a directory structure, usually from one robot activity such as a flight.
    :py:class:`~roboto.domain.datasets.Dataset` wraps this record with methods that act on the dataset, and exposes
    it as :py:attr:`~roboto.domain.datasets.Dataset.record`. Building a record raises ``pydantic.ValidationError``
    when ``name`` is longer than 120 characters.
    """

    created: datetime.datetime
    """Time the dataset was created."""

    created_by: str
    """Principal that created the dataset, as ``<type>:<id>``, such as ``user:<user_id>``."""

    dataset_id: str
    """Unique ID of the dataset, beginning with ``ds_``."""

    description: Optional[str] = None
    """Human-readable description of the dataset, or ``None`` if it has none."""

    device_id: Optional[str] = None
    """ID of the device the dataset's data came from, or ``None`` if none was given."""

    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the dataset."""

    custom_fields: dict[str, Any] = pydantic.Field(default_factory=dict)
    """Values of the custom fields the organization defines for datasets, keyed by field name.

    Every dataset custom field in the :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state appears
    as a key, mapped to ``None`` when the dataset has no value for it. Fields in any other state are absent, so the
    map is empty when no dataset custom field is in that state.
    """

    modified: datetime.datetime
    """Time the dataset was last modified."""

    modified_by: str
    """Principal that last modified the dataset, in the same ``<type>:<id>`` form as ``created_by``."""

    name: Optional[str] = pydantic.Field(
        default=None,
        max_length=120,
    )
    """Human-readable name of the dataset, at most 120 characters, or ``None`` if it has none.

    Roboto does not require names to be unique. A name can be an identifier more meaningful to the organization than
    ``dataset_id``, or a short summary of the dataset's contents.
    """

    org_id: str
    """ID of the organization that owns the dataset."""

    roboto_record_version: int = 0
    """Unused. Version number of the record, ``0`` on every dataset Roboto returns."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the dataset."""

    # A dataset's files can live in several buckets, customer-provided or Roboto-managed, so no single storage
    # location or administrator describes a dataset. Roboto never sets the three fields below; their defaults keep
    # the API's dataset payload parseable by older SDK versions that still require them.
    administrator: str = "Roboto"
    """Deprecated. Administrator of the dataset, always ``"Roboto"`` on datasets Roboto returns.

    Nothing replaces it.
    """

    storage_ctx: dict[str, Any] = pydantic.Field(default_factory=make_backwards_compatible_placeholder_storage_ctx)
    """Deprecated. Placeholder storage context whose values are all ``"NOT_SET"``.

    Each file's :py:attr:`~roboto.domain.files.FileRecord.uri` gives where that file is stored. SDK versions before
    0.10.0 require this field.
    """

    storage_location: str = "S3"
    """Deprecated. Storage location of the dataset, always ``"S3"`` on datasets Roboto returns.

    Each file's :py:attr:`~roboto.domain.files.FileRecord.uri` gives where that file is stored.
    """

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, Any]) -> dict[str, Any]:
        return field_serializer_custom_field_values(custom_fields)
