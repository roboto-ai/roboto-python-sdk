# Copyright (c) 2024 Roboto Technologies, Inc.
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
    """
    Supported representation format types
    """

    MCAP = "mcap"


class RepresentationRecord(pydantic.BaseModel):
    """
    Pointer to data extracted from a Topic--potentially a specific slice of the data,
    from within a MessagePath--processed for representation in a particular modality.

    Most MessagePaths within a Topic will point to the same Representation
    (e.g., an MCAP file with all of the Topic data).
    Some MessagePaths, however, may have more than one Representation,
    such as both an MCAP and a preview GIF or statically rendered, line-chart preview.
    """

    association: Association
    """
    Identifier and entity type with which this Representation is associated. E.g., a file, a database.
    """

    representation_id: str
    storage_format: RepresentationStorageFormat
    topic_id: str
    version: int


class CanonicalDataType(enum.Enum):
    """
    Well-known (and simplified) data types, normalized across frameworks/technologies.
    Primarily used for UI purposes to determine if a Panel can render a particular MessagePath.

    References:

        - ROS 1 field types: http://wiki.ros.org/msg
        - ROS 2 field types: https://docs.ros.org/en/iron/Concepts/Basic/About-Interfaces.html#field-types
        - uORB: there is no list of primitive field types, but they appear
          to be the same as ROS: https://docs.px4.io/main/en/middleware/uorb.html#adding-a-new-topic

    Example mappings:

        - ``float32`` -> ``DataType.Number``
        - ``uint8[]`` -> ``DataType.Array``
        - ``uint8[]`` -> ``DataType.Image``
        - ``geometry_msgs/Pose`` -> ``DataType.Object``
        - ``std_msgs/Header`` -> ``DataType.Object``
        - ``string`` -> ``DataType.String``
        - ``char`` -> ``DataType.String``
        - ``bool`` -> ``DataType.Boolean``
        - ``byte`` -> ``DataType.Byte``

    """

    Array = "array"  # A sequence of values.
    Boolean = "boolean"
    Byte = "byte"
    Image = "image"  # Special purpose type for data that can be rendered as an image.
    Number = "number"
    NumberArray = "number_array"
    Object = "object"  # A struct with attributes.
    String = "string"
    Unknown = "unknown"  # This is a fallback and should be used sparingly.

    # Special purpose types for data that represents geographic points
    LatDegFloat = "latdegfloat"  # e.g. 47.6749387 (used in ULog ver_data_format >= 2)
    LonDegFloat = "londegfloat"  # e.g. 9.1445274 (used in ULog ver_data_format >= 2)
    LatDegInt = "latdegint"  # e.g. 317534036 (used in ULog ver_data_format < 2)
    LonDegInt = "londegint"  # e.g. 1199146398 (used in ULog ver_data_format < 2)


class MessagePathStatistic(enum.Enum):
    """Statistics computed by Roboto in our standard ingestion actions."""

    Count = "count"
    Max = "max"
    Mean = "mean"
    Median = "median"
    Min = "min"


class MessagePathRecord(pydantic.BaseModel):
    """
    Path to a typed attribute within individual datum records contained within a Topic.
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
    """
    Collection of timestamped data that share a common name and association (e.g., file).

    Data from the same file within the same named topic/channel are considered part of the same Topic.
    Data from different files or with differently named topics/channels belong within unique Topics.

    Source files that have been chunked by time or size but from the same point-in-time data collection will
    produce multiple Topics for the same "logical topic" (~= name, schema) within those chunks.
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
