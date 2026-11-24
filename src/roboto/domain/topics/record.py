# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import datetime
import enum
import re
import typing

import pydantic

from ...association import Association
from ...compat import StrEnum
from ...formats import FieldSelection
from ...int64 import INT64_MAX
from ...warnings import experimental


class RepresentationSelector(pydantic.BaseModel):
    """Criteria for choosing which of a message path's representations to read.

    A message path can have several representations, such as the original image messages and a JPEG encoding of
    them. A read uses only the representations that meet every criterion set on the selector, and leaves out a
    message path with no such representation, so it can return some of the requested message paths or none of them.

    Instances are immutable, so one instance can serve as a default argument, as it does in
    :py:meth:`~roboto.domain.topics.Topic.get_data`.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    content_format: typing.Optional[str] = None
    """Content format that a representation's ``format`` must equal, such as ``"jpeg"``, or ``None`` for no requirement.

    A representation whose ``format`` is ``None`` meets any value.
    """

    transformations: typing.Optional[list[str]] = None
    """Transformations that a representation's ``transformations`` must equal, in order, or ``None`` for no requirement.

    ``[]`` requires a representation with no transformations: the original data.
    """

    @classmethod
    def raw(cls) -> RepresentationSelector:
        """Build a selector that requires the original data: a representation with no transformations."""
        return cls(transformations=[])

    def matches(self, representation: RepresentationRecord) -> bool:
        """Return whether ``representation`` meets every criterion set on this selector."""
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
        """Choose one matching representation for each message path in ``mappings``.

        :py:meth:`~roboto.domain.topics.Topic.get_data` and :py:meth:`~roboto.domain.topics.Topic.get_data_as_df`
        choose representations through it, so most code never calls it.

        A topic can have several representations covering the same message paths, such as an MCAP file of the
        original data and an MCAP file of JPEG-encoded images for an image topic. Mappings whose representation does
        not match are dropped, and each message path goes to the first remaining mapping that covers it. When
        ``content_format`` is set, representations whose ``format`` equals it come before those whose ``format`` is
        ``None``; otherwise the order of ``mappings`` decides. A message path that no matching representation covers
        is left out.

        Args:
            mappings: Message paths paired with the representations that hold their data. A message path can
                appear in more than one mapping.

        Returns:
            Mappings in which each message path appears at most once, or an empty list when no representation
            matches.
        """
        matched = [m for m in mappings if self.matches(m.representation)]

        # matches() already required any representation with a format to equal content_format, so listing those
        # first lets an exact format match cover a message path before a representation with no format can.
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
    """File format that a representation's data is stored in."""

    MCAP = "mcap"
    """MCAP, a container format for timestamped robotics messages."""
    PARQUET = "parquet"
    """Apache Parquet, a columnar file format."""


class TransformationKind(StrEnum):
    """Kind of transformation applied to a topic's data to produce a representation of it.

    A representation lists each transformation applied to it in ``RepresentationRecord.transformations``, as a
    ``"<kind>:<param>"`` string such as ``"downsample:0.5"`` or ``"encode:jpeg"``. This enum lists the kinds; the form
    of the parameter depends on the kind. Build these strings with ``with_param`` and split them with ``parse``.
    """

    DOWNSAMPLE = "downsample"
    """Spatial or temporal downsampling. The parameter is a scale factor in ``(0, 1]``."""
    ENCODE = "encode"
    """Re-encoding into another content format. The parameter is the target format, such as ``"jpeg"``."""

    def with_param(self, param: object) -> str:
        """Build the ``"<kind>:<param>"`` transformation string for this kind and ``param``.

        Args:
            param: Parameter of the transformation, converted to a string.

        Examples:
            >>> TransformationKind.DOWNSAMPLE.with_param(0.5)
            'downsample:0.5'
        """
        return f"{self.value}:{param}"

    @classmethod
    def parse(cls, descriptor: str) -> tuple[TransformationKind, str]:
        """Split a ``"<kind>:<param>"`` transformation string into its kind and its parameter.

        Args:
            descriptor: Transformation string, such as ``"encode:jpeg"``.

        Returns:
            ``(kind, param)``: the kind and the parameter as a string. The parameter is empty when ``descriptor``
            contains no ``:``.

        Raises:
            ValueError: The text before the first ``:`` is not a ``TransformationKind`` value.

        Examples:
            >>> TransformationKind.parse("encode:jpeg")
            (<TransformationKind.ENCODE: 'encode'>, 'jpeg')
        """
        kind, _, param = descriptor.partition(":")
        return cls(kind), param


