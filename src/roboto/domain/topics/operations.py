# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing

import pydantic
from pydantic import model_validator

from ...association import Association
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
)
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
    """Request payload to add a representation to a topic"""

    association: Association
    storage_format: RepresentationStorageFormat
    version: int


class SetDefaultRepresentationRequest(BaseAddRepresentationRequest):
    """Memorialize a representation of topic data contained within a source recording file"""

    # 'ignore' used to avoid backwards incompatible change to remove `org_id` from BaseAddRepresentationRequest.
    # Should be changed back to 'forbid' for SDK v1.0
    model_config = pydantic.ConfigDict(extra="ignore")


class AddMessagePathRepresentationRequest(BaseAddRepresentationRequest):
    """Associate a MessagePath with a Representation"""

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
    """Update attributes of a message path within a topic"""

    message_path: str
    """Message path name (required)."""

    metadata_changeset: typing.Union[TaglessMetadataChangeset, NotSetType] = NotSet
    """A set of changes to the message path's metadata (optional)."""

    data_type: typing.Union[str, NotSetType] = NotSet
    """Native data type for the data under this message path (optional)."""

    canonical_data_type: typing.Union[CanonicalDataType, NotSetType] = NotSet
    """Canonical Roboto data type for the data under this message path (optional).

    Note: updating this attribute should be done with care, as it affects Roboto's
    ability to interpret and visualize the data.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    def has_updates(self) -> bool:
        """Checks whether this request would result in any message path modifications."""

        return (
            is_set(self.data_type)
            or is_set(self.canonical_data_type)
            or (
                is_set(self.metadata_changeset)
                and self.metadata_changeset.has_changes()
            )
        )


class DeleteMessagePathRequest(pydantic.BaseModel):
    """Delete a message path from a topic."""

    message_path: str
    """Message path name."""

    model_config = pydantic.ConfigDict(extra="forbid")


class MessagePathChangeset(pydantic.BaseModel):
    """A set of changes to add, delete or update message paths on a topic."""

    message_paths_to_add: collections.abc.Sequence[AddMessagePathRequest] | None = None
    """Message paths to add to a topic."""

    message_paths_to_delete: (
        collections.abc.Sequence[DeleteMessagePathRequest] | None
    ) = None
    """Message paths to delete from a topic."""

    message_paths_to_update: (
        collections.abc.Sequence[UpdateMessagePathRequest] | None
    ) = None
    """Message paths to update on a topic."""

    replace_all: bool = False
    """Flag indicating whether this changeset should replace all message paths on a topic.

    It assumes that the replacement message paths will be provided via ``message_paths_to_add``. Rather than
    setting this flag directly, use appropriate class methods such as ``from_replacement_message_paths``.
    """

    @model_validator(mode="after")
    def check_replace_all_correctness(self) -> MessagePathChangeset:
        if self.replace_all and (
            self.message_paths_to_add is None
            or not (
                self.message_paths_to_update is None
                and self.message_paths_to_delete is None
            )
        ):
            raise ValueError("replace_all must only be used with message_paths_to_add")

        return self

    @classmethod
    def from_replacement_message_paths(
        cls, message_paths: collections.abc.Sequence[AddMessagePathRequest]
    ) -> MessagePathChangeset:
        """A changeset that replaces any existing message paths with the ones provided."""

        return cls(message_paths_to_add=message_paths, replace_all=True)

    def has_changes(self) -> bool:
        """Checks whether the changeset contains any actual changes."""

        return self.replace_all or not (
            (self.message_paths_to_add is None or not self.message_paths_to_add)
            and (
                self.message_paths_to_update is None or not self.message_paths_to_update
            )
            and (
                self.message_paths_to_delete is None or not self.message_paths_to_delete
            )
        )


class CreateTopicRequest(pydantic.BaseModel):
    """Memorialize a Topic contained within a source recording file"""

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
    """Request payload to update a Topic"""

    end_time: typing.Union[typing.Optional[int], NotSetType] = NotSet
    message_count: typing.Union[int, NotSetType] = NotSet
    schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet
    schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet
    start_time: typing.Union[typing.Optional[int], NotSetType] = NotSet
    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    message_path_changeset: typing.Union[MessagePathChangeset, NotSetType] = NotSet

    model_config = pydantic.ConfigDict(
        extra="forbid", json_schema_extra=NotSetType.openapi_schema_modifier
    )
