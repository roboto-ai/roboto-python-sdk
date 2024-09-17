# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

import pydantic

from ...association import Association
from ...sentinels import NotSet, NotSetType
from ...updates import (
    MetadataChangeset,
    TaglessMetadataChangeset,
)
from .record import (
    CanonicalDataType,
    MessagePathRecord,
    RepresentationRecord,
    RepresentationStorageFormat,
)


class BaseAddRepresentationRequest(pydantic.BaseModel):
    association: Association
    storage_format: RepresentationStorageFormat
    version: int


class SetDefaultRepresentationRequest(BaseAddRepresentationRequest):
    """Memorialize a representation of topic data contained within a source recording file."""

    # 'ignore' used to avoid backwards incompatible change to remove `org_id` from BaseAddRepresentationRequest.
    # Should be changed back to 'forbid' for SDK v1.0
    model_config = pydantic.ConfigDict(extra="ignore")


class AddMessagePathRepresentationRequest(BaseAddRepresentationRequest):
    """Associate a MessagePath with a Representation."""

    message_path_id: str

    # 'ignore' used to avoid backwards incompatible change to remove `org_id` from BaseAddRepresentationRequest
    # Should be changed back to 'forbid' for SDK v1.0
    model_config = pydantic.ConfigDict(extra="ignore")


class MessagePathRepresentationMapping(pydantic.BaseModel):
    """Latest representation of topic data in particular storage format containing given message paths"""

    message_paths: collections.abc.MutableSequence[MessagePathRecord]
    representation: RepresentationRecord


class AddMessagePathRequest(pydantic.BaseModel):
    """Associate a MessagePath with a Topic."""

    message_path: str
    data_type: str
    canonical_data_type: CanonicalDataType
    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this topic message path for discovery and search, e.g. "
        + "`{ 'min': 0.71, 'max': 1.77, 'classification': 'my-custom-classification-tag' }`",
    )

    model_config = pydantic.ConfigDict(extra="forbid")


class UpdateMessagePathRequest(pydantic.BaseModel):
    """Update metadata for a MessagePath within a topic"""

    message_path: str
    metadata_changeset: typing.Union[TaglessMetadataChangeset]

    model_config = pydantic.ConfigDict(extra="forbid")


class CreateTopicRequest(pydantic.BaseModel):
    """Memorialize a Topic contained within a source recording file."""

    # Required
    association: Association
    topic_name: str

    # Optional
    end_time: typing.Optional[int] = None
    message_count: typing.Optional[int] = None
    metadata: typing.Optional[collections.abc.Mapping[str, typing.Any]] = None
    schema_checksum: typing.Optional[str] = None
    schema_name: typing.Optional[str] = None
    start_time: typing.Optional[int] = None
    message_paths: typing.Optional[collections.abc.Sequence[AddMessagePathRequest]] = (
        None
    )

    # 'ignore' used to avoid backwards incompatible change to remove `org_id`
    # Should be changed back to 'forbid' for SDK v1.0
    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateTopicRequest(pydantic.BaseModel):
    """Update a Topic."""

    end_time: typing.Union[typing.Optional[int], NotSetType] = NotSet
    message_count: typing.Union[int, NotSetType] = NotSet
    schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet
    schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet
    start_time: typing.Union[typing.Optional[int], NotSetType] = NotSet
    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet

    model_config = pydantic.ConfigDict(
        extra="forbid", json_schema_extra=NotSetType.openapi_schema_modifier
    )