class RepresentationRecord(pydantic.BaseModel):
    """Data record of a representation, as the Roboto API returns it.

    A representation is one stored copy of a topic's data, in one file format and possibly transformed, such as
    downsampled or encoded as JPEG. Most of a topic's message paths share one representation, usually the MCAP or
    Parquet file that holds all of the topic's data; some message paths have further representations, such as a
    preview format.
    """

    association: Association
    """Resource that holds the representation's data, usually a file."""

    created: datetime.datetime
    """Time the representation was created."""

    format: typing.Optional[str] = None
    """Content format of the representation's data, or ``None`` when none was recorded, as for most non-image topics.

    For an image topic, this is the image encoding of an encoded representation, such as ``"jpeg"`` or ``"png"``, or
    the message schema name of the original data, such as ``"sensor_msgs/Image"``.
    """

    modified: datetime.datetime
    """Time the representation was last modified."""

    representation_id: str
    """Unique ID of the representation."""

    storage_format: RepresentationStorageFormat
    """File format the representation's data is stored in."""

    topic_id: str
    """ID of the topic this representation belongs to."""

    transformations: list[str] = pydantic.Field(default_factory=list)
    """Transformations applied, in order, to produce this representation, or an empty list for the original data.

    Each entry is a ``"<kind>:<param>"`` string whose kind is a ``TransformationKind`` value, such as
    ``["downsample:0.5", "encode:jpeg"]``.
    """

    version: int
    """Version number of the representation, as set when it was added."""


