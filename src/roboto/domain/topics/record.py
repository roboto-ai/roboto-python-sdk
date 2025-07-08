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

    metadata: collections.abc.Mapping[str, typing.Any] = pydantic.Field(
        default_factory=dict,
    )
    """
    Key-value pairs to associate with this metadata for discovery and search, e.g.
    `{ 'min': '0.71', 'max': '1.77 }`
    """

    modified: datetime.datetime
    modified_by: str

    representations: collections.abc.MutableSequence[RepresentationRecord] = (
        pydantic.Field(default_factory=list)
    )
    """
    Zero to many Representations of this MessagePath.
    """

    topic_id: str

    org_id: str
    """
    This message path's organization ID, which is the organization ID of the containing topic.
    """

    message_path_id: str


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
