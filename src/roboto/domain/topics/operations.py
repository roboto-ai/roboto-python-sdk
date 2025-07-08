# Copyright (c) 2025 Roboto Technologies, Inc.
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
    """Base request for adding a representation to a topic.

    Defines the common fields required when creating any type of representation
    for topic data, including the storage location, format, and version information.
    """

    association: Association
    storage_format: RepresentationStorageFormat
    version: int


class SetDefaultRepresentationRequest(BaseAddRepresentationRequest):
    """Request to set the default representation for a topic.

    Designates a specific representation as the default for accessing topic data.
    The default representation is used when no specific representation is requested
    for data access operations.
    """

    # 'ignore' used to avoid backwards incompatible change to remove `org_id` from BaseAddRepresentationRequest.
    # Should be changed back to 'forbid' for SDK v1.0
    model_config = pydantic.ConfigDict(extra="ignore")


class AddMessagePathRepresentationRequest(BaseAddRepresentationRequest):
    """Request to associate a message path with a representation.

    Creates a link between a specific message path and a data representation,
    enabling efficient access to individual fields within topic data.
    """

    message_path_id: str

    # 'ignore' used to avoid backwards incompatible change to remove `org_id` from BaseAddRepresentationRequest
    # Should be changed back to 'forbid' for SDK v1.0
    model_config = pydantic.ConfigDict(extra="ignore")


class MessagePathRepresentationMapping(pydantic.BaseModel):
    """Mapping between message paths and their data representation.

    Associates a set of message paths with a specific representation that contains
    their data. This mapping is used to efficiently locate and access data for
    specific message paths within topic representations.
    """

    message_paths: collections.abc.MutableSequence[MessagePathRecord]
    representation: RepresentationRecord


class AddMessagePathRequest(pydantic.BaseModel):
    """Request to add a new message path to a topic.

    Defines a new message path within a topic's schema, specifying its data type,
    canonical type, and initial metadata. Used during topic creation or when
    extending an existing topic's schema.

    Attributes:
        message_path: Dot-delimited path to the attribute (e.g., "pose.position.x").
        data_type: Native data type as it appears in the original data source
            (e.g., "float32", "geometry_msgs/Pose"). Used for display purposes.
        canonical_data_type: Normalized Roboto data type that enables specialized
            platform features for maps, images, timestamps, and other data.
        metadata: Initial key-value pairs to associate with the message path.
    """

    message_path: str
    data_type: str
    canonical_data_type: CanonicalDataType
    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this topic message path for discovery and search, e.g. "
        + "`{ 'min': 0.71, 'max': 1.77, 'classification': 'my-custom-classification-tag' }`",
    )

    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateMessagePathRequest(pydantic.BaseModel):
    """Request to update an existing message path within a topic.

    Allows modification of message path attributes including metadata, data type,
    and canonical data type. Used to correct or enhance message path definitions
    after initial creation.
    """

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

    model_config = pydantic.ConfigDict(extra="ignore")

    def has_updates(self) -> bool:
        """Check whether this request would result in any message path modifications.

        Returns:
            True if the request contains changes that would modify the message path.
        """

        return (
            is_set(self.data_type)
            or is_set(self.canonical_data_type)
            or (
                is_set(self.metadata_changeset)
                and self.metadata_changeset.has_changes()
            )
        )


class DeleteMessagePathRequest(pydantic.BaseModel):
    """Request to delete a message path from a topic.

    Removes a message path from a topic's schema. This operation cannot be undone
    and will remove all associated data and metadata for the specified path.
    """

    message_path: str
    """Message path name."""

    model_config = pydantic.ConfigDict(extra="ignore")


class MessagePathChangeset(pydantic.BaseModel):
    """Changeset for batch operations on topic message paths.

    Defines a collection of add, delete, and update operations to be applied
    to a topic's message paths in a single atomic operation. Useful for
    making multiple schema changes efficiently.
    """

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
        """Create a changeset that replaces all existing message paths.

        Creates a changeset that will replace all existing message paths on a topic
        with the provided set of message paths. This is useful for completely
        redefining a topic's schema.

        Args:
            message_paths: Sequence of message path requests to replace existing paths.

        Returns:
            MessagePathChangeset configured to replace all existing message paths.

        Examples:
            >>> from roboto.domain.topics import AddMessagePathRequest, CanonicalDataType
            >>> new_paths = [
            ...     AddMessagePathRequest(
            ...         message_path="velocity.x",
            ...         data_type="float32",
            ...         canonical_data_type=CanonicalDataType.Number
            ...     )
            ... ]
            >>> changeset = MessagePathChangeset.from_replacement_message_paths(new_paths)
        """
        return cls(message_paths_to_add=message_paths, replace_all=True)

    def has_changes(self) -> bool:
        """Check whether the changeset contains any actual changes.

        Returns:
            True if the changeset contains operations that would modify the topic's message paths.
        """

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
    """Request to create a new topic in the Roboto platform.

    Contains all the information needed to register a topic found within a source
    recording file, including its schema, temporal boundaries, and initial message paths.
    """

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
    """Request to update an existing topic's properties.

    Allows modification of topic attributes including temporal boundaries,
    message count, schema information, metadata, and message paths.
    """

    end_time: typing.Union[typing.Optional[int], NotSetType] = NotSet
    message_count: typing.Union[int, NotSetType] = NotSet
    schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet
    schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet
    start_time: typing.Union[typing.Optional[int], NotSetType] = NotSet
    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    message_path_changeset: typing.Union[MessagePathChangeset, NotSetType] = NotSet

    model_config = pydantic.ConfigDict(
        extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier
    )
