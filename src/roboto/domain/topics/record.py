# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import enum
import typing

import pydantic

from ...association import Association
from ...compat import StrEnum
from ...formats import FieldSelection
from ...warnings import experimental


class RepresentationSelector(pydantic.BaseModel):
    """Criteria for selecting among multiple representations of the same data.

    When a message path has multiple representations (e.g., both raw sensor data and
    a processed JPEG encoding), this is a *hard filter*: only matching representations
    qualify, and message paths with no matching representation are dropped from
    selection results — callers must handle empty or partial output.

    **Legacy carve-out for ``content_format``:** representations with no ``format`` set
    (i.e., predating the field) are treated as matching any ``content_format`` request.
    This keeps older data accessible. When both an explicit format match and a legacy
    representation are available for the same message path, the explicit match wins.

    Instances are immutable (``frozen=True``) so they can be safely shared — including
    as default arguments to methods like :py:meth:`Topic.get_data`.

    Attributes:
        content_format: If set, only representations whose ``format`` field matches
            this value qualify (e.g., ``"jpeg"``). Representations with no ``format``
            also qualify under the legacy carve-out. ``None`` means no constraint.
        transformations: If set, only representations whose ``transformations`` field
            matches exactly qualify. ``[]`` matches representations with no transformations
            (i.e., raw/original data). ``None`` means no constraint.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    content_format: typing.Optional[str] = None
    transformations: typing.Optional[list[str]] = None

    @classmethod
    def raw(cls) -> RepresentationSelector:
        """Select representations with no transformations applied (original data)."""
        return cls(transformations=[])

    def matches(self, representation: RepresentationRecord) -> bool:
        """Check whether a representation satisfies this selector's criteria.

        A representation matches when each non-``None`` selector field is satisfied.
        For ``content_format``, representations with no ``format`` set are treated
        as matching (legacy carve-out — see class docstring).
        """
        if self.content_format is not None:
            if representation.format is not None and representation.format != self.content_format:
                return False
        if self.transformations is not None and representation.transformations != self.transformations:
            return False
        return True

    def select_representations(
        self,
        mappings: list[MessagePathRepresentationMapping],
    ) -> list[MessagePathRepresentationMapping]:
        """Select one representation per message path that matches this selector.

        When the API returns multiple representations for the same message paths
        (e.g., both a raw MCAP and a processed JPEG MCAP for an image topic),
        this method picks a matching representation for each path and deduplicates
        so each message path appears in exactly one mapping.

        Non-matching representations are excluded. When both an explicit format match
        and a legacy representation (no ``format`` set) cover the same message path,
        the explicit match wins. Message paths covered by no matching representation
        are dropped — callers must handle empty or partial results.

        Args:
            mappings: All representation mappings, potentially with overlapping message paths.

        Returns:
            Deduplicated mappings of message paths to matching representations.
            Empty if no representation matches.
        """
        matched = [m for m in mappings if self.matches(m.representation)]

        # Prefer explicit content_format matches over legacy reps (where rep.format is
        # None and the legacy carve-out applies). Without a content_format constraint,
        # all matched mappings are equivalent.
        if self.content_format is not None:
            explicit = [m for m in matched if m.representation.format is not None]
            legacy = [m for m in matched if m.representation.format is None]
            ordered = explicit + legacy
        else:
            ordered = matched

        covered_message_path_ids: set[str] = set()
        selected: list[MessagePathRepresentationMapping] = []

        for mapping in ordered:
            remaining_paths = [mp for mp in mapping.message_paths if mp.message_path_id not in covered_message_path_ids]
            if remaining_paths:
                selected.append(
                    MessagePathRepresentationMapping(
                        representation=mapping.representation,
                        message_paths=remaining_paths,
                    )
                )
                covered_message_path_ids.update(mp.message_path_id for mp in remaining_paths)

        return selected


class RepresentationStorageFormat(enum.Enum):
    """Supported storage formats for topic data representations.

    Defines the available formats for storing and accessing topic data within
    the Roboto platform. Each format has different characteristics and use cases.
    """

    MCAP = "mcap"
    """MCAP format - optimized for robotics time-series data with efficient random access."""
    PARQUET = "parquet"
    """Parquet format - columnar storage optimized for analytics and large-scale data processing."""


class TransformationKind(StrEnum):
    """Canonical vocabulary of transformations that can be applied when producing a representation.

    A transformation is serialized into ``RepresentationRecord.transformations`` as a
    ``"<kind>:<param>"`` string (e.g. ``"downsample:0.5"``, ``"encode:jpeg"``). This enum is the
    source of truth for the set of supported kinds; the parameter tail remains free-form because
    different kinds carry different parameter shapes (floats, format tokens, etc.).

    Producers should construct transformation strings via :py:meth:`with_param` and consumers
    should destructure them via :py:meth:`parse` to keep the vocabulary centralized.

    Examples:
        >>> TransformationKind.DOWNSAMPLE.with_param(0.5)
        'downsample:0.5'
        >>> TransformationKind.parse("encode:jpeg")
        (<TransformationKind.ENCODE: 'encode'>, 'jpeg')
    """

    DOWNSAMPLE = "downsample"
    """Spatial or temporal downsampling. Parameter is a float scale factor in ``(0, 1]``."""
    ENCODE = "encode"
    """Re-encoding to a different content format. Parameter is the target format token (e.g. ``"jpeg"``)."""

    def with_param(self, param: object) -> str:
        """Construct a transformation descriptor string for this kind with the given parameter."""
        return f"{self.value}:{param}"

    @classmethod
    def parse(cls, descriptor: str) -> tuple[TransformationKind, str]:
        """Parse a ``"<kind>:<param>"`` transformation descriptor into its kind and raw parameter.

        Raises:
            ValueError: If the kind prefix is not a known :py:class:`TransformationKind` member.
        """
        kind, _, param = descriptor.partition(":")
        return cls(kind), param


class RepresentationRecord(pydantic.BaseModel):
    """Record representing a data representation for topic content.

    A representation is a pointer to processed topic data stored in a specific format
    and location. Representations enable efficient access to topic data by providing
    multiple storage formats optimized for different use cases.

    Most message paths within a topic point to the same representation (e.g., an MCAP or Parquet
    file containing all topic data). However, some message paths may have multiple
    representations for analytics or preview formats.

    Representations are versioned and associated with specific files or storage locations
    through the association field.
    """

    association: Association
    """
    Identifier and entity type with which this Representation is associated. E.g., a file, a database.
    """

    created: datetime.datetime

    format: typing.Optional[str] = None
    """
    Content format descriptor for this representation.
    For image topics: the image encoding (e.g. "jpeg", "png") for simplified representations,
    or the ROS schema name (e.g. "sensor_msgs/Image") for original/passthrough representations.
    None for non-image topics or legacy representations.
    """

    modified: datetime.datetime
    representation_id: str
    storage_format: RepresentationStorageFormat
    topic_id: str

    transformations: list[str] = pydantic.Field(default_factory=list)
    """
    Ordered list of transformation descriptors applied to produce this representation.
    Empty for original/passthrough representations.

    Each entry is a ``"<kind>:<param>"`` string where ``<kind>`` is a
    :py:class:`TransformationKind` member. Construct entries via
    :py:meth:`TransformationKind.with_param` and parse them via
    :py:meth:`TransformationKind.parse` to keep the vocabulary centralized.

    Example: ``["downsample:0.5", "encode:jpeg"]``
    """

    version: int


class CanonicalDataType(enum.Enum):
    """Normalized data types used across different robotics frameworks.

    Well-known and simplified data types that provide a common vocabulary for
    describing message path data types across different frameworks and technologies.
    These canonical types are primarily used for UI rendering decisions and
    cross-platform compatibility.

    The canonical types abstract away framework-specific details while preserving
    the essential characteristics needed for data processing and visualization.

    References:
        - ROS 1 field types: http://wiki.ros.org/msg
        - ROS 2 field types: https://docs.ros.org/en/iron/Concepts/Basic/About-Interfaces.html#field-types
        - uORB: https://docs.px4.io/main/en/middleware/uorb.html#adding-a-new-topic

    Example mappings:
        - ``float32`` -> ``CanonicalDataType.Number``
        - ``uint8[]`` -> ``CanonicalDataType.Array``
        - ``sensor_msgs/Image`` -> ``CanonicalDataType.Image``
        - ``geometry_msgs/Pose`` -> ``CanonicalDataType.Object``
        - ``std_msgs/Header`` -> ``CanonicalDataType.Object``
        - ``string`` -> ``CanonicalDataType.String``
        - ``char`` -> ``CanonicalDataType.String``
        - ``bool`` -> ``CanonicalDataType.Boolean``
        - ``byte`` -> ``CanonicalDataType.Byte``
    """

    Array = "array"
    """A sequence of values."""
    Boolean = "boolean"
    Byte = "byte"
    Categorical = "categorical"
    """
    Data that can take a limited, fixed set of values.
    To be interpreted correctly by Roboto clients,
    a ``MessagePathRecord`` with this type must have a ``"categories"`` metadata key on the ``MessagePathRecord``,
    which must be the ordered list of values that the Categorical can take.

    For example, a signal that is logged as either "off" or "on"
    could be represented as a Categorical with the metadata ``"categories"=["off", "on"]``.
    This allows Roboto to map the value "off" to 0 and "on" to 1
    --each corresponding to their index position in the metadata array--
    and therefore visualize these state transitions as a plot.

    The default visual representation of ``Categorical`` data will be the same as ``String`` data,
    but the Roboto visualizer will be capable of rendering Categorical data in a plot.
    """
    Image = "image"
    """Special purpose type for data that can be rendered as an image."""
    Number = "number"
    NumberArray = "number_array"
    Object = "object"
    """A struct with attributes."""
    String = "string"
    Timestamp = "timestamp"
    """
    Time elapsed since the Unix epoch, identifying a single instant on the time-line.
    Roboto clients will look for a ``"unit"`` metadata key on the ``MessagePath`` record,
    and will assume "ns" if none is found.
    If the timestamp is in a different unit, add the following metadata to the `MessagePath` record:
    ``{ "unit": "s"|"ms"|"us"|"ns" }``
    The unit must be a known value from :py:class:`~roboto.time.TimeUnit`.
    """
    Unknown = "unknown"
    """This is a fallback and should be used sparingly."""
    LatDegFloat = "latdegfloat"
    """Geographic point in degrees. E.g. 47.6749387 (used in ULog ver_data_format >= 2)"""
    LonDegFloat = "londegfloat"
    """Geographic point in degrees. E.g. 9.1445274  (used in ULog ver_data_format >= 2)"""
    LatDegInt = "latdegint"
    """Geographic point in degrees, expressed as an integer. E.g. 317534036 (used in ULog ver_data_format < 2)"""
    LonDegInt = "londegint"
    """Geographic point in degrees, expressed as an integer. E.g. 1199146398 (used in ULog ver_data_format < 2)"""


class MessagePathStatistic(enum.Enum):
    """Statistics computed by Roboto in our standard ingestion actions."""

    Count = "count"
    Max = "max"
    Mean = "mean"
    Median = "median"
    Min = "min"


class MessagePathMetadataWellKnown(StrEnum):
    """
    Well-known metadata key names (with well-known semantics) that may be set in
    :py:attr:`~roboto.domain.topics.MessagePathRecord.metadata`.

    These are most often set by Roboto's first-party ingestion actions and used by Roboto clients.
    """

    ColumnName = "column_name"
    """
    The original name or path to this field in the source data schema.
    May differ from :py:attr:`~roboto.domain.topics.MessagePathRecord.message_path`
    if character substitutions were applied to conform to naming requirements.

    Notes:
        - Use of this metadata field is soft-deprecated as of SDK v0.24.0.
        - Prefer use of :py:attr:`~roboto.domain.topics.MessagePathRecord.source_path` and
          :py:attr:`~roboto.domain.topics.MessagePathRecord.path_in_schema` instead.
          Those attributes are now first-class fields on :py:class:`~MessagePathRecord`
          and can be specified via :py:class:`~roboto.domain.topics.AddMessagePathRequest`.
    """

    Categories = "categories"
    """
    An ordered list of values that a :py:attr:`~roboto.domain.topics.CanonicalDataType.Categorical` can take.

    Examples:
        - ``"categories"=["off", "on"]``
        - ``"categories"=["left", "up", "right", "down"]``
    """

    Unit = "unit"
    """
    Unit of a field. E.g., 'ns' for a timestamp.
    If provided, must match a known, supported unit from :py:class:`~roboto.time.TimeUnit`.
    """


class MessagePathRecord(pydantic.BaseModel):
    """Record representing a message path within a topic.

    Defines a specific field or signal within a topic's data schema, including
    its data type, metadata, and statistical information. Message paths use
    dot notation to specify nested attributes within complex message structures.

    Message paths are the fundamental units for accessing individual data elements
    within time-series robotics data, enabling fine-grained analysis and visualization
    of specific signals or measurements.
    """

    canonical_data_type: CanonicalDataType
    """Normalized data type, used primarily internally by the Roboto Platform."""

    created: datetime.datetime
    created_by: str

    data_type: str
    """
    'Native'/framework-specific data type of the attribute at this path.
    E.g. "float32", "uint8[]", "geometry_msgs/Pose", "string".
    """

    message_path: str
    """
    Dot-delimited path to the attribute within the datum record.
    """

    message_path_id: str

    metadata: collections.abc.Mapping[str, typing.Any] = pydantic.Field(
        default_factory=dict,
    )
    """
    Key-value pairs to associate with this metadata for discovery and search, e.g.
    `{ 'min': '0.71', 'max': '1.77 }`
    """

    modified: datetime.datetime
    modified_by: str

    org_id: str
    """
    This message path's organization ID, which is the organization ID of the containing topic.
    """

    path_in_schema: list[str]
    """
    List of path components representing the field's location in the original data schema.
    Unlike :py:attr:`message_path`, which must conform to Roboto-specific naming requirements
    and assumes dots separated path parts imply nested data,
    this preserves the exact path from the source data for accurate attribute access.
    This is expected to be the split representation of :py:attr:`source_path`.
    """

    representations: collections.abc.MutableSequence[RepresentationRecord] = pydantic.Field(default_factory=list)
    """
    Zero to many Representations of this MessagePath.
    """

    source_path: str
    """
    The original name of this field in the source data schema.
    May differ from :py:attr:`message_path` if character substitutions were applied to conform to naming requirements.

    This is the preferred field to use when specifying ``message_path_include`` or
    ``message_path_exclude`` to the ``get_data`` or ``get_data_as_df`` methods
    of :py:class:`~roboto.domain.topics.Topic` and :py:class:`~roboto.domain.events.Event`.
    """

    topic_id: str

    def parents(self, delimiter: str = ".") -> list[str]:
        """
        Logical message path ancestors of this path.

        Examples:
            Given a deeply nested field ``root.sub_obj_1.sub_obj_2.leaf_field``:

            >>> field = "root.sub_obj_1.sub_obj_2.leaf_field"
            >>> record = MessagePathRecord(message_path=field)  # other fields omitted for brevity
            >>> print(record.parents())
            ['root.sub_obj_1.sub_obj_2', 'root.sub_obj_1', 'root']
        """
        parent_path_parts = self.path_in_schema[:-1]
        return [delimiter.join(parent_path_parts[:i]) for i in range(len(parent_path_parts), 0, -1)]

    def to_field_selection(self) -> FieldSelection:
        """Translate this record into the :py:class:`~roboto.formats.FieldSelection` the format decoders accept."""
        return FieldSelection(path_in_schema=tuple(self.path_in_schema))


class MessagePathRepresentationMapping(pydantic.BaseModel):
    """Mapping between message paths and their data representation.

    Associates a set of message paths with a specific representation that contains
    their data. This mapping is used to efficiently locate and access data for
    specific message paths within topic representations.
    """

    message_paths: collections.abc.MutableSequence[MessagePathRecord]
    representation: RepresentationRecord


class TopicRecord(pydantic.BaseModel):
    """Record representing a topic in the Roboto platform.

    A topic is a collection of timestamped data records that share a common name
    and association (typically a file). Topics represent logical data streams
    from robotics systems, such as sensor readings, robot state information,
    or other time-series data.

    Data from the same file with the same topic name are considered part of the
    same topic. Data from different files or with different topic names belong
    to separate topics, even if they have similar schemas.

    When source files are chunked by time or size but represent the same logical
    data collection, they will produce multiple topic records for the same
    "logical topic" (same name and schema) across those chunks.
    """

    association: Association
    """
    Identifier and entity type with which this Topic is associated. E.g., a file, a dataset.
    """

    created: datetime.datetime

    created_by: str

    default_representation: typing.Optional[RepresentationRecord] = None
    """
    Default Representation for this Topic.
    Assume that if a MessagePath is not more specifically associated with a Representation,
    it should use this one.
    """

    end_time: typing.Optional[int] = None
    """
    Timestamp of oldest message in topic, in nanoseconds since epoch (assumed Unix epoch).
    """

    message_count: typing.Optional[int] = None

    message_paths: collections.abc.MutableSequence[MessagePathRecord] = pydantic.Field(default_factory=list)
    """
    Zero to many MessagePathRecords associated with this TopicSource.
    """

    metadata: collections.abc.Mapping[str, typing.Any] = pydantic.Field(default_factory=dict)
    """
    Arbitrary metadata.
    """

    modified: datetime.datetime

    modified_by: str

    org_id: str

    schema_checksum: typing.Optional[str] = None
    """
    Checksum of topic schema.
    May be None if topic does not have a known/named schema.
    """

    schema_id: typing.Optional[str] = None
    """
    ID of the schema record for this topic.
    May be None if the topic has no schema, or if the schema record has not yet been populated.
    """

    schema_name: typing.Optional[str] = None
    """
    Type of messages in topic. E.g., "sensor_msgs/PointCloud2".
    May be None if topic does not have a known/named schema.
    """

    start_time: typing.Optional[int] = None
    """
    Timestamp of earliest message in topic, in nanoseconds since epoch (assumed Unix epoch).
    """

    topic_id: str
    topic_name: str


FieldPath = tuple[str, ...]
"""A schema field's path components, in order from the schema root to the leaf."""


