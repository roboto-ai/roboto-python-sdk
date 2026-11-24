# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
from datetime import datetime
import pathlib
import tempfile
import typing
import urllib.parse

from ...association import Association
from ...compat import import_optional_dependency
from ...exceptions import RobotoConflictException
from ...http import RobotoClient
from ...logging import default_logger
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from ...time import Time, TimeUnit
from ...updates import (
    MetadataChangeset,
    TaglessMetadataChangeset,
)
from ...warnings import experimental
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
from .parquet import (
    ParquetParser,
    generate_message_path_requests,
    make_topic_filename_safe,
    upload_representation_file,
)
from .record import (
    CanonicalDataType,
    MessagePathRecord,
    RepresentationRecord,
    RepresentationSelector,
    RepresentationStorageFormat,
    TopicRecord,
    TopicTimeBounds,
)
from .topic_data_service import TopicDataService
from .topic_reader import Timestamp
from .topic_schema import TopicSchema

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


logger = default_logger()


class Topic:
    """A topic: a sequence of structured time-series data, called messages, linked to a source file.

    Each message follows the topic's schema, whose fields or signals are the topic's message paths. Data under one
    topic name in one file forms one topic, so a recording split across several files has one topic per file for each
    topic name. Ingestion usually creates topics. A ``Topic`` reads their data, with ``get_data`` and
    ``get_data_as_df``, and manages their message paths, representations, and metadata. Access to a topic follows
    access to its file.

    Get a ``Topic`` from ``from_id``, ``from_name_and_file``, ``get_by_file``, or
    :py:meth:`~roboto.domain.files.File.get_topics`. Each instance holds a copy of the topic's record: methods that
    change the topic update that copy from Roboto's response, and ``refresh`` fetches changes made elsewhere.
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
        message_paths: typing.Optional[collections.abc.Sequence[AddMessagePathRequest]] = (None),
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        """Create a topic in a file.

        Ingestion actions usually create topics. A new topic describes its data but holds none: it cannot be read
        with ``get_data`` or visualized until a representation of its data is registered, with
        ``set_default_representation`` or ``add_message_path_representation``. To create a topic and store its data
        from a pandas DataFrame in one call, use :py:meth:`~roboto.domain.files.File.add_topic`.

        Args:
            file_id: ID of the file the topic belongs to.
            topic_name: Name of the topic, such as ``"/imu/data"``. Unique within the file.
            end_time: End of the topic's data, in nanoseconds since the Unix epoch. Must not be negative.
            message_count: Number of messages in the topic. Must not be negative.
            metadata: Key-value metadata to set on the topic. ``None`` sets none.
            schema_checksum: Checksum of the topic's message schema.
            schema_name: Name of the topic's message schema, such as ``"sensor_msgs/Imu"``.
            start_time: Start of the topic's data, in nanoseconds since the Unix epoch. Must not be negative.
            message_paths: Message paths to create with the topic. No two may have the same ``message_path``.
                ``None`` creates none.
            caller_org_id: Organization to create the topic in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new topic.

        Raises:
            RobotoConflictException: The file already has a topic named ``topic_name``.
            RobotoInvalidRequestException: ``topic_name`` is blank, a time or ``message_count`` is negative, or two
                of ``message_paths`` have the same ``message_path``.

        Examples:
            Create a topic for camera data:

            >>> topic = Topic.create(
            ...     file_id="fl_12345",
            ...     topic_name="/camera/image",
            ...     schema_name="sensor_msgs/Image",
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ...     message_count=100,
            ... )

            Create a topic with metadata and message paths:

            >>> from roboto.domain.topics import AddMessagePathRequest, CanonicalDataType
            >>> message_paths = [
            ...     AddMessagePathRequest(
            ...         message_path="header.stamp.sec",
            ...         data_type="uint32",
            ...         canonical_data_type=CanonicalDataType.Timestamp,
            ...         path_in_schema=["header", "stamp", "sec"],
            ...         metadata={"unit": "s"},
            ...     )
            ... ]
            >>> topic = Topic.create(
            ...     file_id="fl_12345",
            ...     topic_name="/imu/data",
            ...     schema_name="sensor_msgs/Imu",
            ...     metadata={"sensor_type": "IMU", "frequency": 100},
            ...     message_paths=message_paths,
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
    def create_from_df(
        cls,
        file_id: str,
        dataset_id: str,
        topic_name: str,
        df: "pandas.DataFrame",
        timestamp_column: typing.Optional[str] = None,
        timestamp_unit: typing.Optional[typing.Union[str, TimeUnit]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Topic:
        """Create a topic in a file from a pandas DataFrame, or replace the data of the file's topic of that name.

        :py:meth:`~roboto.domain.files.File.add_topic` does the same and needs only the file. Each row of ``df`` is
        one message. The method:

        1. Writes ``df`` to a Parquet file.
        2. Creates the topic, with message paths, a message count, and a time range read from that file. When the
           file already has a topic named ``topic_name``, it replaces that topic's message paths, message count,
           time range, and schema name instead.
        3. Uploads the Parquet file to the dataset's ``.VISUALIZATION_ASSETS`` directory and makes it the topic's
           default representation, so the data can be read and visualized.

        If the upload fails, the topic keeps the message paths from step 2 without the data to match them.

        Args:
            file_id: ID of the file the topic belongs to.
            dataset_id: ID of the dataset that contains the file. The Parquet file is uploaded to it.
            topic_name: Name of the topic, unique within the file. Also set as the topic's schema name.
            df: Data of the topic, one row per message. It must have a timestamp column, named by
                ``timestamp_column`` or found automatically.
            timestamp_column: Name of the column that holds each message's timestamp. ``None`` uses the first column
                of a timezone-aware timestamp type.
            timestamp_unit: Unit of the timestamp column's values: ``"s"``, ``"ms"``, ``"us"`` or ``"ns"``, or a
                :py:class:`~roboto.time.TimeUnit`. Required when the column is numeric. A timestamp-typed column
                carries its own unit, which this overrides.
            caller_org_id: Organization to create the topic in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The created or updated topic.

        Raises:
            IngestionException: The timestamp column is not in ``df``, cannot be found automatically, is neither
                numeric nor a timezone-aware timestamp type, or is numeric with no ``timestamp_unit``; or the upload
                finished without Roboto returning an ID for the Parquet file.
            ImportError: The ``roboto[ingestion]`` extra is not installed.

        Examples:
            Create a topic from a DataFrame with a timestamp column in seconds:

            >>> import pandas as pd
            >>> from roboto.domain.topics import Topic
            >>> df = pd.DataFrame(
            ...     {
            ...         "timestamp": [1763947309.4198897, 1763947316.7686195, 1763947335.0095527],
            ...         "temperature": [20.5, 21.0, 20.8],
            ...         "humidity": [45.2, 46.1, 45.8],
            ...     }
            ... )
            >>> topic = Topic.create_from_df(
            ...     file_id="fl_12345",
            ...     dataset_id="ds_12345",
            ...     topic_name="sensor_data",
            ...     df=df,
            ...     timestamp_column="timestamp",
            ...     timestamp_unit="s",
            ... )
            >>> print(f"Created topic: {topic.name}")
            Created topic: sensor_data

            Do the same with :py:meth:`~roboto.domain.files.File.add_topic`, which finds the dataset itself:

            >>> from roboto import File
            >>> file = File.from_id("fl_12345")
            >>> topic = file.add_topic("sensor_data", df, timestamp_column="timestamp", timestamp_unit="s")
        """
        # pandas needs pyarrow to write Parquet. Checking first raises an ImportError that names the extra to install.
        import_optional_dependency("pyarrow", "ingestion")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)

            file_name = make_topic_filename_safe(topic_name)
            parquet_path = tmpdir_path / f"{file_name}_{file_id}.parquet"
            df.to_parquet(parquet_path, engine="pyarrow")

            parser = ParquetParser(parquet_path)
            timestamp = parser.extract_timestamp_info(timestamp_column, timestamp_unit)
            message_path_requests = list(generate_message_path_requests(parser, timestamp))

            # RobotoConflictException means the file already has a topic named topic_name; replace its message paths
            # and time range instead.
            try:
                topic = Topic.create(
                    file_id=file_id,
                    topic_name=topic_name,
                    schema_name=topic_name,
                    message_count=parser.row_count,
                    message_paths=message_path_requests,
                    start_time=timestamp.start_time_ns(),
                    end_time=timestamp.end_time_ns(),
                    caller_org_id=caller_org_id,
                    roboto_client=roboto_client,
                )
                logger.info("Created topic '%s'", topic_name)
            except RobotoConflictException:
                topic = Topic.from_name_and_file(
                    file_id=file_id,
                    topic_name=topic_name,
                    roboto_client=roboto_client,
                )
                logger.info("Topic '%s' already exists, updating it", topic_name)
                topic.update(
                    schema_name=topic_name,
                    message_count=parser.row_count,
                    message_path_changeset=MessagePathChangeset.from_replacement_message_paths(message_path_requests),
                    start_time=timestamp.start_time_ns(),
                    end_time=timestamp.end_time_ns(),
                )

            representation_file_id = upload_representation_file(
                parquet_path,
                Association.dataset(dataset_id),
                caller_org_id=caller_org_id,
                roboto_client=roboto_client,
            )
            topic.set_default_representation(
                association=Association.file(representation_file_id),
                storage_format=RepresentationStorageFormat.PARQUET,
                version=1,
            )

        return topic

    @classmethod
    def from_id(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        """Fetch a topic by its ID.

        Args:
            topic_id: Unique ID of the topic, beginning with ``tp_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No topic has this ID.

        Examples:
            >>> topic = Topic.from_id("tp_12345")
            >>> print(topic.name, topic.message_count)
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
        """Fetch a topic by its name and the file it belongs to.

        Topic names are unique within a file, so a name and a file identify one topic.

        Args:
            topic_name: Name of the topic, such as ``"/camera/image"``.
            file_id: ID of the file the topic belongs to.
            owner_org_id: Organization that owns the file. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The file has no topic with this name.

        Examples:
            >>> topic = Topic.from_name_and_file(topic_name="/camera/image", file_id="fl_12345")
            >>> print(topic.topic_id)
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
        """List the topics of a dataset's files.

        When several files have a topic with the same name, such as files split from one recording, each file's
        topic is yielded separately.

        Note:
            The topics come without message paths: each topic's ``message_paths`` is empty. To get them, use
            ``get_by_file`` on each file instead.

        Args:
            dataset_id: ID of the dataset.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each topic of the dataset's files.

        Raises:
            RobotoNotFoundException: No dataset has this ID. It surfaces on the first iteration.

        Examples:
            Print each topic with the file it belongs to:

            >>> for topic in Topic.get_by_dataset("ds_12345"):
            ...     print(topic.name, topic.file_id)

            Count the files that have each topic name:

            >>> from collections import Counter
            >>> topic_name_counts = Counter(topic.name for topic in Topic.get_by_dataset("ds_12345"))
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
        """List the topics of a file.

        Args:
            file_id: ID of the file.
            owner_org_id: Organization that owns the file. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each topic of the file, with its message paths.

        Examples:
            Print each topic's name and message count:

            >>> for topic in Topic.get_by_file("fl_12345"):
            ...     print(topic.name, topic.message_count)

            Keep only the topics whose names contain ``"camera"``:

            >>> camera_topics = [topic for topic in Topic.get_by_file("fl_12345") if "camera" in topic.name]
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

    @classmethod
    def get_time_bounds_by_association(
        cls,
        association: Association,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> TopicTimeBounds:
        """Fetch the earliest start time and latest end time across the topics of a file or other entity.

        For a file, returns the same values as taking the minimum ``start_time`` and maximum ``end_time`` over
        ``get_by_file``, in one request instead of one per page of topics.

        Note:
            Only topics that belong to ``association`` itself count. Topics usually belong to files, so a dataset
            association leaves out the topics of the dataset's files; for those, use
            :py:meth:`~roboto.domain.datasets.Dataset.get_topic_time_bounds`.

        Args:
            association: Entity whose topics to cover, such as ``Association.file("fl_12345")``.
            owner_org_id: Organization that owns the entity. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            Bounds in nanoseconds since the Unix epoch. Both are ``None`` when the entity has no topics, and either
            is ``None`` when no topic has that bound.

        Examples:
            >>> from roboto.association import Association
            >>> bounds = Topic.get_time_bounds_by_association(Association.file("fl_12345"))
            >>> print(bounds.start_time, bounds.end_time)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        encoded_association = association.url_encode()

        return roboto_client.get(
            f"v1/topics/association/{encoded_association}/time-bounds",
            owner_org_id=owner_org_id,
        ).to_record(TopicTimeBounds)

    def __init__(
        self,
        record: TopicRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__topic_data_service = topic_data_service or TopicDataService(self.__roboto_client)
        self.__fetch_message_paths_left_out()

    def __fetch_message_paths_left_out(self) -> None:
        """Fetch the message paths the record leaves out, a page at a time, so ``message_paths`` holds every one."""
        page_token = self.__record.message_paths_next_token
        if page_token is None:
            return
        message_paths = list(self.__record.message_paths)
        while page_token is not None:
            page = self.__roboto_client.get(
                f"v1/topics/id/{self.__record.topic_id}/message-paths",
                query={"page_token": page_token},
                owner_org_id=self.__record.org_id,
            ).to_paginated_list(MessagePathRecord)
            message_paths.extend(page.items)
            page_token = page.next_token
        # Replace the record rather than change it, because it may be the record the caller passed to Topic(record).
        self.__record = self.__record.model_copy(
            update={"message_paths": message_paths, "message_paths_next_token": None}
        )

    def __eq__(self, other: typing.Any):
        if not isinstance(other, Topic):
            return NotImplemented

        return self.__record == other.__record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def association(self) -> Association:
        """Resource the topic belongs to, usually the file its data came from."""
        return self.__record.association

    @property
    def created(self) -> datetime:
        """Time the topic was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the topic."""
        return self.__record.created_by

    @property
    def dataset_id(self) -> typing.Optional[str]:
        """ID of the dataset the topic or its file belongs to, or ``None`` if the topic belongs to neither.

        When the topic belongs to a file, each access makes a request to Roboto for the file's record.
        """
        if self.association.is_dataset:
            return self.association.association_id

        if self.association.is_file:
            # Reads the file's record directly, because importing File here would create a circular import.
            return self.__roboto_client.get(f"v1/files/record/{self.association.association_id}").to_dict(
                json_path=["data", "association_id"]
            )

        return None

    @property
    def default_representation(self) -> typing.Optional[RepresentationRecord]:
        """Record of the representation that holds the data of each message path without one of its own.

        ``None`` if the topic has no default representation, in which case only message paths with representations of
        their own can be read.
        """
        return self.__record.default_representation

    @property
    def end_time(self) -> typing.Optional[int]:
        """Timestamp of the topic's latest message, in nanoseconds since the Unix epoch, or ``None`` if unknown."""
        return self.__record.end_time

    @property
    def file_id(self) -> typing.Optional[str]:
        """ID of the file the topic belongs to, or ``None`` if the topic belongs to something other than a file."""
        if self.association.is_file:
            return self.association.association_id

        return None

    @property
    def message_count(self) -> typing.Optional[int]:
        """Number of messages in the topic, or ``None`` if unknown."""
        return self.__record.message_count

    @property
    def message_paths(self) -> collections.abc.Sequence[MessagePathRecord]:
        """Message paths of the topic.

        Empty for a topic listed by ``get_by_dataset``, which leaves them out.
        """
        return self.__record.message_paths

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata on the topic.

        Each access returns a copy, so changing it does not change the topic.
        """
        return dict(self.__record.metadata)

    @property
    def modified(self) -> datetime:
        """Time the topic was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the topic."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Name of the topic, such as ``"/imu/data"``.

        Unique within its file. Same as ``topic_name``.
        """
        return self.__record.topic_name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the topic."""
        return self.__record.org_id

    @property
    def record(self) -> TopicRecord:
        """Record of the topic that this instance holds.

        Each of its fields is also a property of ``Topic``. ``refresh`` replaces it with the current one.
        """

        return self.__record

    @property
    def schema_checksum(self) -> typing.Optional[str]:
        """Checksum of the topic's schema, or ``None`` if the topic has no known schema."""
        return self.__record.schema_checksum

    @property
    @experimental
    def schema_id(self) -> typing.Optional[str]:
        """ID of the topic's schema, or ``None`` if the topic has no schema or Roboto has not yet recorded it."""
        return self.__record.schema_id

    @property
    def schema_name(self) -> typing.Optional[str]:
        """Name of the topic's message type, such as ``"sensor_msgs/PointCloud2"``, or ``None`` if it is unknown."""
        return self.__record.schema_name

    @property
    def start_time(self) -> typing.Optional[int]:
        """Timestamp of the topic's earliest message, in nanoseconds since the Unix epoch, or ``None`` if unknown."""
        return self.__record.start_time

    @property
    def topic_id(self) -> str:
        """Unique ID of the topic, beginning with ``tp_``."""
        return self.__record.topic_id

    @property
    def topic_name(self) -> str:
        """Name of the topic, such as ``"/imu/data"``.

        Unique within its file.
        """
        return self.__record.topic_name

    def add_message_path(
        self,
        message_path: str,
        data_type: str,
        canonical_data_type: CanonicalDataType,
        path_in_schema: typing.Optional[list[str]] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
    ) -> MessagePathRecord:
        """Add a message path to the topic.

        Fetches the topic's record afterwards, so ``message_paths`` includes the new message path.

        Args:
            message_path: Dot-delimited path to a field within the topic's messages, such as ``"pose.position.x"``.
                Unique within the topic.
            data_type: Native data type of the field, as the source data's framework names it, such as
                ``"float32"``, ``"uint8[]"`` or ``"geometry_msgs/Pose"``.
            canonical_data_type: Framework-independent data type of the field, which Roboto uses to choose how to
                display its data, such as on a map or as an image.
            path_in_schema: Components of the field's path in the source data's schema, in order from the schema
                root. Unlike ``message_path``, it keeps a field name that contains a dot as one component. ``None``
                splits ``message_path`` at each dot.
            metadata: Key-value metadata to set on the message path. ``None`` sets none.

        Returns:
            Record of the new message path.

        Raises:
            RobotoConflictException: The topic already has a message path at ``message_path``.

        Examples:
            >>> from roboto.domain.topics import CanonicalDataType
            >>> topic = Topic.from_id("tp_12345")
            >>> message_path = topic.add_message_path(
            ...     message_path="pose.position.x",
            ...     data_type="float64",
            ...     canonical_data_type=CanonicalDataType.Number,
            ...     metadata={"frame": "map"},
            ... )
            >>> print(message_path.message_path)
            pose.position.x
        """
        path_in_schema = path_in_schema or message_path.split(".")

        request = AddMessagePathRequest(
            message_path=message_path,
            path_in_schema=path_in_schema,
            data_type=data_type,
            canonical_data_type=canonical_data_type,
            metadata=metadata or {},
        )

        response = self.__roboto_client.post(
            f"v1/topics/id/{self.topic_id}/message-path",
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
        format: typing.Optional[str] = None,
        transformations: typing.Optional[list[str]] = None,
    ) -> RepresentationRecord:
        """Register a representation of one of the topic's message paths.

        A representation is a stored copy of the data, in one file format and possibly transformed, such as encoded
        as JPEG. Within the topic, ``association``, ``storage_format`` and ``version`` together identify a
        representation, so registering a combination the topic already has updates that representation's ``format``
        and ``transformations`` instead of adding another. Fetches the topic's record afterwards.

        Args:
            message_path_id: ID of the message path the representation holds data for, beginning with ``mp_``.
            association: File, or other entity, that holds the representation's data. It must exist.
            storage_format: File format the representation's data is stored in.
            version: Version number of the representation.
            format: Content format of the data, such as an image encoding (``"jpeg"``) or a message schema name
                (``"sensor_msgs/Image"``). ``None`` keeps the stored format when the representation already exists.
            transformations: Transformations applied to produce the representation, in order, as
                ``"<kind>:<param>"`` strings such as ``"downsample:0.5"``
                (see :py:class:`~roboto.domain.topics.TransformationKind`). ``None`` keeps the stored list when the
                representation already exists, and records none otherwise.

        Returns:
            Record of the registered representation.

        Raises:
            RobotoNotFoundException: The topic has no message path with ID ``message_path_id``.

        Examples:
            >>> from roboto.association import Association
            >>> from roboto.domain.topics import RepresentationStorageFormat
            >>> topic = Topic.from_id("tp_12345")
            >>> representation = topic.add_message_path_representation(
            ...     message_path_id="mp_12345",
            ...     association=Association.file("fl_12345"),
            ...     storage_format=RepresentationStorageFormat.MCAP,
            ...     version=1,
            ... )
        """
        request = AddMessagePathRepresentationRequest(
            association=association,
            message_path_id=message_path_id,
            storage_format=storage_format,
            version=version,
            format=format,
            transformations=transformations,
        )

        response = self.__roboto_client.post(
            f"v1/topics/id/{self.topic_id}/message-path/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.refresh()
        return representation_record

    def delete(self) -> None:
        """Delete the topic. This cannot be undone.

        Also deletes the topic's message paths and representations, the MCAP files that hold its representations,
        and each event linked to nothing but this topic and its message paths. Deleting a topic that no longer exists
        succeeds and changes nothing.

        Examples:
            >>> topic = Topic.from_id("tp_12345")
            >>> topic.delete()
        """
        self.__roboto_client.delete(
            f"v1/topics/id/{self.topic_id}",
            owner_org_id=self.org_id,
        )

    @experimental
    def get_schema(self) -> typing.Optional["TopicSchema"]:
        """Fetch the topic's schema, or return ``None`` if the topic has no schema.

        Returns:
            The ``TopicSchema`` that the topic's messages follow, or ``None`` when ``schema_id`` is ``None``.

        Raises:
            RobotoNotFoundException: ``schema_id`` names a schema that no longer exists.

        Examples:
            >>> topic = Topic.from_id("tp_12345")
            >>> schema = topic.get_schema()
            >>> if schema is not None:
            ...     for field in schema.fields:
            ...         print(field.name, field.data_type)
        """
        if self.schema_id is None:
            return None

        return TopicSchema.from_id(self.schema_id, roboto_client=self.__roboto_client)

    def get_data(
        self,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        representation_selector: RepresentationSelector = RepresentationSelector.raw(),
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield this topic's messages, optionally limited to some message paths and a time range.

        Each yielded item is a ``(timestamp, message)`` tuple, where ``message`` is a dictionary that follows the
        topic's schema.

        Args:
            message_paths_include: Message paths to include. ``None`` includes every message path.
            message_paths_exclude: Message paths to leave out. ``None`` leaves out none.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            cache_dir: Directory to download the topic's data to. ``None`` uses
                :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.
            representation_selector: Which of the topic's stored representations to read. Defaults to the raw,
                untransformed data. A message path with no representation that meets it is left out.

        Yields:
            ``(timestamp, message)`` tuples, limited by the arguments.

        Examples:
            Print every message:

            >>> topic = Topic.from_name_and_file(topic_name="/imu/data", file_id="fl_12345")
            >>> for timestamp, message in topic.get_data():
            ...     print(timestamp, message)

            Include ``angular_velocity`` but leave out its ``y`` axis:

            >>> for timestamp, message in topic.get_data(
            ...     message_paths_include=["angular_velocity"],
            ...     message_paths_exclude=["angular_velocity.y"],
            ... ):
            ...     print(message)

            Read only the messages in a time range:

            >>> for timestamp, message in topic.get_data(
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ... ):
            ...     print(timestamp)

            Read the JPEG-encoded representation of an image topic:

            >>> from roboto.domain.topics import RepresentationSelector
            >>> image_topic = Topic.from_name_and_file(topic_name="/camera/image", file_id="fl_12345")
            >>> for timestamp, message in image_topic.get_data(
            ...     representation_selector=RepresentationSelector(content_format="jpeg"),
            ... ):
            ...     print(timestamp)

            Read many topics in parallel with a thread pool:

            >>> from concurrent.futures import ThreadPoolExecutor
            >>> topics = list(Topic.get_by_file("fl_12345"))
            >>> with ThreadPoolExecutor(max_workers=16) as executor:
            ...     messages_by_topic = list(executor.map(lambda t: list(t.get_data()), topics))
        """
        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
            representation_selector=representation_selector,
        )

    def get_data_as_df(
        self,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        representation_selector: RepresentationSelector = RepresentationSelector.raw(),
    ) -> pandas.DataFrame:
        """Fetch this topic's messages as a pandas DataFrame, optionally limited to some message paths and a time range.

        Each row is one message. Nested fields become columns with dot-delimited names, such as
        ``angular_velocity.x``. The index, named ``_index``, is a UTC ``pandas.DatetimeIndex`` of each message's
        timestamp.

        Args:
            message_paths_include: Message paths to include. ``None`` includes every message path.
            message_paths_exclude: Message paths to leave out. ``None`` leaves out none.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            cache_dir: Directory to download the topic's data to. ``None`` uses
                :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.
            representation_selector: Which of the topic's stored representations to read. Defaults to the raw,
                untransformed data. A message path with no representation that meets it is left out.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.

        Note:
            An array-typed message path, such as a ``float32[3]`` acceleration, becomes one column whose values are
            lists. Its elements are not message paths, so neither a column nor ``message_paths_include`` or
            ``message_paths_exclude`` can name one. Select the array's path and unpack the column, as in the last
            example. ``numpy.stack`` needs every row to have the same length, so process a variable-length array, such
            as a point cloud, row by row, for example with ``df[column].map(...)``.

        Examples:
            Read every message:

            >>> topic = Topic.from_name_and_file(topic_name="/imu/data", file_id="fl_12345")
            >>> df = topic.get_data_as_df()
            >>> print(df.head())

            Include ``angular_velocity`` but leave out its ``z`` axis:

            >>> df_filtered = topic.get_data_as_df(
            ...     message_paths_include=["angular_velocity"],
            ...     message_paths_exclude=["angular_velocity.z"],
            ... )

            Unpack a fixed-length array message path, a column of lists, into a numpy array of shape ``(N, 3)``:

            >>> import numpy as np
            >>> df_accel = topic.get_data_as_df(message_paths_include=["acceleration"])
            >>> xyz = np.stack(df_accel["acceleration"].to_numpy())

            Read many topics in parallel with a thread pool, then combine them in time order:

            >>> import pandas as pd
            >>> from concurrent.futures import ThreadPoolExecutor
            >>> topics = list(Topic.get_by_file("fl_12345"))
            >>> with ThreadPoolExecutor(max_workers=16) as executor:
            ...     dfs = list(executor.map(lambda t: t.get_data_as_df(), topics))
            >>> combined = pd.concat(dfs).sort_index()
        """
        return self.__topic_data_service.get_data_as_df(
            topic_id=self.__record.topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
            representation_selector=representation_selector,
        )

    def get_message_path(self, message_path: str) -> MessagePath:
        """Return the topic's message path at ``message_path``.

        Looks the path up in this instance's record, without a request to Roboto.

        Args:
            message_path: Dot-delimited path to a field within the topic's messages, such as ``"pose.position.x"``.

        Returns:
            The :py:class:`~roboto.domain.topics.MessagePath`, which reads that field's data and statistics.

        Raises:
            ValueError: The topic has no message path at ``message_path``, or this instance's record has no message
                paths, as for a topic listed by ``get_by_dataset``.

        Examples:
            >>> topic = Topic.from_name_and_file(topic_name="/imu/data", file_id="fl_12345")
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> print(angular_velocity_x.mean, angular_velocity_x.stddev)
        """
        for message_path_record in self.__record.message_paths:
            if message_path_record.message_path == message_path:
                return MessagePath(
                    message_path_record,
                    roboto_client=self.__roboto_client,
                    topic_data_service=self.__topic_data_service,
                )

        raise ValueError(f"Topic '{self.name}' does not have a message path matching '{message_path}'")

    def refresh(self) -> None:
        """Replace this instance's record with the topic's current record from Roboto.

        Use it to see changes that other users or processes made after this instance was loaded.

        Raises:
            RobotoNotFoundException: The topic no longer exists.

        Examples:
            >>> topic = Topic.from_id("tp_12345")
            >>> topic.refresh()
            >>> print(topic.message_count)
        """
        topic = Topic.from_id(self.topic_id, self.__roboto_client)
        self.__record = topic.__record

    def set_default_representation(
        self,
        association: Association,
        storage_format: RepresentationStorageFormat,
        version: int,
        format: typing.Optional[str] = None,
        transformations: typing.Optional[list[str]] = None,
    ) -> RepresentationRecord:
        """Register a representation of the topic's data and make it the topic's default.

        Roboto reads the default representation for every message path that has no representation of its own, so
        registering one is what makes a new topic's data readable; ingestion actions do it after uploading the data.
        The topic's other representations stay registered and stop being the default. Within the topic,
        ``association``, ``storage_format`` and ``version`` together identify a representation, so registering a
        combination the topic already has updates that representation instead of adding another. Fetches the topic's
        record afterwards, so ``default_representation`` is the new default.

        Args:
            association: File, or other entity, that holds the representation's data. It must exist.
            storage_format: File format the representation's data is stored in.
            version: Version number of the representation.
            format: Content format of the data, such as an image encoding (``"jpeg"``) or a message schema name
                (``"sensor_msgs/Image"``). ``None`` keeps the stored format when the representation already exists.
            transformations: Transformations applied to produce the representation, in order, as
                ``"<kind>:<param>"`` strings such as ``"downsample:0.5"``
                (see :py:class:`~roboto.domain.topics.TransformationKind`). ``None`` keeps the stored list when the
                representation already exists, and records none otherwise.

        Returns:
            Record of the registered representation.

        Examples:
            >>> from roboto.association import Association
            >>> from roboto.domain.topics import RepresentationStorageFormat
            >>> topic = Topic.from_id("tp_12345")
            >>> representation = topic.set_default_representation(
            ...     association=Association.file("fl_12345"),
            ...     storage_format=RepresentationStorageFormat.MCAP,
            ...     version=2,
            ... )
        """
        request = SetDefaultRepresentationRequest(
            association=association,
            storage_format=storage_format,
            version=version,
            format=format,
            transformations=transformations,
        )
        response = self.__roboto_client.post(
            f"v1/topics/id/{self.topic_id}/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.refresh()
        return representation_record

    def to_association(self) -> Association:
        """Return an association that refers to this topic, such as to link an event to it.

        Examples:
            >>> topic = Topic.from_id("tp_12345")
            >>> association = topic.to_association()
            >>> print(association.association_type)
            AssociationType.Topic
            >>> print(association.association_id)
            tp_12345
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
        """Update the topic's properties and, optionally, its message paths.

        An argument left unset (``NotSet``) leaves that property unchanged. Roboto applies the whole update, or none
        of it if any part is refused.

        Args:
            end_time: End of the topic's data, in nanoseconds since the Unix epoch. Must not be negative, and must not
                be before ``start_time`` when this call sets both. ``None`` clears it.
            message_count: Number of messages in the topic. Must not be negative.
            schema_checksum: Checksum of the topic's message schema. Setting it requires a schema name, already on
                the topic or set by this call. ``None`` clears it.
            schema_name: Name of the topic's message schema, such as ``"sensor_msgs/Imu"``. ``None`` clears it; when
                the topic has a schema checksum, this call must clear that too.
            start_time: Start of the topic's data, in nanoseconds since the Unix epoch. Must not be negative.
                ``None`` clears it.
            metadata_changeset: Changes to the topic's metadata. Topics have no tags, so the changeset's tag changes
                have no effect.
            message_path_changeset: Message paths to add, update, and delete. Updating or deleting a message path
                the topic does not have is skipped.

        Returns:
            This instance, with its record updated. When ``message_path_changeset`` has changes, the method fetches
            the topic's record afterwards, so ``message_paths`` shows them.

        Raises:
            RobotoInvalidRequestException: An argument has a value Roboto rejects, such as a negative
                ``message_count``.
            RobotoConflictException: ``message_path_changeset`` adds a message path the topic already has, and its
                ``replace_all`` is not set.

        Examples:
            Set the message count and a metadata field:

            >>> from roboto.updates import MetadataChangeset
            >>> topic = Topic.from_id("tp_12345")
            >>> topic.update(
            ...     message_count=1500,
            ...     metadata_changeset=MetadataChangeset(put_fields={"sensor": "imu"}),
            ... )

            Clear the schema name and checksum:

            >>> topic.update(schema_name=None, schema_checksum=None)
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
        # The response holds no message paths, so keep the ones this topic has. A message path change refreshes them.
        self.__record = record.model_copy(update={"message_paths": self.__record.message_paths})

        if is_set(message_path_changeset) and message_path_changeset.has_changes():
            self.refresh()

        return self

    def update_message_path(
        self,
        message_path: str,
        metadata_changeset: typing.Union[TaglessMetadataChangeset, NotSetType] = NotSet,
        data_type: typing.Union[str, NotSetType] = NotSet,
        canonical_data_type: typing.Union[CanonicalDataType, NotSetType] = NotSet,
        path_in_schema: typing.Union[list[str], NotSetType] = NotSet,
    ) -> MessagePath:
        """Update one of the topic's message paths.

        An argument left unset (``NotSet``) leaves that property of the message path unchanged. Fetches the topic's
        record afterwards, so ``message_paths`` shows the change.

        Args:
            message_path: Dot-delimited path of the message path to update, such as ``"pose.position.x"``.
            metadata_changeset: Changes to the message path's metadata.
            data_type: Native data type of the field, as the source data's framework names it, such as
                ``"float32"``.
            canonical_data_type: Framework-independent data type of the field. Changing it changes how Roboto
                displays the field's data.
            path_in_schema: Components of the field's path in the source data's schema, in order from the schema
                root.

        Returns:
            The updated message path.

        Raises:
            RobotoNotFoundException: The topic has no message path at ``message_path``.

        Examples:
            Set a metadata field on a message path:

            >>> from roboto.updates import TaglessMetadataChangeset
            >>> topic = Topic.from_id("tp_12345")
            >>> changeset = TaglessMetadataChangeset(put_fields={"frame": "map"})
            >>> updated_path = topic.update_message_path(message_path="pose.position.x", metadata_changeset=changeset)
            >>> print(updated_path.metadata["frame"])
            map

            Change a message path's data types:

            >>> from roboto.domain.topics import CanonicalDataType
            >>> updated_path = topic.update_message_path(
            ...     message_path="velocity", data_type="float64", canonical_data_type=CanonicalDataType.Number
            ... )
        """

        request = remove_not_set(
            UpdateMessagePathRequest(
                message_path=message_path,
                metadata_changeset=metadata_changeset,
                data_type=data_type,
                canonical_data_type=canonical_data_type,
                path_in_schema=path_in_schema,
            )
        )

        response = self.__roboto_client.put(
            f"v1/topics/id/{self.topic_id}/message-path",
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
