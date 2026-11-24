# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic
from pydantic import ConfigDict

from ...pydantic import (
    remove_non_noneable_init_args,
)
from ...sentinels import NotSet, NotSetType
from ...updates import CustomFieldChangeset, MetadataChangeset
from ..files.operations import (
    CreateDirectoryRequest,
    DeleteDirectoriesRequest,
    QueryDatasetFilesRequest,
    RenameDirectoryRequest,
)


class CreateDatasetRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.datasets.Dataset.create`.

    Passing ``None`` for ``metadata`` or ``tags`` is the same as omitting it. A ``name`` longer than 120 characters
    raises ``pydantic.ValidationError``.
    """

    description: typing.Optional[str] = pydantic.Field(
        default=None,
        description="An optional human-readable description for this dataset.",
    )
    """Human-readable description of the dataset."""

    device_id: typing.Optional[str] = pydantic.Field(
        default=None,
        description="The ID of the device which created this dataset, if applicable.",
    )
    """ID of the device that produced the dataset's data.

    Must name a device in the organization the dataset is created in. ``None`` records the calling device when a
    device makes the request, and no device otherwise.
    """

    name: typing.Optional[str] = pydantic.Field(
        default=None,
        description="A short name for this dataset. Must be under 120 characters or less.",
        max_length=120,
    )
    """Human-readable name of the dataset, at most 120 characters."""

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this dataset for discovery and search, e.g. "
        + "`{ 'softwareVersion': '3.1.4' }`",
    )
    """Key-value metadata to set on the dataset."""

    tags: list[str] = pydantic.Field(
        default_factory=list,
        description="Initial tags to associate with this dataset for discovery and search, e.g. "
        + "`['sunny', 'campaign5']`",
    )
    """Tags to set on the dataset."""

    custom_fields: typing.Optional[dict[str, typing.Any]] = pydantic.Field(
        default=None,
        description="Initial values for custom fields defined on Datasets in the caller's org, e.g. "
        + "`{ 'drone_id': 'DJI-X', 'flight_count': 12 }`. Each name must match a Ready custom-field "
        + "definition for the org's Dataset entity type; values are typed against the field's declared type.",
    )
    """Initial values for the dataset's custom fields, keyed by field name. ``None`` sets none.

    Each name must be a :py:class:`~roboto.domain.custom_fields.CustomField` defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Dataset` in the organization the dataset is created in,
    with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
    field's declared type. Otherwise the request fails with ``RobotoIllegalArgumentException``.
    """

    def __init__(self, **data):
        super().__init__(**remove_non_noneable_init_args(data, self))


class QueryDatasetsRequest(pydantic.BaseModel):
    """Request body holding filter criteria for datasets.

    No SDK method or Roboto route uses this model. To search datasets, pass a
    :py:class:`~roboto.query.QuerySpecification` to :py:meth:`~roboto.domain.datasets.Dataset.query`.
    """

    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Filter criteria for datasets."""

    model_config = ConfigDict(extra="ignore")


class UpdateDatasetRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.datasets.Dataset.update`.

    A field left at its default (``NotSet`` or ``None``) is unchanged. A ``name`` longer than 120 characters raises
    ``pydantic.ValidationError``.
    """

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the dataset's tags and metadata."""

    description: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """Human-readable description of the dataset. ``None`` clears it."""

    device_id: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """ID of the device that produced the dataset's data, which must be in the dataset's organization.

    ``None`` clears it.
    """

    name: typing.Optional[
        typing.Union[typing.Annotated[str, pydantic.StringConstraints(max_length=120)], NotSetType]
    ] = NotSet
    """Human-readable name of the dataset, at most 120 characters. ``None`` clears it."""

    custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None
    """Changes to the dataset's custom-field values.

    Each field name the changeset references must be a custom field defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Dataset` in the dataset's organization, with status
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each ``set_fields`` value must match that
    field's declared type. Otherwise the request fails with ``RobotoIllegalArgumentException``. See
    :py:class:`~roboto.updates.CustomFieldChangeset`.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class CreateDatasetIfNotExistsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.datasets.Dataset.create_if_not_exists`.

    Roboto creates the dataset only when no dataset matches a RoboQL query. That method describes how several matches
    and concurrent requests are resolved.
    """

    match_roboql_query: str
    """RoboQL query that looks for an existing dataset in the organization.

    When a dataset matches, the response is that dataset and nothing is created.
    """

    create_request: CreateDatasetRequest
    """Properties of the dataset to create when no dataset matches ``match_roboql_query``."""


class BeginSingleFileUploadRequest(pydantic.BaseModel):
    """Deprecated. Request body for ``POST /v2/datasets/{dataset_id}/uploads``.

    Upload a file with :py:meth:`~roboto.domain.datasets.Dataset.upload_file` instead. The route starts uploading one
    file to a dataset.
    """

    origination: typing.Optional[str] = pydantic.Field(
        description="Additional information about what uploaded the file, e.g. `roboto client v1.0.0`.",
        default=None,
    )
    """What uploaded the file, such as ``roboto client v1.0.0``. ``None`` records the caller's user ID."""

    file_path: str = pydantic.Field(
        description=(
            "The destination path to upload the file to in the dataset, e.g. `recording.bag`or `path/to/metadata.json`."
        ),
    )
    """Path within the dataset to upload the file to, such as ``path/to/metadata.json``."""

    file_size: int = pydantic.Field(description="The size of the file in bytes.")
    """Size of the file in bytes."""


class BeginSingleFileUploadResponse(pydantic.BaseModel):
    """Deprecated. Response body of ``POST /v2/datasets/{dataset_id}/uploads``.

    Upload a file with :py:meth:`~roboto.domain.datasets.Dataset.upload_file` instead. Send the file's bytes to
    ``upload_url`` with an HTTP PUT, then mark the upload complete with
    ``PUT /v2/datasets/{dataset_id}/uploads/{upload_id}/complete``.
    """

    upload_id: str
    """Unique ID of the upload."""

    upload_url: str
    """Pre-signed URL that accepts the file's bytes in an HTTP PUT."""


__all__ = (
    "BeginSingleFileUploadRequest",
    "BeginSingleFileUploadResponse",
    "CreateDatasetIfNotExistsRequest",
    "CreateDatasetRequest",
    "CreateDirectoryRequest",
    "DeleteDirectoriesRequest",
    "QueryDatasetFilesRequest",
    "QueryDatasetsRequest",
    "RenameDirectoryRequest",
    "UpdateDatasetRequest",
)
