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
from ...int64 import INT64_MAX
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
)
from ...time import _EpochNanosecondsFromTime, _NanosecondsFromInteger
from ...updates import (
    MetadataChangeset,
    TaglessMetadataChangeset,
)
from .record import (
    CanonicalDataType,
    RepresentationStorageFormat,
)


class BaseAddRepresentationRequest(pydantic.BaseModel):
    """Fields shared by the requests that register a representation of a topic's data.

    A representation is a stored copy of a topic's data in one format, such as an MCAP or Parquet file. Within a
    topic, ``association``, ``storage_format`` and ``version`` together identify a representation, so registering a
    combination the topic already has updates that representation's ``format`` and ``transformations`` instead of
    adding another.
    """

    association: Association
    """File, or other resource, that holds the representation's data. It must exist."""

    storage_format: RepresentationStorageFormat
    """Format the representation's data is stored in."""

    version: int
    """Version number of the representation."""

    format: typing.Optional[str] = None
    """Content format of the data, such as an image encoding or a ROS schema name.

    For example ``"jpeg"`` or ``"sensor_msgs/Image"``. ``None`` keeps the stored format when the representation
    already exists.
    """

    transformations: typing.Optional[list[str]] = None
    """Transformations applied to produce the representation, in order.

    Each is a ``"<kind>:<param>"`` string such as ``"downsample:0.5"`` (see
    :py:class:`~roboto.domain.topics.TransformationKind`).

    ``None`` keeps the stored list when the representation already exists, and records none otherwise. An empty list
    clears it.
    """


class SetDefaultRepresentationRequest(BaseAddRepresentationRequest):
    """Request body for :py:meth:`~roboto.domain.topics.Topic.set_default_representation`.

    Registers the representation and makes it the topic's default, which Roboto reads for every message path that
    has no representation of its own. The topic's other representations stay registered and stop being the default.
    """

    # Ignores unknown fields, rather than refusing them, so that requests from older SDK versions, which send
    # org_id, still validate.
    model_config = pydantic.ConfigDict(extra="ignore")


class AddMessagePathRepresentationRequest(BaseAddRepresentationRequest):
    """Request body for :py:meth:`~roboto.domain.topics.Topic.add_message_path_representation`.

    Registers the representation and links it to one of the topic's message paths.
    """

    message_path_id: str
    """ID of the message path the representation holds data for, beginning with ``mp_``.

    A message path of another topic fails the request with ``RobotoNotFoundException``.
    """

    # Ignores unknown fields, rather than refusing them, so that requests from older SDK versions, which send
    # org_id, still validate.
    model_config = pydantic.ConfigDict(extra="ignore")


class AddMessagePathRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.topics.Topic.add_message_path`.

    Also describes each message path a topic is created with (``CreateTopicRequest``) or gains in an update
    (``MessagePathChangeset``).
    """

    message_path: str
    """Dot-delimited path to a field within the topic's messages, such as ``"pose.position.x"``.

    Unique within the topic.
    """

    data_type: str
    """Data type of the field as the source data names it, such as ``"float32"`` or ``"geometry_msgs/Pose"``."""

    canonical_data_type: CanonicalDataType
    """Roboto data type of the field, which determines how Roboto interprets and visualizes it.

    For example, it decides whether Roboto treats the field as a location on a map, an image, or a timestamp.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description="Initial key-value pairs to associate with this topic message path for discovery and search, e.g. "
        + "`{ 'min': 0.71, 'max': 1.77, 'classification': 'my-custom-classification-tag' }`",
    )
    """Key-value metadata to set on the message path, such as ``{"min": 0.71, "max": 1.77}``."""

    path_in_schema: list[str] = pydantic.Field(
        description="List of path components representing the field's location in the source data schema. "
        "For nested fields like 'position.x', this would be ['position', 'x'].",
    )
    """Path components of the field in the source data's schema, outermost first.

    For example, ``["position", "x"]`` for ``position.x``.

    Unlike ``message_path``, which splits on dots, it keeps a field name that contains a dot as one component.
    """

    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateMessagePathRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.topics.Topic.update_message_path`.

    Also describes each update in ``MessagePathChangeset.message_paths_to_update``. A field left unset (``NotSet``)
    leaves that property of the message path unchanged.
    """

    message_path: str
    """Dot-delimited path of the message path to update, such as ``"pose.position.x"``.

    When the topic has no message path at this path, :py:meth:`~roboto.domain.topics.Topic.update_message_path`
    fails with ``RobotoNotFoundException``, and a changeset skips the update.
    """

    metadata_changeset: typing.Union[TaglessMetadataChangeset, NotSetType] = NotSet
    """Changes to the message path's metadata."""

    data_type: typing.Union[str, NotSetType] = NotSet
    """Data type of the field as the source data names it, such as ``"float32"``."""

    canonical_data_type: typing.Union[CanonicalDataType, NotSetType] = NotSet
    """Roboto data type of the field. Changing it changes how Roboto interprets and visualizes the field's data."""

    path_in_schema: typing.Union[list[str], NotSetType] = NotSet
    """Path components of the field in the source data's schema, outermost first, such as ``["position", "x"]``."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    def has_updates(self) -> bool:
        """Return whether the request changes anything about the message path.

        A ``metadata_changeset`` with no changes in it does not count.
        """

        return (
            is_set(self.data_type)
            or is_set(self.canonical_data_type)
            or is_set(self.path_in_schema)
            or (is_set(self.metadata_changeset) and self.metadata_changeset.has_changes())
        )


class DeleteMessagePathRequest(pydantic.BaseModel):
    """One message path to delete from a topic.

    Carried in ``MessagePathChangeset.message_paths_to_delete``. Deleting a message path deletes its metadata, and
    also deletes any event that was linked to nothing but the deleted message paths. It cannot be undone.
    """

    message_path: str
    """Dot-delimited path of the message path to delete. A path the topic does not have is skipped."""

    model_config = pydantic.ConfigDict(extra="ignore")


class MessagePathChangeset(pydantic.BaseModel):
    """Message paths to add, update, and delete on a topic, passed to :py:meth:`~roboto.domain.topics.Topic.update`.

    Roboto applies the changeset together with the rest of the topic update: all of it, or none of it if any part is
    refused. To replace every message path on a topic, build the changeset with ``from_replacement_message_paths``.
    Building a changeset that breaks the requirements of ``replace_all`` raises ``pydantic.ValidationError``.
    """

    message_paths_to_add: typing.Union[collections.abc.Sequence[AddMessagePathRequest], None] = None
    """Message paths to add.

    Adding a path the topic already has fails the update with ``RobotoConflictException``, unless ``replace_all`` is
    set.
    """

    message_paths_to_delete: typing.Union[collections.abc.Sequence[DeleteMessagePathRequest], None] = None
    """Message paths to delete. A path the topic does not have is skipped."""

    message_paths_to_update: typing.Union[collections.abc.Sequence[UpdateMessagePathRequest], None] = None
    """Message paths to update. A path the topic does not have is skipped."""

    replace_all: bool = False
    """Whether ``message_paths_to_add`` replaces every message path on the topic.

    When set, Roboto deletes each existing message path the list leaves out, overwrites the data type, canonical data
    type, path in schema, and metadata of each one it repeats, and adds the rest. Requires ``message_paths_to_add``,
    with ``message_paths_to_update`` and ``message_paths_to_delete`` left ``None``.
    """

    @model_validator(mode="after")
    def check_replace_all_correctness(self) -> MessagePathChangeset:
        """Reject a changeset that sets ``replace_all`` without ``message_paths_to_add``, or with either other list."""
        if self.replace_all and (
            self.message_paths_to_add is None
            or not (self.message_paths_to_update is None and self.message_paths_to_delete is None)
        ):
            raise ValueError("replace_all must only be used with message_paths_to_add")

        return self

    @classmethod
    def from_replacement_message_paths(
        cls, message_paths: collections.abc.Sequence[AddMessagePathRequest]
    ) -> MessagePathChangeset:
        """Build a changeset that replaces every message path on a topic with ``message_paths``.

        ``MessagePathChangeset.from_replacement_message_paths(paths)`` builds the same changeset as
        ``MessagePathChangeset(message_paths_to_add=paths, replace_all=True)``.

        Args:
            message_paths: Message paths the topic has after the update.
        """
        return cls(message_paths_to_add=message_paths, replace_all=True)

    def has_changes(self) -> bool:
        """Return whether applying the changeset would change the topic's message paths.

        A changeset with ``replace_all`` set always counts, even with an empty list, because it deletes every message
        path the list leaves out.
        """

        return self.replace_all or not (
            (self.message_paths_to_add is None or not self.message_paths_to_add)
            and (self.message_paths_to_update is None or not self.message_paths_to_update)
            and (self.message_paths_to_delete is None or not self.message_paths_to_delete)
        )


class CreateTopicRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.topics.Topic.create`, which registers a topic found in a file."""

    association: Association
    """File, or other resource, the topic belongs to. It must exist."""

    topic_name: str
    """Name of the topic, such as ``"/imu/data"``.

    Must not be blank, and must be unique within ``association``: a name already taken fails with
    ``RobotoConflictException``.
    """

    end_time: typing.Optional[_NanosecondsFromInteger] = None
    """End of the topic's data, in nanoseconds since the Unix epoch. Must not be negative."""

    message_count: typing.Optional[int] = None
    """Number of messages in the topic. Must not be negative."""

    metadata: typing.Optional[collections.abc.Mapping[str, typing.Any]] = None
    """Key-value metadata to set on the topic."""

    schema_checksum: typing.Optional[str] = None
    """Checksum of the topic's message schema."""

    schema_name: typing.Optional[str] = None
    """Name of the topic's message schema, such as ``"sensor_msgs/Imu"``."""

    start_time: typing.Optional[_NanosecondsFromInteger] = None
    """Start of the topic's data, in nanoseconds since the Unix epoch. Must not be negative."""

    message_paths: typing.Optional[collections.abc.Sequence[AddMessagePathRequest]] = None
    """Message paths to create with the topic.

    No two may have the same ``message_path``. When ``schema_name`` is also set, they define the topic's schema.
    """

    # Ignores unknown fields, rather than refusing them, so that requests from older SDK versions, which send
    # org_id, still validate.
    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateTopicRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.topics.Topic.update`.

    A field left unset (``NotSet``) leaves that property of the topic unchanged.
    """

    end_time: typing.Union[typing.Optional[_NanosecondsFromInteger], NotSetType] = NotSet
    """End of the topic's data, in nanoseconds since the Unix epoch.

    Must not be negative, and must not be before ``start_time`` when the request sets both. ``None`` clears it.
    """

    message_count: typing.Union[int, NotSetType] = NotSet
    """Number of messages in the topic. Must not be negative."""

    schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet
    """Checksum of the topic's message schema.

    Setting it requires a schema name, already on the topic or set by this request. ``None`` clears it.
    """

    schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet
    """Name of the topic's message schema, such as ``"sensor_msgs/Imu"``.

    ``None`` clears it; when the topic has a schema checksum, the request must clear that too.
    """

    start_time: typing.Union[typing.Optional[_NanosecondsFromInteger], NotSetType] = NotSet
    """Start of the topic's data, in nanoseconds since the Unix epoch. Must not be negative. ``None`` clears it."""

    metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the topic's metadata. Topics have no tags, so the changeset's tag changes have no effect."""

    message_path_changeset: typing.Union[MessagePathChangeset, NotSetType] = NotSet
    """Message paths to add, update, and delete."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class TimelineOffsetEntry(pydantic.BaseModel):
    """One offset to apply to a file's timelines.

    Carried in ``SetTimelineOffsetsRequest.offsets``. With no selector set, the offset applies to every timeline on
    the file. ``topic_name`` limits it to one topic, and ``timeline_source_name`` or ``timeline_source_id`` (at most
    one of them) limits it to some of the topic's timeline sources. Sent by ``File.set_timeline_offsets``.

    Building it raises ``pydantic.ValidationError`` when:

    - it sets both ``timeline_source_name`` and ``timeline_source_id``.
    - ``unix_epoch_offset_ns`` is negative or greater than :py:const:`~roboto.int64.INT64_MAX`.
    - ``unix_epoch_offset_ns`` is not a time that :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    unix_epoch_offset_ns: _EpochNanosecondsFromTime = pydantic.Field(ge=0, le=INT64_MAX)
    """Nanoseconds to add to the file's stored timestamps to make them Unix-epoch time.

    That is, ``unix_epoch_time_ns = stored_time_ns + unix_epoch_offset_ns``.

    Must be from 0 to ``2**63 - 1``, the largest signed 64-bit integer (:py:const:`~roboto.int64.INT64_MAX`). Also
    accepts any :py:const:`~roboto.time.Time`, converted by :py:func:`~roboto.time.to_epoch_nanoseconds`, so a
    ``datetime`` gives the instant at which stored time 0 occurred. A type checker accepts only an ``int``; convert
    other values with that function first.
    """

    topic_name: typing.Optional[str] = None
    """Name of the topic to apply the offset to, such as ``"/imu/raw"``.

    Topic names are unique within a file. ``None`` applies it to every topic.
    """

    timeline_source_name: typing.Optional[str] = None
    """Name of the timeline sources to apply the offset to, such as ``"header.stamp"``.

    Names are not unique, so the offset applies to every source of this name, within ``topic_name`` when it is set.
    ``None`` applies it to every source.
    """

    timeline_source_id: typing.Optional[str] = None
    """ID of the one timeline source to apply the offset to.

    Take it from the source's ``TimelineSourceRecord``. Set at most one of this and
    ``timeline_source_name``.
    """

    @model_validator(mode="after")
    def _check_timeline_source_selector(self) -> "TimelineOffsetEntry":
        if self.timeline_source_name is not None and self.timeline_source_id is not None:
            raise ValueError("Specify at most one of timeline_source_name, timeline_source_id.")
        return self


class SetTimelineOffsetsRequest(pydantic.BaseModel):
    """Request body for ``File.set_timeline_offsets``.

    Roboto applies every entry, or none of them if any is refused. Building a request with no entries raises
    ``pydantic.ValidationError``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    offsets: list[TimelineOffsetEntry] = pydantic.Field(min_length=1)
    """Offsets to apply, at least one.

    An entry whose selectors match none of the file's timelines is skipped, as long as another entry matches one; a
    request whose entries together match none fails with ``RobotoNotFoundException``. When two entries match the
    same timeline, the later entry's offset applies.
    """


class TimelineSourceUpdate(pydantic.BaseModel):
    """Request body for ``PUT /v2/topics/schema/id/{schema_id}/timeline-sources/{timeline_source_id}``.

    Renames a timeline source, changes whether it is its schema's default, or both. A field left unset (``NotSet``)
    leaves that property unchanged.
    """

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    is_default: typing.Union[bool, NotSetType] = NotSet
    """Whether the source is its schema's default.

    ``True`` moves the default to this source from the schema's current default. ``False`` on the default source
    leaves the schema with no default, so reads of its topics must name a source until another becomes the default.
    """

    name: typing.Union[str, NotSetType] = NotSet
    """Human-readable name of the timeline source. Names are not unique within a schema."""