class CanonicalDataType(enum.Enum):
    """Framework-independent data type of a message path, which Roboto uses to choose how to display its data.

    Each native field type, such as a field type of ROS 1 (http://wiki.ros.org/msg), ROS 2
    (https://docs.ros.org/en/iron/Concepts/Basic/About-Interfaces.html#field-types) or uORB
    (https://docs.px4.io/main/en/middleware/uorb.html#adding-a-new-topic), maps onto one of these. For example:

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
    """Sequence of values."""
    Boolean = "boolean"
    """True or false value."""
    Byte = "byte"
    """Single byte."""
    Categorical = "categorical"
    """Value from a fixed, ordered set of values, such as ``"off"`` or ``"on"``.

    The message path's metadata must have a ``"categories"`` key (``MessagePathMetadataWellKnown.Categories``)
    listing the values in order, such as ``["off", "on"]``. Roboto maps each value to its index in that list,
    ``"off"`` to 0 and ``"on"`` to 1, so it can plot changes from one value to another. Outside a plot, Roboto
    displays categorical data as it displays ``String`` data.
    """
    Image = "image"
    """Data that Roboto can display as an image."""
    Number = "number"
    """Numeric scalar, such as an integer or a float."""
    NumberArray = "number_array"
    """Flat sequence of numeric scalars, of fixed or variable length.

    Elements are ints, floats, or decimals: never booleans, strings, nested sequences, or structs, so a
    ``NumberArray`` message path never has child message paths. A fixed length appears as the trailing ``[<N>]``
    of ``data_type`` (``float64[7]``, ``fixed_size_list<element: double>[3]``) and is read by
    :py:attr:`~roboto.domain.topics.MessagePath.array_length`; ``float64[]`` and ``list<element: double>``
    declare none.

    Code that creates message paths (ingestion actions, :py:meth:`~roboto.domain.topics.Topic.create_from_df`)
    must not assign this type to arrays of byte-width element types (``uint8``, ``int8``, ``byte``, ``char``),
    because those typically hold raw bytes (images, serialized blobs), not signals to plot. ULog ingestion is the
    exception: it types ``int8_t[N]`` and ``uint8_t[N]`` as ``NumberArray``. Code that must exclude byte payloads
    therefore checks ``data_type`` for a byte-width element type rather than relying on this type alone.
    """
    Object = "object"
    """Struct with attributes."""
    String = "string"
    """Text."""
    Timestamp = "timestamp"
    """Instant in time, as the time elapsed since the Unix epoch.

    The unit is the message path's ``"unit"`` metadata value, which must be a :py:class:`~roboto.time.TimeUnit`
    value: ``"s"``, ``"ms"``, ``"us"`` or ``"ns"``. Without that key, Roboto reads the value as nanoseconds.
    """
    Unknown = "unknown"
    """Data that fits no other type. Assign it only when no other type applies."""
    LatDegFloat = "latdegfloat"
    """Latitude in degrees, as a float, such as ``47.6749387``.

    ULog files with ``ver_data_format`` 2 or later use it.
    """
    LonDegFloat = "londegfloat"
    """Longitude in degrees, as a float, such as ``9.1445274``.

    ULog files with ``ver_data_format`` 2 or later use it.
    """
    LatDegInt = "latdegint"
    """Latitude in degrees times 10^7, as an integer, such as ``317534036`` for 31.7534036 degrees.

    ULog files with ``ver_data_format`` below 2 use it.
    """
    LonDegInt = "londegint"
    """Longitude in degrees times 10^7, as an integer, such as ``1199146398`` for 119.9146398 degrees.

    ULog files with ``ver_data_format`` below 2 use it.
    """


_FIXED_ARRAY_DATA_TYPE = re.compile(r"([^\[]+)\[(\d+)\]")
_ARROW_FIXED_SIZE_LIST_ELEMENT = re.compile(r"fixed_size_list<[^:<>]+:\s*(.+)>")
_BYTE_WIDTH_ELEMENT_TYPES = frozenset({"byte", "char", "int8", "int8_t", "octet", "uint8", "uint8_t"})


@dataclasses.dataclass(frozen=True)
class FixedArrayDataType:
    """Element type and length that a flat, fixed-length array declares in its ``data_type``.

    Build one with ``parse``.
    """

    element_type: str
    """Type of each element, as the recording format spells it.

    ``float32`` for ``float32[6]``, and ``float`` for the Arrow ``fixed_size_list<element: float not null>[6]``.
    """

    length: int
    """Number of elements, from the trailing ``[<N>]``."""

    @classmethod
    def parse(cls, data_type: str) -> typing.Optional[FixedArrayDataType]:
        """Build the element type and length from a ``data_type`` that ends in a single ``[<N>]``.

        ``float64[7]``, ``Point[3]`` and ``fixed_size_list<element: double>[3]`` parse.

        Args:
            data_type: Native data type of a field or message path.

        Returns:
            The element type and length, or ``None`` for a variable-length array (``float64[]``,
            ``list<element: double>``), a ROS 2 bounded one (``float64[<=10]``), a multi-dimensional one
            (``float64[2][3]``, ``fixed_size_list<element: list<element: double>>[3]``) or a scalar.
        """
        # Each Arrow "list<" opener (in list<, large_list< and fixed_size_list<) is one dimension.
        # fixed_size_list<element: list<element: double>>[3] ends in the outer list's [3] alone, which the pattern
        # below would read as a flat length.
        if data_type.count("list<") > 1:
            return None
        match = _FIXED_ARRAY_DATA_TYPE.fullmatch(data_type)
        if match is None:
            return None
        element_type, length = match.groups()
        arrow_element = _ARROW_FIXED_SIZE_LIST_ELEMENT.fullmatch(element_type)
        if arrow_element is not None:
            element_type = arrow_element.group(1).removesuffix(" not null")
        return cls(element_type=element_type.strip(), length=int(length))

    @property
    def has_byte_width_elements(self) -> bool:
        """Whether each element is one byte wide.

        The one-byte element types are ``uint8``, ``int8``, ``uint8_t``, ``int8_t``, ``byte``, ``char`` and
        ``octet``, in any letter case. Arrays of them typically hold raw bytes, not signals; see
        ``CanonicalDataType.NumberArray``.
        """
        return self.element_type.lower() in _BYTE_WIDTH_ELEMENT_TYPES


class MessagePathStatistic(enum.Enum):
    """Statistic that Roboto's ingestion actions compute for a message path, keyed by this value in its metadata.

    Which statistics a message path has depends on the action that ingested it, so treat each one as optional. Read
    it with ``metadata.get(...)`` or the matching :py:class:`~roboto.domain.topics.MessagePath` property, which both
    return ``None`` for a statistic that was never computed; a missing statistic does not mean zero. Indexing
    ``MessagePathRecord.metadata`` directly raises ``KeyError`` for a missing one.
    """

    Count = "count"
    Max = "max"
    Mean = "mean"
    Median = "median"
    Min = "min"
    P25 = "p25"
    P75 = "p75"
    P95 = "p95"
    P99 = "p99"
    Stddev = "stddev"


class MessagePathMetadataWellKnown(StrEnum):
    """Metadata key that Roboto gives a meaning to in ``MessagePathRecord.metadata``.

    Roboto's ingestion actions usually set these keys, and Roboto's clients read them.
    """

    ColumnName = "column_name"
    """Deprecated. Field's name or path in the source data's schema.

    Use ``MessagePathRecord.source_path`` instead. The name or path can differ from ``MessagePathRecord.message_path``
    when characters were replaced to meet message path naming rules. ``MessagePathRecord.path_in_schema`` holds the
    same path as a list of components, and :py:class:`~roboto.domain.topics.AddMessagePathRequest` sets it.
    """

    Categories = "categories"
    """Ordered list of the values a ``CanonicalDataType.Categorical`` message path takes.

    For example, ``["off", "on"]`` or ``["left", "up", "right", "down"]``.
    """

    Unit = "unit"
    """Unit of the message path's values, such as ``"ns"`` for a timestamp.

    When set, it must be a :py:class:`~roboto.time.TimeUnit` value.
    """


class MessagePathRecord(pydantic.BaseModel):
    """Data record of a message path, as the Roboto API returns it.

    A message path is one field or signal of a topic's messages, such as ``"pose.position.x"``.
    :py:class:`~roboto.domain.topics.MessagePath` wraps this record with methods that act on the message path, and
    exposes it as :py:attr:`~roboto.domain.topics.MessagePath.record`.
    """

    canonical_data_type: CanonicalDataType
    """Framework-independent data type of the field, which Roboto uses to choose how to display its data."""

    created: datetime.datetime
    """Time the message path was created."""

    created_by: str
    """ID of the user who created the message path."""

    data_type: str
    """Native data type of the field, as the source data's framework names it.

    For example, ``"float32"``, ``"uint8[]"``, ``"geometry_msgs/Pose"`` or ``"string"``.
    """

    message_path: str
    """Dot-delimited path to the field within the topic's messages, such as ``"pose.position.x"``."""

    message_path_id: str
    """Unique ID of the message path, beginning with ``mp_``."""

    metadata: collections.abc.Mapping[str, typing.Any] = pydantic.Field(
        default_factory=dict,
    )
    """Key-value metadata on the message path, such as ``{"min": 0.71, "max": 1.77}``.

    ``MessagePathStatistic`` and ``MessagePathMetadataWellKnown`` list the keys Roboto gives a meaning to.
    """

    modified: datetime.datetime
    """Time the message path was last modified."""

    modified_by: str
    """ID of the user who last modified the message path."""

    org_id: str
    """ID of the organization that owns the message path, which is the organization that owns its topic."""

    path_in_schema: list[str]
    """Components of the field's path in the source data's schema, in order from the schema root.

    Each component keeps the source's own name. ``message_path`` instead follows Roboto's naming rules and treats
    every dot as a separator between nested fields, so this is the path to use to find the field in the source data.
    """

    representations: collections.abc.MutableSequence[RepresentationRecord] = pydantic.Field(default_factory=list)
    """Representations that hold this message path's data, if any."""

    source_path: str
    """Name of the field in the source data's schema: ``path_in_schema`` joined with dots.

    It can differ from ``message_path`` when characters were replaced to meet message path naming rules. Prefer it
    when you pass ``message_paths_include`` or ``message_paths_exclude`` to the ``get_data`` and ``get_data_as_df``
    methods of :py:class:`~roboto.domain.topics.Topic` and :py:class:`~roboto.domain.events.Event`.
    """

    topic_id: str
    """ID of the topic this message path belongs to."""

    def parents(self, delimiter: str = ".") -> list[str]:
        """Return the paths of this field's ancestors in the source data's schema, nearest first.

        Each ancestor's path is leading components of ``path_in_schema``, joined with ``delimiter``.

        Args:
            delimiter: String to join path components with.

        Examples:
            For a record whose ``path_in_schema`` is ``["root", "sub_obj_1", "sub_obj_2", "leaf_field"]``:

            >>> record.parents()
            ['root.sub_obj_1.sub_obj_2', 'root.sub_obj_1', 'root']
        """
        parent_path_parts = self.path_in_schema[:-1]
        return [delimiter.join(parent_path_parts[:i]) for i in range(len(parent_path_parts), 0, -1)]

    def to_field_selection(self) -> FieldSelection:
        """Return this field as the :py:class:`~roboto.formats.FieldSelection` that format readers take."""
        return FieldSelection(path_in_schema=tuple(self.path_in_schema))