@experimental
class SchemaFieldRecord(pydantic.BaseModel):
    """A single field within a topic schema.

    One entry per unique field path within a schema;
    field paths are deduplicated across topics that share the schema.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    canonical_data_type: CanonicalDataType
    """Normalized data type used for cross-framework compatibility and UI rendering decisions."""

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    data_type: str
    """Native, framework-specific data type of the field. E.g. "float32", "uint8[]", "geometry_msgs/Pose"."""

    field_id: str
    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: str
    """Human-readable display name of the field (typically the final component of ``path_in_schema``)."""

    org_id: str
    path_in_schema: FieldPath
    """
    Path components locating this field in the source data schema.
    Each component is a schema-native attribute name, in order from the schema root to the leaf.
    """

    schema_id: str
    unit: typing.Optional[str] = None
    """Optional unit of the field's values (e.g., ``"ns"``, ``"m/s"``). None if the field is unitless or unknown."""


@experimental
class TopicSchemaRecord(pydantic.BaseModel):
    """A content-addressed topic schema.

    Within an organization, two schemas with identical fields share a single record
    (identified by a deterministic checksum of the fields).
    ``name`` is a mutable, informational label (last-writer-wins) and is not part of the schema's identity.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    checksum: str
    """Deterministic checksum computed over the schema's fields; identical schemas share a checksum."""

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: typing.Optional[str] = None
    """Informational label for the schema (e.g., ``"sensor_msgs/PointCloud2"``). Not part of identity."""

    org_id: str
    schema_id: str
    """Stable identifier for this schema record."""


