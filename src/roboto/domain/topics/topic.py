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
import urllib.parse

from ...association import Association
from ...http import RobotoClient
from ...logging import default_logger
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from ...time import Time
from ...updates import (
    MetadataChangeset,
    TaglessMetadataChangeset,
)
from .message_path import MessagePath
from .operations import (
    AddMessagePathRepresentationRequest,
    AddMessagePathRequest,
    CreateTopicRequest,
    MessagePathChangeset,
    SetDefaultRepresentationRequest,
    UpdateMessagePathRequest,
    UpdateTopicRequest,
)
from .record import (
    CanonicalDataType,
    MessagePathRecord,
    RepresentationRecord,
    RepresentationStorageFormat,
    TopicRecord,
)
from .topic_data_service import TopicDataService

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


class Topic:
    """Represents a topic within the Roboto platform.

    A topic is a sequence of structured time-series data linked to a source file, typically
    containing sensor readings, robot state information, or other timestamped data streams.
    Topics are fundamental building blocks for data analysis in robotics, providing organized
    access to time-synchronized data from various sources like ROS bags, MCAP files, or other
    structured data formats.

    Each topic follows a defined schema where message paths represent the individual fields
    or signals within that schema. Topics enable efficient querying, filtering, and analysis
    of time-series data, supporting operations like temporal slicing, field selection, and
    data export to various formats including pandas DataFrames.

    Topics are associated with files and inherit access permissions from their parent dataset.
    They provide the primary interface for accessing ingested robotics data in the Roboto
    platform, supporting both programmatic access through the SDK and visualization in the
    web interface.

    The Topic class serves as the main interface for topic operations in the Roboto SDK,
    providing methods for data retrieval, message path management, metadata operations,
    and schema management.
    """

    __record: TopicRecord
    __roboto_client: RobotoClient
    __topic_data_service: TopicDataService

    @classmethod
    def create(
        cls,
        file_id: str,
        topic_name: str,
        end_time: typing.Optional[int] = None,
        message_count: typing.Optional[int] = None,
        metadata: typing.Optional[collections.abc.Mapping[str, typing.Any]] = None,
        schema_checksum: typing.Optional[str] = None,
        schema_name: typing.Optional[str] = None,
        start_time: typing.Optional[int] = None,
        message_paths: typing.Optional[
            collections.abc.Sequence[AddMessagePathRequest]
        ] = (None),
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        """Create a new topic associated with a file.

        Creates a new topic record in the Roboto platform, associating it with the specified
        file and defining its schema and temporal boundaries. This method is typically used
        during data ingestion to register topics found in robotics data files.

        Note:
            On successful creation, the topic will be a metadata-only container and will not
            be visualizable or usable via data access methods like :py:meth:`get_data_as_df`
            until one or more representations have been registered. This is typically handled
            automatically by ingestion actions, but power users may need to manage
            representations manually.

        Args:
            file_id: Unique identifier of the file this topic is associated with.
            topic_name: Name of the topic (e.g., "/camera/image", "/imu/data").
            end_time: End time of the topic data in nanoseconds since UNIX epoch.
            message_count: Total number of messages in this topic.
            metadata: Additional metadata to associate with the topic.
            schema_checksum: Checksum of the topic's message schema for validation.
            schema_name: Name of the message schema (e.g., "sensor_msgs/Image").
            start_time: Start time of the topic data in nanoseconds since UNIX epoch.
            message_paths: Message paths to create along with the topic.
            caller_org_id: Organization ID to create the topic in. Required for multi-org users.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Topic instance representing the newly created topic.

        Raises:
            RobotoInvalidRequestException: Invalid topic parameters.
            RobotoUnauthorizedException: Caller lacks permission to create topics.

        Examples:
            Create a basic topic for camera data:

            >>> topic = Topic.create(
            ...     file_id="file_abc123",
            ...     topic_name="/camera/image",
            ...     schema_name="sensor_msgs/Image",
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ...     message_count=100
            ... )
            >>> print(topic.topic_id)
            topic_xyz789

            Create a topic with metadata and message paths:

            >>> from roboto.domain.topics import AddMessagePathRequest, CanonicalDataType
            >>> message_paths = [
            ...     AddMessagePathRequest(
            ...         message_path="header.stamp.sec",
            ...         data_type="uint32",
            ...         canonical_data_type=CanonicalDataType.Timestamp
            ...     )
            ... ]
            >>> topic = Topic.create(
            ...     file_id="file_abc123",
            ...     topic_name="/imu/data",
            ...     schema_name="sensor_msgs/Imu",
            ...     metadata={"sensor_type": "IMU", "frequency": 100},
            ...     message_paths=message_paths
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateTopicRequest(
            association=Association.file(file_id),
            end_time=end_time,
            message_count=message_count,
            message_paths=message_paths,
            metadata=metadata,
            schema_checksum=schema_checksum,
            schema_name=schema_name,
            start_time=start_time,
            topic_name=topic_name,
        )
        response = roboto_client.post(
            "v1/topics",
            data=request,
            caller_org_id=caller_org_id,
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_id(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        """Retrieve a topic by its unique identifier.

        Fetches a topic record from the Roboto platform using its unique topic ID.
        This is the most direct way to access a specific topic when you know its identifier.

        Args:
            topic_id: Unique identifier for the topic.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Topic instance representing the requested topic.

        Raises:
            RobotoNotFoundException: Topic with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the topic.

        Examples:
            >>> topic = Topic.from_id("topic_xyz789")
            >>> print(topic.name)
            '/camera/image'
            >>> print(topic.message_count)
            100
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        response = roboto_client.get(
            f"v1/topics/id/{topic_id}",
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_name_and_file(
        cls,
        topic_name: str,
        file_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        """Retrieve a topic by its name and associated file.

        Fetches a topic record using its name and the file it's associated with. This is
        useful when you know the topic name (e.g., "/camera/image") and the file containing
        the topic data.

        Args:
            topic_name: Name of the topic to retrieve.
            file_id: Unique identifier of the file containing the topic.
            owner_org_id: Organization ID to scope the search. If None, uses caller's org.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Topic instance representing the requested topic.

        Raises:
            RobotoNotFoundException: Topic with the given name does not exist in the specified file.
            RobotoUnauthorizedException: Caller lacks permission to access the topic.

        Examples:
            >>> topic = Topic.from_name_and_file(
            ...     topic_name="/camera/image",
            ...     file_id="file_abc123"
            ... )
            >>> print(topic.topic_id)
            topic_xyz789
            >>> print(len(topic.message_paths))
            5
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        quoted_topic_name = urllib.parse.quote_plus(topic_name)
        encoded_association = Association.file(file_id).url_encode()

        response = roboto_client.get(
            f"v1/topics/association/{encoded_association}/name/{quoted_topic_name}",
            owner_org_id=owner_org_id,
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def get_by_dataset(
        cls, dataset_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Generator["Topic", None, None]:
        """List all topics associated with files in a dataset.

        Retrieves all topics from files within the specified dataset. If multiple files
        contain topics with the same name (e.g., chunked files with the same schema),
        they are returned as separate topic objects.

        Args:
            dataset_id: Unique identifier of the dataset to search.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Yields:
            Topic instances associated with files in the dataset.

        Raises:
            RobotoNotFoundException: Dataset with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the dataset.

        Examples:
            >>> for topic in Topic.get_by_dataset("ds_abc123"):
            ...     print(f"Topic: {topic.name} (File: {topic.file_id})")
            Topic: /camera/image (File: file_001)
            Topic: /imu/data (File: file_001)
            Topic: /camera/image (File: file_002)
            Topic: /imu/data (File: file_002)

            >>> # Count topics by name
            >>> from collections import Counter
            >>> topic_names = [topic.name for topic in Topic.get_by_dataset("ds_abc123")]
            >>> print(Counter(topic_names))
            Counter({'/camera/image': 2, '/imu/data': 2})
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        page_token: typing.Optional[str] = None

        while True:
            query_params: dict[str, typing.Any] = {}
            if page_token:
                query_params["page_token"] = str(page_token)

            paginated_results = roboto_client.get(
                f"v1/datasets/{dataset_id}/topics",
                query=query_params,
            ).to_paginated_list(TopicRecord)

            for record in paginated_results.items:
                yield cls(record=record, roboto_client=roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    @classmethod
    def get_by_file(
        cls,
        file_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Topic", None, None]:
        """List all topics associated with a specific file.

        Retrieves all topics contained within the specified file. This is useful for
        exploring the structure of robotics data files and understanding what data
        streams are available.

        Args:
            file_id: Unique identifier of the file to search.
            owner_org_id: Organization ID to scope the search. If None, uses caller's org.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Yields:
            Topic instances associated with the specified file.

        Raises:
            RobotoNotFoundException: File with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the file.

        Examples:
            >>> for topic in Topic.get_by_file("file_abc123"):
            ...     print(f"Topic: {topic.name} ({topic.message_count} messages)")
            Topic: /camera/image (150 messages)
            Topic: /imu/data (1500 messages)
            Topic: /gps/fix (50 messages)

            >>> # Get topics with specific schema
            >>> camera_topics = [
            ...     topic for topic in Topic.get_by_file("file_abc123")
            ...     if "camera" in topic.name
            ... ]
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        encoded_association = Association.file(file_id).url_encode()

        page_token: typing.Optional[str] = None
        while True:
            response = roboto_client.get(
                f"v1/topics/association/{encoded_association}",
                owner_org_id=owner_org_id,
                query={"page_token": page_token} if page_token else None,
            )
            paginated_results = response.to_paginated_list(TopicRecord)
            for topic_record in paginated_results.items:
                yield cls(topic_record, roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: TopicRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__topic_data_service = topic_data_service or TopicDataService(
            self.__roboto_client
        )

    def __eq__(self, other: typing.Any):
        if not isinstance(other, Topic):
            return NotImplemented

        return self.__record == other.__record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def association(self) -> Association:
        """Association linking this topic to its source entity (typically a file)."""
        return self.__record.association

    @property
    def created(self) -> datetime:
        """Timestamp when this topic was created in the Roboto platform."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Identifier of the user or system that created this topic."""
        return self.__record.created_by

    @property
    def dataset_id(self) -> typing.Optional[str]:
        """Unique identifier of the dataset containing this topic, if applicable."""
        if self.association.is_dataset:
            return self.association.association_id

        if self.association.is_file:
            # This is equivalent to File.from_id(file_id), but without introducing a circular dependency
            return self.__roboto_client.get(
                f"v1/files/record/{self.association.association_id}"
            ).to_dict(json_path=["data", "association_id"])

        return None

    @property
    def default_representation(self) -> typing.Optional[RepresentationRecord]:
        """Default representation used for accessing this topic's data."""
        return self.__record.default_representation

    @property
    def end_time(self) -> typing.Optional[int]:
        """End time of the topic data in nanoseconds since UNIX epoch."""
        return self.__record.end_time

    @property
    def file_id(self) -> typing.Optional[str]:
        """Unique identifier of the file containing this topic, if applicable."""
        if self.association.is_file:
            return self.association.association_id

        return None

    @property
    def message_count(self) -> typing.Optional[int]:
        """Total number of messages in this topic."""
        return self.__record.message_count

    @property
    def message_paths(self) -> collections.abc.Sequence[MessagePathRecord]:
        """Sequence of message path records defining the topic's schema."""
        return self.__record.message_paths

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Metadata dictionary associated with this topic."""
        return dict(self.__record.metadata)

    @property
    def modified(self) -> datetime:
        """Timestamp when this topic was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Identifier of the user or system that last modified this topic."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Name of the topic (e.g., '/camera/image', '/imu/data')."""
        return self.__record.topic_name

    @property
    def org_id(self) -> str:
        """Organization ID that owns this topic."""
        return self.__record.org_id

    @property
    def record(self) -> TopicRecord:
        """Topic representation in the Roboto database.

        This property is on the path to deprecation. All ``TopicRecord`` attributes
        are accessible directly using a ``Topic`` instance.
        """

        return self.__record

    @property
    def schema_checksum(self) -> typing.Optional[str]:
        """Checksum of the topic's message schema for validation."""
        return self.__record.schema_checksum

    @property
    def schema_name(self) -> typing.Optional[str]:
        """Name of the message schema (e.g., 'sensor_msgs/Image')."""
        return self.__record.schema_name

    @property
    def start_time(self) -> typing.Optional[int]:
        """Start time of the topic data in nanoseconds since UNIX epoch."""
        return self.__record.start_time

    @property
    def topic_id(self) -> str:
        """Unique identifier for this topic."""
        return self.__record.topic_id

    @property
    def topic_name(self) -> str:
        """Name of the topic (e.g., '/camera/image', '/imu/data')."""
        return self.__record.topic_name

    @property
    def url_quoted_name(self) -> str:
        """URL-encoded version of the topic name for use in API calls."""
        return urllib.parse.quote_plus(self.name)

    def add_message_path(
        self,
        message_path: str,
        data_type: str,
        canonical_data_type: CanonicalDataType,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
    ) -> MessagePathRecord:
        """Add a new message path to this topic.

        Creates a new message path within this topic, defining a specific field or signal
        that can be extracted from the topic's data. Message paths use dot notation to
        specify nested attributes within the topic's schema.

        Args:
            message_path: Dot-delimited path to the attribute (e.g., "pose.position.x").
            data_type: Native data type of the attribute as it appears in the original data
                source (e.g., "float32", "uint8[]", "geometry_msgs/Pose"). Used primarily
                for display purposes and should match the robot's runtime language or
                schema definitions.
            canonical_data_type: Normalized Roboto data type that enables specialized
                platform features for maps, images, timestamps, and other data with
                special interpretations.
            metadata: Additional metadata to associate with the message path.

        Returns:
            MessagePathRecord representing the newly created message path.

        Raises:
            RobotoConflictException: Message path already exists for this topic.
            RobotoUnauthorizedException: Caller lacks permission to modify the topic.

        Examples:
            >>> from roboto.domain.topics import CanonicalDataType
            >>> topic = Topic.from_id("topic_xyz789")
            >>> message_path = topic.add_message_path(
            ...     message_path="pose.position.x",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Number,
            ...     metadata={"unit": "meters"}
            ... )
            >>> print(message_path.message_path)
            pose.position.x
        """

        request = AddMessagePathRequest(
            message_path=message_path,
            data_type=data_type,
            canonical_data_type=canonical_data_type,
            metadata=metadata or {},
        )

        encoded_association = self.association.url_encode()
        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path",
            data=request,
            owner_org_id=self.org_id,
        )
        message_path_record = response.to_record(MessagePathRecord)
        self.refresh()
        return message_path_record

    def add_message_path_representation(
        self,
        message_path_id: str,
        association: Association,
        storage_format: RepresentationStorageFormat,
        version: int,
    ) -> RepresentationRecord:
        """Add a representation for a specific message path.

        Associates a message path with a data representation, enabling efficient access
        to specific fields within the topic data. Representations can be in different
        storage formats like MCAP or Parquet.

        Args:
            message_path_id: Unique identifier of the message path.
            association: Association pointing to the representation data.
            storage_format: Format of the representation data.
            version: Version number of the representation.

        Returns:
            RepresentationRecord representing the newly created representation.

        Raises:
            RobotoNotFoundException: Message path with the given ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to modify the topic.

        Examples:
            >>> from roboto.association import Association
            >>> from roboto.domain.topics import RepresentationStorageFormat
            >>> topic = Topic.from_id("topic_xyz789")
            >>> representation = topic.add_message_path_representation(
            ...     message_path_id="mp_123",
            ...     association=Association.file("file_repr_456"),
            ...     storage_format=RepresentationStorageFormat.MCAP,
            ...     version=1
            ... )
            >>> print(representation.representation_id)
            repr_789
        """
        encoded_association = self.association.url_encode()

        request = AddMessagePathRepresentationRequest(
            association=association,
            message_path_id=message_path_id,
            storage_format=storage_format,
            version=version,
        )

        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.refresh()
        return representation_record

    def delete(self) -> None:
        """Delete this topic from the Roboto platform.

        Permanently removes this topic and all its associated message paths and representations
        from the platform. This operation cannot be undone.

        Raises:
            RobotoNotFoundException: Topic does not exist or has already been deleted.
            RobotoUnauthorizedException: Caller lacks permission to delete the topic.

        Examples:
            >>> topic = Topic.from_id("topic_xyz789")
            >>> topic.delete()
            # Topic and all its data are now permanently deleted
        """
        encoded_association = self.association.url_encode()
        self.__roboto_client.delete(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}",
            owner_org_id=self.org_id,
        )

    def get_data(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Return this topic's underlying data.

        Retrieves and yields data records from this topic, with optional filtering by
        message paths and time range. Each yielded datum is a dictionary that matches
        this topic's schema.

        Args:
            message_paths_include: Dot notation paths that match attributes of individual
                data records to include. If None, all paths are included.
            message_paths_exclude: Dot notation paths that match attributes of individual
                data records to exclude. If None, no paths are excluded.
            start_time: Start time (inclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            end_time: End time (exclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            cache_dir: Directory where topic data will be downloaded if necessary.
                Defaults to :py:attr:`~roboto.domain.topics.topic_data_service.TopicDataService.DEFAULT_CACHE_DIR`.

        Yields:
            Dictionary records that match this topic's schema, filtered according to the parameters.

        Notes:
            For each example below, assume the following is a sample datum record that can be found in this topic:

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
            Print all data to stdout:

            >>> topic = Topic.from_name_and_file(...)
            >>> for record in topic.get_data():
            ...     print(record)

            Only include the "angular_velocity" sub-object, but filter out its "y" property:

            >>> topic = Topic.from_name_and_file(...)
            >>> for record in topic.get_data(
            ...     message_paths_include=["angular_velocity"],
            ...     message_paths_exclude=["angular_velocity.y"],
            ... ):
            ...     print(record)

            Only include data between two timestamps:

            >>> topic = Topic.from_name_and_file(...)
            >>> for record in topic.get_data(
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127699468924,
            ... ):
            ...     print(record)

            Collect all topic data into a dataframe (requires installing the ``roboto[analytics]`` extra):

            >>> topic = Topic.from_name_and_file(...)
            >>> df = topic.get_data_as_df()
        """
        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def get_data_as_df(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> pandas.DataFrame:
        """Return this topic's underlying data as a pandas DataFrame.

        Retrieves topic data and converts it to a pandas DataFrame for analysis and
        visualization. The DataFrame is indexed by log time and contains columns for
        each message path in the topic data.

        Args:
            message_paths_include: Dot notation paths that match attributes of individual
                data records to include. If None, all paths are included.
            message_paths_exclude: Dot notation paths that match attributes of individual
                data records to exclude. If None, no paths are excluded.
            start_time: Start time (inclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            end_time: End time (exclusive) as nanoseconds since UNIX epoch or
                convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            cache_dir: Directory where topic data will be downloaded if necessary.
                Defaults to :py:attr:`~roboto.domain.topics.topic_data_service.TopicDataService.DEFAULT_CACHE_DIR`.

        Returns:
            pandas DataFrame containing the topic data, indexed by log time.

        Raises:
            ImportError: pandas is not installed. Install with ``roboto[analytics]`` extra.

        Notes:
            Requires installing this package using the ``roboto[analytics]`` extra.

        Examples:
            >>> topic = Topic.from_name_and_file("/imu/data", "file_abc123")
            >>> df = topic.get_data_as_df()
            >>> print(df.head())
                                    angular_velocity.x  angular_velocity.y  ...
            log_time
            1722870127699468923                  0.1                 0.2  ...
            1722870127699468924                  0.15                0.25 ...

            >>> # Filter specific message paths
            >>> df_filtered = topic.get_data_as_df(
            ...     message_paths_include=["angular_velocity"],
            ...     message_paths_exclude=["angular_velocity.z"]
            ... )
            >>> print(df_filtered.columns.tolist())
            ['angular_velocity.x', 'angular_velocity.y']
        """
        return self.__topic_data_service.get_data_as_df(
            topic_id=self.__record.topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def get_message_path(self, message_path: str) -> MessagePath:
        """Get a specific message path from this topic.

        Retrieves a MessagePath object for the specified path, enabling access to
        individual fields or signals within the topic's data schema.

        Args:
            message_path: Dot-delimited path to the desired attribute (e.g., "pose.position.x").

        Returns:
            MessagePath instance for the specified path.

        Raises:
            ValueError: No message path with the given name exists in this topic.

        Examples:
            >>> topic = Topic.from_name_and_file("/imu/data", "file_abc123")
            >>> angular_vel_x = topic.get_message_path("angular_velocity.x")
            >>> print(angular_vel_x.canonical_data_type)
            CanonicalDataType.Number

            >>> # Access message path statistics
            >>> print(angular_vel_x.mean)
            0.125
            >>> print(angular_vel_x.std_dev)
            0.05
        """
        for message_path_record in self.__record.message_paths:
            if message_path_record.message_path == message_path:
                return MessagePath(
                    message_path_record,
                    roboto_client=self.__roboto_client,
                    topic_data_service=self.__topic_data_service,
                )

        raise ValueError(
            f"Topic '{self.name}' does not have a message path matching '{message_path}'"
        )

    def refresh(self) -> None:
        """Refresh this topic instance with the latest data from the platform.

        Fetches the current state of the topic from the Roboto platform and updates
        this instance's data. Useful when the topic may have been modified by other
        processes or users.

        Examples:
            >>> topic = Topic.from_id("topic_xyz789")
            >>> # Topic may have been updated by another process
            >>> topic.refresh()
            >>> print(f"Current message count: {topic.message_count}")
        """
        topic = Topic.from_id(self.topic_id, self.__roboto_client)
        self.__record = topic.__record

    def set_default_representation(
        self,
        association: Association,
        storage_format: RepresentationStorageFormat,
        version: int,
    ) -> RepresentationRecord:
        """Set the default representation for this topic.

        Designates a specific representation as the default for this topic, which will
        be used when accessing topic data without specifying a particular representation.

        Args:
            association: Association pointing to the representation data.
            storage_format: Format of the representation data.
            version: Version number of the representation.

        Returns:
            RepresentationRecord representing the newly set default representation.

        Raises:
            RobotoNotFoundException: Specified representation does not exist.
            RobotoUnauthorizedException: Caller lacks permission to modify the topic.

        Examples:
            >>> from roboto.association import Association
            >>> from roboto.domain.topics import RepresentationStorageFormat
            >>> topic = Topic.from_id("topic_xyz789")
            >>> default_repr = topic.set_default_representation(
            ...     association=Association.file("file_repr_456"),
            ...     storage_format=RepresentationStorageFormat.MCAP,
            ...     version=2
            ... )
            >>> print(topic.default_representation.representation_id)
            repr_789
        """
        encoded_association = self.association.url_encode()
        request = SetDefaultRepresentationRequest(
            association=association,
            storage_format=storage_format,
            version=version,
        )
        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.refresh()
        return representation_record

    def to_association(self) -> Association:
        """Convert this topic to an Association object.

        Creates an Association object that can be used to reference this topic
        in other parts of the Roboto platform.

        Returns:
            Association object representing this topic.

        Examples:
            >>> topic = Topic.from_id("topic_xyz789")
            >>> association = topic.to_association()
            >>> print(association.association_type)
            AssociationType.Topic
            >>> print(association.association_id)
            topic_xyz789
        """
        return Association.topic(self.topic_id)

    def update(
        self,
        end_time: typing.Union[typing.Optional[int], NotSetType] = NotSet,
        message_count: typing.Union[int, NotSetType] = NotSet,
        schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        start_time: typing.Union[typing.Optional[int], NotSetType] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        message_path_changeset: typing.Union[MessagePathChangeset, NotSetType] = NotSet,
    ) -> "Topic":
        """Updates a topic's attributes and (optionally) its message paths.

        Args:
            schema_name:
              topic schema name. Setting to ``None`` clears the attribute.
            schema_checksum:
              topic schema checksum. Setting to ``None`` clears the attribute.
            start_time:
              topic data start time, in epoch nanoseconds.
              Must be non-negative. Setting to ``None`` clears the attribute.
            end_time:
              topic data end time, in epoch nanoseconds. Must be non-negative, and greater than `start_time`.
              Setting to `None` clears the attribute.
            message_count:
              number of messages recorded for this topic. Must be non-negative.
            metadata_changeset:
              a set of changes to apply to the topic's metadata
            message_path_changeset:
              a set of additions, deletions or updates to this topic's message paths.
              Updating or deleting non-existent message paths has no effect.
              Attempting to (re-)add existing message paths raises ``RobotoConflictException``,
              unless the changeset's ``replace_all`` flag is set to ``True``

        Returns:
            this ``Topic`` object with any updates applied

        Raises:
            RobotoInvalidRequestException:
              if any method argument has an invalid value, e.g. a negative ``message_count``
            RobotoConflictException:
              if, as part of the update, an attempt is made to add an already extant
              message path, and to this topic, and ``replace_all`` is not toggled
              on the ``message_path_changeset``
        """

        request = remove_not_set(
            UpdateTopicRequest(
                end_time=end_time,
                message_count=message_count,
                schema_checksum=schema_checksum,
                schema_name=schema_name,
                start_time=start_time,
                metadata_changeset=metadata_changeset,
                message_path_changeset=message_path_changeset,
            )
        )

        response = self.__roboto_client.put(
            f"v1/topics/id/{self.topic_id}",
            data=request,
            owner_org_id=self.org_id,
        )

        record = response.to_record(TopicRecord)
        self.__record = record

        if is_set(message_path_changeset) and message_path_changeset.has_changes():
            self.refresh()

        return self

    def update_message_path(
        self,
        message_path: str,
        metadata_changeset: typing.Union[TaglessMetadataChangeset, NotSetType] = NotSet,
        data_type: typing.Union[str, NotSetType] = NotSet,
        canonical_data_type: typing.Union[CanonicalDataType, NotSetType] = NotSet,
    ) -> MessagePath:
        """Update the metadata and attributes of a message path.

        Modifies an existing message path within this topic, allowing updates to
        its metadata, data type, and canonical data type. This is useful for
        correcting or enhancing message path definitions after initial creation.

        Args:
            message_path: Name of the message path to update (e.g., "pose.position.x").
            metadata_changeset: Metadata changeset to apply to any existing metadata.
            data_type: Native (application-specific) message path data type.
            canonical_data_type: Canonical Roboto data type corresponding to the native data type.

        Returns:
            MessagePath instance representing the updated message path.

        Raises:
            RobotoNotFoundException: No message path with the given name exists for this topic.
            RobotoUnauthorizedException: Caller lacks permission to modify the topic.

        Examples:
            >>> from roboto.updates import TaglessMetadataChangeset
            >>> from roboto.domain.topics import CanonicalDataType
            >>> topic = Topic.from_id("topic_xyz789")
            >>>
            >>> # Update metadata for a message path
            >>> changeset = TaglessMetadataChangeset(put_fields={"unit": "meters"})
            >>> updated_path = topic.update_message_path(
            ...     message_path="pose.position.x",
            ...     metadata_changeset=changeset
            ... )
            >>> print(updated_path.metadata["unit"])
            meters

            >>> # Update data type and canonical type
            >>> updated_path = topic.update_message_path(
            ...     message_path="velocity",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Number
            ... )
        """

        request = remove_not_set(
            UpdateMessagePathRequest(
                message_path=message_path,
                metadata_changeset=metadata_changeset,
                data_type=data_type,
                canonical_data_type=canonical_data_type,
            )
        )

        encoded_association = self.association.url_encode()
        response = self.__roboto_client.put(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path",
            data=request,
            owner_org_id=self.org_id,
        )

        message_path_record = response.to_record(MessagePathRecord)
        self.refresh()

        return MessagePath(
            record=message_path_record,
            roboto_client=self.__roboto_client,
            topic_data_service=self.__topic_data_service,
        )
