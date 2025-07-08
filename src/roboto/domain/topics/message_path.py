# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
from datetime import datetime
import pathlib
import typing

from ...association import Association
from ...http import RobotoClient
from ...time import Time
from .record import (
    CanonicalDataType,
    MessagePathRecord,
    MessagePathStatistic,
)
from .topic_data_service import TopicDataService

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

PreComputedStat: typing.TypeAlias = typing.Optional[typing.Union[int, float]]


class MessagePath:
    """Represents a message path within a topic in the Roboto platform.

    A message path defines a specific field or signal within a topic's data schema,
    using dot notation to specify nested attributes. Message paths enable fine-grained
    access to individual data elements within time-series robotics data, supporting
    operations like statistical analysis, data filtering, and visualization.

    Each message path has an associated data type (both native and canonical), metadata,
    and statistical information computed from the underlying data. Message paths are
    the fundamental building blocks for data analysis in Roboto, allowing users to
    work with specific signals or measurements from complex robotics data structures.

    Message paths support temporal filtering, data export to various formats including
    pandas DataFrames, and integration with the broader Roboto analytics ecosystem.
    They provide efficient access to time-series data while maintaining the semantic
    structure of the original robotics messages.

    The MessagePath class serves as the primary interface for accessing individual
    data signals within topics, providing methods for data retrieval, statistical
    analysis, and metadata management.
    """

    DELIMITER: typing.ClassVar = "."

    __record: MessagePathRecord
    __roboto_client: RobotoClient
    __topic_data_service: TopicDataService

    @staticmethod
    def parents(path: str) -> list[str]:
        """Get parent paths for a message path in dot notation.

        Given a message path in dot notation, returns a list of its parent paths
        ordered from most specific to least specific.

        Args:
            path: Message path in dot notation (e.g., "pose.pose.position.x").

        Returns:
            List of parent paths in dot notation, ordered from most to least specific.

        Examples:
            >>> path = "pose.pose.position.x"
            >>> MessagePath.parents(path)
            ['pose.pose.position', 'pose.pose', 'pose']

            >>> # Single level path has no parents
            >>> MessagePath.parents("velocity")
            []
        """
        parent_parts = MessagePath.parts(path)[:-1]
        return [
            MessagePath.DELIMITER.join(parent_parts[:i])
            for i in range(len(parent_parts), 0, -1)
        ]

    @staticmethod
    def parts(path: str) -> list[str]:
        """Split message path in dot notation into its constituent parts.

        Splits a message path string into individual components, useful for
        programmatic manipulation of message path hierarchies.

        Args:
            path: Message path in dot notation (e.g., "pose.pose.position.x").

        Returns:
            List of path components in order from root to leaf.

        Examples:
            >>> path = "pose.pose.position.x"
            >>> MessagePath.parts(path)
            ['pose', 'pose', 'position', 'x']

            >>> # Single component path
            >>> MessagePath.parts("velocity")
            ['velocity']
        """
        return path.split(MessagePath.DELIMITER)

    @classmethod
    def from_id(
        cls,
        message_path_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ) -> "MessagePath":
        """Retrieve a message path by its unique identifier.

        Fetches a message path record from the Roboto platform using its unique ID.
        This is useful when you have a message path identifier from another operation.

        Args:
            message_path_id: Unique identifier for the message path.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            topic_data_service: Service for accessing topic data. If None, creates a default instance.

        Returns:
            MessagePath instance representing the requested message path.

        Raises:
            RobotoNotFoundException: Message path with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the message path.

        Examples:
            >>> message_path = MessagePath.from_id("mp_abc123")
            >>> print(message_path.path)
            'angular_velocity.x'
            >>> print(message_path.canonical_data_type)
            CanonicalDataType.Number
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/topics/message-path/id/{message_path_id}"
        ).to_record(MessagePathRecord)
        return cls(record, roboto_client, topic_data_service)

    def __init__(
        self,
        record: MessagePathRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__topic_data_service = topic_data_service or TopicDataService(
            self.__roboto_client
        )

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, MessagePath):
            return NotImplemented

        return self.__record == other.__record

    @property
    def canonical_data_type(self) -> CanonicalDataType:
        """Canonical Roboto data type corresponding to the native data type."""

        return self.__record.canonical_data_type

    @property
    def count(self) -> PreComputedStat:
        """Number of data points available for this message path."""
        return self.__get_statistic(MessagePathStatistic.Count)

    @property
    def created(self) -> datetime:
        """Timestamp when this message path was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Identifier of the user or system that created this message path."""
        return self.__record.created_by

    @property
    def data_type(self) -> str:
        """Native data type for this message path, e.g. 'float32'"""

        return self.__record.data_type

    @property
    def max(self) -> PreComputedStat:
        """Maximum value observed for this message path."""
        return self.__get_statistic(MessagePathStatistic.Max)

    @property
    def mean(self) -> PreComputedStat:
        """Mean (average) value for this message path."""
        return self.__get_statistic(MessagePathStatistic.Mean)

    @property
    def median(self) -> PreComputedStat:
        """Median value for this message path."""
        return self.__get_statistic(MessagePathStatistic.Median)

    @property
    def message_path_id(self) -> str:
        """Unique identifier for this message path."""
        return self.__record.message_path_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Metadata dictionary associated with this message path."""
        return dict(self.__record.metadata)

    @property
    def min(self) -> PreComputedStat:
        """Minimum value observed for this message path."""
        return self.__get_statistic(MessagePathStatistic.Min)

    @property
    def modified(self) -> datetime:
        """Timestamp when this message path was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Identifier of the user or system that last modified this message path."""
        return self.__record.modified_by

    @property
    def org_id(self) -> str:
        """Organization ID that owns this message path."""
        return self.__record.org_id

    @property
    def path(self) -> str:
        """Dot-delimited path to the attribute (e.g., 'pose.position.x')."""
        return self.__record.message_path

    @property
    def record(self) -> MessagePathRecord:
        """Underlying MessagePathRecord for this message path."""
        return self.__record

    @property
    def topic_id(self) -> str:
        """Unique identifier of the topic containing this message path."""
        return self.__record.topic_id

    def get_data(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Return data for this specific message path.

        Retrieves and yields data records containing only the values for this message path,
        with optional temporal filtering. This provides a focused view of a single signal
        or field within the broader topic data.

        Args:
            start_time: Start time (inclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            end_time: End time (exclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            cache_dir: Directory where topic data will be downloaded if necessary.
                Defaults to :py:attr:`~roboto.domain.topics.topic_data_service.TopicDataService.DEFAULT_CACHE_DIR`.

        Yields:
            Dictionary records containing the log_time and the value for this message path.

        Notes:
            For each example below, assume the following is a sample datum record
            that can be found in this message path's associated topic:

            ::

                {
                    "angular_velocity": {
                        "x": <uint32>,
                        "y": <uint32>,
                        "z": <uint32>
                    },
                    "orientation": {
                        "x": <uint32>,
                        "y": <uint32>,
                        "z": <uint32>,
                        "w": <uint32>
                    }
                }

        Examples:
            Print all data for a specific message path:

            >>> topic = Topic.from_name_and_file("/imu/data", "file_abc123")
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> for record in angular_velocity_x.get_data():
            ...     print(f"Time: {record['log_time']}, Value: {record['angular_velocity']['x']}")

            Get data within a time range:

            >>> for record in angular_velocity_x.get_data(
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923
            ... ):
            ...     print(record)

            Collect data into a dataframe (requires installing the ``roboto[analytics]`` extra):

            >>> df = angular_velocity_x.get_data_as_df()
            >>> import math
            >>> assert math.isclose(angular_velocity_x.mean, df[angular_velocity_x.path].mean())
        """

        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=[self.__record.message_path],
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def get_data_as_df(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> pandas.DataFrame:
        """Return this message path's data as a pandas DataFrame.

        Retrieves message path data and converts it to a pandas DataFrame for analysis
        and visualization. The DataFrame is indexed by log time and contains a column
        for this message path's values.

        Args:
            start_time: Start time (inclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            end_time: End time (exclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            cache_dir: Directory where topic data will be downloaded if necessary.
                Defaults to :py:attr:`~roboto.domain.topics.topic_data_service.TopicDataService.DEFAULT_CACHE_DIR`.

        Returns:
            pandas DataFrame containing the message path data, indexed by log time.

        Raises:
            ImportError: pandas is not installed. Install with ``roboto[analytics]`` extra.

        Notes:
            Requires installing this package using the ``roboto[analytics]`` extra.

        Examples:
            >>> topic = Topic.from_name_and_file("/imu/data", "file_abc123")
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> df = angular_velocity_x.get_data_as_df()
            >>> print(df.head())
                                    angular_velocity.x
            log_time
            1722870127699468923                  0.1
            1722870127699468924                  0.15
            >>> print(f"Mean: {df[angular_velocity_x.path].mean()}")
            Mean: 0.125
        """
        return self.__topic_data_service.get_data_as_df(
            topic_id=self.__record.topic_id,
            message_paths_include=[self.__record.message_path],
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def to_association(self) -> Association:
        """Convert this message path to an Association object.

        Creates an Association object that can be used to reference this message path
        in other parts of the Roboto platform.

        Returns:
            Association object representing this message path.

        Examples:
            >>> message_path = MessagePath.from_id("mp_abc123")
            >>> association = message_path.to_association()
            >>> print(association.association_type)
            AssociationType.MessagePath
            >>> print(association.association_id)
            mp_abc123
        """
        return Association.msgpath(self.message_path_id)

    def __get_statistic(self, stat: MessagePathStatistic) -> PreComputedStat:
        return self.__record.metadata.get(stat.value)