class MessagePathRepresentationMapping(pydantic.BaseModel):
    """Item of the response body of ``GET /v1/topics/id/{topic_id}/message-path/representations``.

    It pairs message paths with a representation that holds their data.
    :py:meth:`~roboto.domain.topics.Topic.get_data` and :py:meth:`~roboto.domain.topics.Topic.get_data_as_df` read the
    list to choose where each message path's data comes from.
    """

    message_paths: collections.abc.MutableSequence[MessagePathRecord]
    """Message paths whose data the representation holds."""

    representation: RepresentationRecord
    """Record of the representation that holds the message paths' data."""


class TopicRecord(pydantic.BaseModel):
    """Data record of a topic, as the Roboto API returns it.

    A topic is a sequence of structured time-series data, called messages, linked to a source file; each message
    follows the topic's schema. Data under one topic name in one file forms one topic. Data in different files, or
    under different names, forms separate topics even when the schemas match, so a recording split into several
    files by time or size yields one topic record per file for the same topic name.
    :py:class:`~roboto.domain.topics.Topic` wraps this record with methods that act on the topic, and exposes it as
    :py:attr:`~roboto.domain.topics.Topic.record`.
    """

    association: Association
    """Resource the topic belongs to, usually the file its data came from."""

    created: datetime.datetime
    """Time the topic was created."""

    created_by: str
    """ID of the user who created the topic."""

    default_representation: typing.Optional[RepresentationRecord] = None
    """Record of the representation that holds the data of each message path without one of its own.

    ``None`` if there is none.
    """

    end_time: typing.Optional[int] = None
    """Timestamp of the topic's latest message, in nanoseconds since the Unix epoch, or ``None`` if unknown."""

    message_count: typing.Optional[int] = None
    """Number of messages in the topic, or ``None`` if unknown."""

    message_paths: collections.abc.MutableSequence[MessagePathRecord] = pydantic.Field(default_factory=list)
    """Message paths of the topic.

    When ``message_paths_next_token`` is not ``None``, this holds only the first part of the list.
    """

    message_paths_next_token: typing.Optional[str] = None
    """Token for the message paths that ``message_paths`` leaves out, or ``None`` when it holds every one.

    A record leaves message paths out when they would not fit in one response with the rest of the record. Pass the
    token as ``page_token`` to ``GET /v1/topics/id/{topic_id}/message-paths`` for the first page of the rest, and each
    page's ``next_token`` for the page after it, until ``next_token`` is ``None``.
    :py:class:`~roboto.domain.topics.Topic` fetches every page when it is built from the record, so its
    :py:attr:`~roboto.domain.topics.Topic.record` holds every message path.
    """

    metadata: collections.abc.Mapping[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the topic."""

    modified: datetime.datetime
    """Time the topic was last modified."""

    modified_by: str
    """ID of the user who last modified the topic."""

    org_id: str
    """ID of the organization that owns the topic."""

    schema_checksum: typing.Optional[str] = None
    """Checksum of the topic's schema, or ``None`` if the topic has no known schema."""

    schema_id: typing.Optional[str] = None
    """ID of the topic's schema, or ``None`` if the topic has no schema or Roboto has not yet recorded it."""

    schema_name: typing.Optional[str] = None
    """Name of the topic's message type, such as ``"sensor_msgs/PointCloud2"``, or ``None`` if it is unknown."""

    start_time: typing.Optional[int] = None
    """Timestamp of the topic's earliest message, in nanoseconds since the Unix epoch, or ``None`` if unknown."""

    topic_id: str
    """Unique ID of the topic, beginning with ``tp_``."""

    topic_name: str
    """Name of the topic, such as ``"/imu/data"``."""


class TopicTimeBounds(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.datasets.Dataset.get_topic_time_bounds`.

    :py:meth:`~roboto.domain.topics.Topic.get_time_bounds_by_association` also returns it. It holds the earliest start
    time and latest end time across a set of topics, such as the topics of a dataset. Roboto computes the bounds, so a
    caller does not have to page through every topic to find them.
    """

    start_time: typing.Optional[int] = None
    """Earliest ``start_time`` of a topic in the set, in nanoseconds since the Unix epoch.

    ``None`` when no topic in the set has a ``start_time``, which includes an empty set.
    """

    end_time: typing.Optional[int] = None
    """Latest ``end_time`` of a topic in the set, in nanoseconds since the Unix epoch.

    ``None`` when no topic in the set has an ``end_time``, which includes an empty set.
    """


FieldPath = tuple[str, ...]
"""Path components of a schema field, in order from the schema root to the leaf."""


def validate_data_range(data_range: tuple[int, int]) -> tuple[int, int]:
    """Reject a ``data_range`` that is not a pair of non-negative positions with ``start < end``.

    Pydantic calls this while it builds a model with a ``DataRange`` field, such as a topic partition record. Both
    positions must also fit in a signed 64-bit integer, which is how Roboto stores them.

    Args:
        data_range: The ``(start, end)`` pair to check, with ``start`` included and ``end`` excluded.

    Returns:
        ``data_range``, unchanged.

    Raises:
        ValueError: ``start`` is negative, ``end`` is not greater than ``start``, or a position is too
            large for a signed 64-bit integer.
    """
    start, end = data_range
    if start < 0 or end <= start:
        raise ValueError(
            "data_range must be a pair of non-negative positions with start < end "
            f"(start is included, end is excluded), got {data_range!r}"
        )
    if end > INT64_MAX:
        raise ValueError(
            "data_range positions must fit in a signed 64-bit integer, which is how the platform "
            f"stores them, got {data_range!r}"
        )
    return data_range


DataRange = typing.Annotated[tuple[int, int], pydantic.AfterValidator(validate_data_range)]
"""A slice of one file's contents, as ``(start, end)`` with ``start`` included and ``end`` excluded.

A position is expressed in whatever the file's format uses to address its contents: stored-row
positions counted from 0, or nanoseconds of media time for video. The pair alone does
not say which of the two applies, so a reader takes that from the file's format. The half-open form
matches LeRobot's ``dataset_from_index`` and ``dataset_to_index``, so row ranges read from LeRobot
episode metadata carry over unchanged.
"""


@experimental
class SchemaFieldRecord(pydantic.BaseModel):
    """Field of a topic schema.

    A schema has one record per field path, and topics that share the schema share its field records.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    canonical_data_type: CanonicalDataType
    """Framework-independent data type of the field, which Roboto uses to choose how to display its data."""

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    data_type: str
    """Native data type of the field, as the source data's framework names it, such as ``"float32"``."""

    field_id: str
    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: str
    """Display name of the field, usually the last component of ``path_in_schema``."""

    org_id: str
    path_in_schema: FieldPath
    """Components of the field's path in the source data's schema, from the schema root to the leaf.

    Each component is the source's own name for that level of the schema.
    """

    schema_id: str
    unit: typing.Optional[str] = None
    """Unit of the field's values, such as ``"ns"`` or ``"m/s"``, or ``None`` if it has none or it is unknown."""

    element_names: typing.Optional[tuple[str, ...]] = None
    """Name of each element of a fixed-length numeric array field, in element order, or ``None`` if not named.

    They are declared with ``roboto.experimental.ingest.Field.element_names``.
    """


@experimental
class TopicSchemaRecord(pydantic.BaseModel):
    """Topic schema, identified by its fields.

    Within an organization, schemas with identical fields share one record, which a checksum of the fields
    identifies. ``name`` is not part of that identity: creating or ingesting a topic, or adding message paths to one,
    with a schema name and fields identical to this schema's replaces it with that schema name.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    checksum: str
    """Checksum computed from the schema's fields; schemas with identical fields have the same checksum."""

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: typing.Optional[str] = None
    """Informational name of the schema, such as ``"sensor_msgs/PointCloud2"``; not part of its identity."""

    org_id: str
    schema_id: str
    """Unique ID of the schema."""


@experimental
class TopicIdentityRecord(pydantic.BaseModel):
    """Identity of a topic across files.

    Within an organization, data logged under the same topic name in different files shares one identity record.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: str
    """Name of the topic, such as ``"/camera/image_raw"``, unique within an organization."""

    org_id: str
    topic_id: str
    """Unique ID of the topic identity."""


TimelineSourceKind: typing.TypeAlias = typing.Literal["schema_field", "message_log_time", "message_publish_time"]
"""Where a ``TimelineSourceRecord`` takes its timestamps from.

- ``"schema_field"``: a timestamp field of the schema, named by the record's ``field_id``.
- ``"message_log_time"``: the time each message was logged, from the message envelope.
- ``"message_publish_time"``: the time each message was published, from the message envelope.
"""


@experimental
class TimelineSourceRecord(pydantic.BaseModel):
    """Source of timestamps registered for a schema.

    A timeline source takes timestamps from a timestamp field of the schema or from each message's log or publish
    time, as ``source`` says. Timeline sources belong to a schema, not a topic, so topics that share a schema share
    its timeline sources.

    Building one raises ``pydantic.ValidationError`` when ``source`` is not a ``TimelineSourceKind`` value, when
    ``source`` is ``"schema_field"`` and ``field_id`` is ``None``, or when ``field_id`` is set and ``source`` is
    anything else.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    field_id: typing.Optional[str] = None
    """ID of the schema field the timestamps come from when ``source`` is ``"schema_field"``; otherwise ``None``."""

    is_default: bool = False
    """Whether this is its schema's default timeline source, used when no timeline source is named."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    name: str
    """Human-readable name of the timeline source."""

    org_id: str
    schema_id: str
    """ID of the schema this timeline source belongs to."""

    source: TimelineSourceKind
    """Where the timestamps come from: a schema field, or each message's log or publish time."""

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
    """Smallest and largest timestamps of one topic partition, as one timeline source measures them.

    Ingestion records them when it summarizes a partition's timestamps for a timeline source, such as a timestamp
    field of the schema or the messages' log time.

    Timestamps are stored as the source data has them, so they can be nanoseconds since the Unix epoch or relative
    to the partition, such as a clock that starts at zero. ``unix_epoch_offset_ns`` converts a stored timestamp to
    nanoseconds since the Unix epoch: ``unix_time_ns = stored_time_ns + unix_epoch_offset_ns``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    max_timestamp: typing.Optional[int] = None
    """Largest stored timestamp of the partition, in nanoseconds."""

    min_timestamp: typing.Optional[int] = None
    """Smallest stored timestamp of the partition, in nanoseconds."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    org_id: str
    timeline_extent_id: str
    timeline_source_id: str
    """ID of the timeline source that measures these timestamps."""

    topic_part_id: str
    """ID of the topic partition these timestamps belong to."""

    unix_epoch_offset_ns: int = 0
    """Nanoseconds to add to each stored timestamp to get nanoseconds since the Unix epoch.

    ``0`` when the stored timestamps already count from the Unix epoch, or when no offset has been recorded for this
    partition and timeline source.
    """


@experimental
class TopicPartitionRecord(pydantic.BaseModel):
    """One file's data for a topic.

    Pairs a topic identity with a file and carries the facts that vary from file to file: the schema
    the file's messages follow (``schema_id``), the device that produced them, and the ``data_range``
    locating them inside the file, for formats that pack several slices of data into one shared file.
    A partition references a file, not a specific version; reads always resolve to the current version.

    Building one raises ``pydantic.ValidationError`` for a ``data_range`` that ``validate_data_range`` rejects.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    data_range: typing.Optional[DataRange] = None
    """Slice of the file that this partition's data occupies, as ``(start, end)``, or ``None`` for the whole file.

    ``start`` alone identifies the partition within its (topic, file) pair, since a slice's starting
    position is stable across re-ingest: re-declaring a slice that begins at the same position updates
    the existing partition instead of adding a second, overlapping one.
    """

    device_id: typing.Optional[str] = None
    """ID of the device that produced this partition's data, or ``None`` if unknown."""

    fs_node_id: str
    """ID of the file this partition's data is in."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    org_id: str
    schema_id: str
    """ID of the schema this partition's messages follow."""

    topic_id: str
    """ID of the topic identity this partition belongs to."""

    topic_part_id: str