@experimental
class TopicIdentityRecord(pydantic.BaseModel):
    """A durable log-stream identity.

    Within an organization, topic names are unique.
    Contributions from different files with the same topic name share a single identity record.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: str
    """Human-readable topic name (e.g., ``"/camera/image_raw"``). Unique within an organization."""

    org_id: str
    topic_id: str
    """Stable identifier for this topic identity."""


TimelineSourceKind: typing.TypeAlias = typing.Literal["schema_field", "message_log_time", "message_publish_time"]
"""Discriminator for how a ``TimelineSourceRecord`` derives its timestamps.

``"schema_field"`` points at a timestamp field inside the schema (``field_id`` is set).
``"message_log_time"`` and ``"message_publish_time"`` point at the message envelope's
log or publish timestamp respectively (``field_id`` is ``None``).
"""


@experimental
class TimelineSourceRecord(pydantic.BaseModel):
    """A registered time source for a schema.

    A time source either points at a timestamp field inside the schema
    (``source="schema_field"``, ``field_id`` set) or at the message envelope's
    log or publish timestamp (``source`` in ``{"message_log_time", "message_publish_time"}``,
    ``field_id`` is ``None``). Time sources are scoped to a schema, not a topic, so
    topics that share a schema share their time sources.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    field_id: typing.Optional[str] = None
    """ID of the schema field supplying timestamps. Set when ``source == "schema_field"``; otherwise ``None``."""

    is_default: bool = False
    """Whether this time source is the default for its schema when no source is specified explicitly."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: str
    """Human-readable label for this time source."""

    org_id: str
    schema_id: str
    """ID of the schema this time source is registered against."""

    source: TimelineSourceKind
    """
    Where timestamps come from: a schema field (``"schema_field"``), or the message envelope's
    log or publish timestamp (``"message_log_time"`` / ``"message_publish_time"``).
    """

    timeline_source_id: str

    @pydantic.model_validator(mode="after")
    def _check_source_field_id(self) -> typing.Self:
        if self.source == "schema_field" and self.field_id is None:
            raise ValueError("field_id is required when source is 'schema_field'")
        if self.source != "schema_field" and self.field_id is not None:
            raise ValueError("field_id must be None when source is not 'schema_field'")
        return self


@experimental
class TimelineExtentRecord(pydantic.BaseModel):
    """Min/max timestamp bounds for one topic partition measured against one timeline source.

    Written by ingest when a partition's timestamps are summarized for a given source
    (e.g., a schema timestamp field, or message log/publish time).

    Stored timestamps come through verbatim from the data source: they may be absolute
    nanoseconds since the Unix epoch, or partition-relative (e.g., monotonic from zero).
    ``unix_epoch_offset_ns`` is the calibration that projects stored values onto
    Unix-epoch wall-clock: ``session_time_ns = stored_time_ns + unix_epoch_offset_ns``.
    A value of 0 means the stored timestamps are already absolute Unix-epoch ns,
    or that no calibration has been applied yet.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    max_timestamp: typing.Optional[int] = None
    """Largest stored timestamp in this extent, in nanoseconds. Absolute or partition-relative per the source."""

    min_timestamp: typing.Optional[int] = None
    """Smallest stored timestamp in this extent, in nanoseconds. Absolute or partition-relative per the source."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    org_id: str
    timeline_extent_id: str
    timeline_source_id: str
    """ID of the timeline source these bounds are measured against."""

    topic_part_id: str
    """ID of the topic partition these bounds apply to."""

    unix_epoch_offset_ns: int = 0
    """
    Nanoseconds to add to each stored timestamp to obtain Unix-epoch wall-clock time:
    ``session_time_ns = stored_time_ns + unix_epoch_offset_ns``.
    0 when stored timestamps are already absolute Unix-epoch ns, or when no calibration
    has been recorded for this partition/source pair.
    """


@experimental
class TopicPartitionRecord(pydantic.BaseModel):
    """One file's contribution to a logical topic.

    Pairs a topic identity with a file and carries the per-contribution facts that vary by file:
    the schema used (``schema_id``), message count, device provenance, and,
    for formats that pack multiple logical groups into one file, sub-file segmentation
    (``segment_index``, ``segment_name``) and row-level storage bounds (``data_from_index``, ``data_to_index``).
    Row bounds are half-open ``[data_from_index, data_to_index)``, matching Python slice semantics; both are set
    together for a row-bounded partition, or both are ``None`` when the partition covers the whole file.
    A partition references a file, not a specific version; reads always resolve to the current version.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    data_from_index: typing.Optional[int] = None
    """
    Inclusive lower bound of this partition's row range within the file, or ``None`` if
    the partition covers the whole file. Must be set if and only if ``data_to_index`` is set.
    """

    data_to_index: typing.Optional[int] = None
    """
    Exclusive upper bound of this partition's row range within the file, forming a half-open
    range ``[data_from_index, data_to_index)``. ``None`` if the partition covers the whole file.
    Must be set if and only if ``data_from_index`` is set, and strictly greater than it.
    """

    device_id: typing.Optional[str] = None
    """ID of the device that produced this contribution, if known."""

    fs_node_id: str
    """ID of the file this partition's data lives in."""

    message_count: typing.Optional[int] = None
    """Number of messages this partition contributes, if known."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    org_id: str
    schema_id: str
    """ID of the schema this contribution conforms to."""

    segment_index: int = 0
    """
    Zero-based index of the logical segment within the file this partition represents.
    0 for formats that hold a single logical group per file.
    """

    segment_name: typing.Optional[str] = None
    """Optional human-readable name for this segment, when the file format names its segments."""

    topic_id: str
    """ID of the topic identity this contribution belongs to."""

    topic_part_id: str

    @pydantic.model_validator(mode="after")
    def _check_data_index_range(self) -> "TopicPartitionRecord":
        # Row-level storage bounds are half-open [data_from_index, data_to_index),
        # matching LeRobot's dataset_from_index / dataset_to_index and Python
        # slice semantics. Either both are set (a row-bounded partition) or
        # both are NULL (the whole file is this partition's data).
        from_idx = self.data_from_index
        to_idx = self.data_to_index
        if (from_idx is None) != (to_idx is None):
            raise ValueError(
                "data_from_index and data_to_index must both be set or both be None "
                f"(got data_from_index={from_idx!r}, data_to_index={to_idx!r})"
            )
        if from_idx is not None and to_idx is not None and from_idx >= to_idx:
            raise ValueError(
                "data_from_index must be strictly less than data_to_index "
                f"(got data_from_index={from_idx!r}, data_to_index={to_idx!r})"
            )
        return self
