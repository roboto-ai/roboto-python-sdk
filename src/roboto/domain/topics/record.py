# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import enum
import typing

import pydantic

from ...association import Association


class RepresentationStorageFormat(enum.Enum):
    """Supported storage formats for topic data representations.

    Defines the available formats for storing and accessing topic data within
    the Roboto platform. Each format has different characteristics and use cases.
    """

    MCAP = "mcap"
    """MCAP format - optimized for robotics time-series data with efficient random access."""
    PARQUET = "parquet"
    """Parquet format - columnar storage optimized for analytics and large-scale data processing."""


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
    modified: datetime.datetime
    representation_id: str
    storage_format: RepresentationStorageFormat
    topic_id: str
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


class MessagePathMetadataWellKnown(str, enum.Enum):
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
          While those attributes are currently derived from metadata stored in this key,
          first-class support for specifying those attributes will be added to
          :py:class:`~MessagePathRecord` creation/update APIs in an upcoming SDK release.
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

    representations: collections.abc.MutableSequence[RepresentationRecord] = (
        pydantic.Field(default_factory=list)
    )
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
            >>> record = MessagePathRecord(message_path=field) # other fields omitted for brevity
            >>> print(record.parents())
            ['root.sub_obj_1.sub_obj_2', 'root.sub_obj_1', 'root']
        """
        parent_path_parts = self.path_in_schema[:-1]
        return [
            delimiter.join(parent_path_parts[:i])
            for i in range(len(parent_path_parts), 0, -1)
        ]


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

    message_paths: collections.abc.MutableSequence[MessagePathRecord] = pydantic.Field(
        default_factory=list
    )
    """
    Zero to many MessagePathRecords associated with this TopicSource.
    """

    metadata: collections.abc.Mapping[str, typing.Any] = pydantic.Field(
        default_factory=dict
    )
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
