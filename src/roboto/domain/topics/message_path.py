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
    FixedArrayDataType,
    MessagePathRecord,
    MessagePathStatistic,
)
from .topic_data_service import TopicDataService
from .topic_reader import Timestamp

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

PreComputedStat: typing.TypeAlias = typing.Optional[typing.Union[int, float]]
"""Value of a statistic Roboto computed for a message path, or ``None`` if it was not computed."""


class MessagePath:
    """A message path: one field or signal of a topic's messages, such as ``"pose.position.x"``.

    Each instance holds a copy of the message path's record: the field's native and canonical data types, its
    key-value metadata, and the statistics Roboto's ingestion actions computed for it, which the ``min``, ``max``,
    ``mean`` and similar properties read. A statistic that was not computed reads ``None``, not zero. ``get_data``
    and ``get_data_as_df`` read the field's values from the topic's messages.

    Get a ``MessagePath`` from :py:meth:`~roboto.domain.topics.Topic.get_message_path` or ``from_id``.
    """

    DELIMITER: typing.ClassVar = "."
    """Separator between the components of a message path."""

    __record: MessagePathRecord
    __roboto_client: RobotoClient
    __topic_data_service: TopicDataService

    @staticmethod
    def parents(path_in_schema: list[str]) -> list[str]:
        """Return the paths of a field's ancestors in the source data's schema, nearest first.

        Each ancestor's path is leading components of ``path_in_schema``, joined with dots.

        Args:
            path_in_schema: Components of the field's path in the source data's schema, in order from the schema
                root, such as :py:attr:`~roboto.domain.topics.MessagePathRecord.path_in_schema`.

        Returns:
            The ancestors' paths, or an empty list for a field at the schema root.

        Raises:
            TypeError: ``path_in_schema`` is a string, such as a dot-delimited path, rather than a list.

        Examples:
            >>> MessagePath.parents(["pose", "pose", "position", "x"])
            ['pose.pose.position', 'pose.pose', 'pose']

            A field at the schema root has no ancestors:

            >>> MessagePath.parents(["velocity"])
            []
        """
        # A string is iterable, so without this check its characters would be read as path components.
        if isinstance(path_in_schema, str):
            raise TypeError(
                "MessagePath.parents() now requires a list[str] (path_in_schema), "
                "not a dot-delimited string. Use MessagePathRecord.path_in_schema "
                "or split your path into components."
            )

        parent_parts = path_in_schema[:-1]
        return [MessagePath.DELIMITER.join(parent_parts[:i]) for i in range(len(parent_parts), 0, -1)]

    @classmethod
    def from_id(
        cls,
        message_path_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ) -> "MessagePath":
        """Fetch a message path by its ID.

        Args:
            message_path_id: Unique ID of the message path, beginning with ``mp_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            topic_data_service: Service to read the message path's data with. ``None`` creates one that uses
                ``roboto_client``.

        Raises:
            RobotoNotFoundException: No message path has this ID.

        Examples:
            >>> message_path = MessagePath.from_id("mp_12345")
            >>> print(message_path.path)
            angular_velocity.x
            >>> print(message_path.canonical_data_type)
            CanonicalDataType.Number
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/topics/message-path/id/{message_path_id}").to_record(MessagePathRecord)
        return cls(record, roboto_client, topic_data_service)

    def __init__(
        self,
        record: MessagePathRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__topic_data_service = topic_data_service or TopicDataService(self.__roboto_client)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, MessagePath):
            return NotImplemented

        return self.__record == other.__record

    @property
    def array_length(self) -> typing.Optional[int]:
        """Fixed length of the array that ``data_type`` declares with a trailing ``[N]``, or ``None``.

        ``float64[7]``, ``float[4]`` and ``fixed_size_list<element: double>[3]`` read 7, 4 and 3. ``None`` for a
        variable-length array (``float64[]``, ``list<element: double>``), a ROS 2 bounded one (``float64[<=10]``),
        a multi-dimensional one (``float64[2][3]``, ``fixed_size_list<element: list<element: double>>[3]``) and a
        scalar, so ``None`` means the length is unknown, not that the path is not an array. The element type does
        not matter: ``string[8]`` reads 8 and ``Point[3]`` reads 3. Only ``data_type`` is read; an ``array_length``
        key in ``metadata`` is not consulted.
        """
        fixed_array = FixedArrayDataType.parse(self.__record.data_type)
        return fixed_array.length if fixed_array else None

    @property
    def canonical_data_type(self) -> CanonicalDataType:
        """Framework-independent data type of the field, which Roboto uses to choose how to display its data."""
        return self.__record.canonical_data_type

    @property
    def count(self) -> PreComputedStat:
        """Number of values the message path has, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.Count)

    @property
    def created(self) -> datetime:
        """Time the message path was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the message path."""
        return self.__record.created_by

    @property
    def data_type(self) -> str:
        """Native data type of the field, as the source data's framework names it.

        :py:attr:`~roboto.domain.topics.MessagePathRecord.data_type` gives examples.
        """
        return self.__record.data_type

    @property
    def max(self) -> PreComputedStat:
        """Maximum of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.Max)

    @property
    def mean(self) -> PreComputedStat:
        """Mean of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.Mean)

    @property
    def median(self) -> PreComputedStat:
        """Median of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.Median)

    @property
    def message_path_id(self) -> str:
        """Unique ID of the message path, beginning with ``mp_``."""
        return self.__record.message_path_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata on the message path, such as ``{"min": 0.71, "max": 1.77}``.

        It includes the message path's computed statistics. Returns a copy, so changing it does not change this
        instance. :py:attr:`~roboto.domain.topics.MessagePathRecord.metadata` names the keys Roboto gives a meaning to.
        """
        return dict(self.__record.metadata)

    @property
    def min(self) -> PreComputedStat:
        """Minimum of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.Min)

    @property
    def modified(self) -> datetime:
        """Time the message path was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the message path."""
        return self.__record.modified_by

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the message path, which is the organization that owns its topic."""
        return self.__record.org_id

    @property
    def p25(self) -> PreComputedStat:
        """25th percentile of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.P25)

    @property
    def p75(self) -> PreComputedStat:
        """75th percentile of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.P75)

    @property
    def p95(self) -> PreComputedStat:
        """95th percentile of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.P95)

    @property
    def p99(self) -> PreComputedStat:
        """99th percentile of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.P99)

    @property
    def path(self) -> str:
        """Dot-delimited path to the field within the topic's messages, such as ``"pose.position.x"``."""
        return self.__record.message_path

    @property
    def record(self) -> MessagePathRecord:
        """Record of the message path that this instance holds."""
        return self.__record

    @property
    def stddev(self) -> PreComputedStat:
        """Standard deviation of the message path's values, or ``None`` if it was not computed."""
        return self.__get_statistic(MessagePathStatistic.Stddev)

    @property
    def topic_id(self) -> str:
        """ID of the topic this message path belongs to."""
        return self.__record.topic_id

    def get_data(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield this message path's values, optionally limited to a time range.

        Each yielded item is a ``(timestamp, message)`` tuple. ``timestamp`` is in nanoseconds since the Unix epoch,
        and ``message`` is a dictionary that holds only this message path's field, nested under its parent fields as
        in the topic's schema.

        Args:
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            cache_dir: Directory to download the topic's data to. ``None`` uses
                :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.

        Yields:
            ``(timestamp, message)`` tuples within the time range.

        Examples:
            Print every value of ``angular_velocity.x``:

            >>> topic = Topic.from_name_and_file(topic_name="/imu/data", file_id="fl_12345")
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> for timestamp, message in angular_velocity_x.get_data():
            ...     print(timestamp, message["angular_velocity"]["x"])

            Print only the values within a time range:

            >>> for timestamp, message in angular_velocity_x.get_data(
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ... ):
            ...     print(timestamp, message)

            Read several message paths at once with a thread pool:

            >>> from concurrent.futures import ThreadPoolExecutor
            >>> message_paths = [topic.get_message_path(path) for path in ["angular_velocity.x", "angular_velocity.y"]]
            >>> with ThreadPoolExecutor(max_workers=16) as executor:
            ...     results = list(executor.map(lambda mp: list(mp.get_data()), message_paths))
        """

        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=[self.__record.source_path],
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
        """Fetch this message path's values as a pandas DataFrame, optionally limited to a time range.

        The DataFrame's columns hold this message path's values. Its index, named ``_index``, is a
        ``pandas.DatetimeIndex`` of each row's timestamp in UTC. Requires the ``roboto[analytics]`` extra.

        Args:
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            cache_dir: Directory to download the topic's data to. ``None`` uses
                :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.

        Examples:
            >>> topic = Topic.from_name_and_file(topic_name="/imu/data", file_id="fl_12345")
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> df = angular_velocity_x.get_data_as_df()
            >>> print(df.head())

            Read several message paths at once with a thread pool, and combine them in time order:

            >>> import pandas as pd
            >>> from concurrent.futures import ThreadPoolExecutor
            >>> message_paths = [topic.get_message_path(path) for path in ["angular_velocity.x", "angular_velocity.y"]]
            >>> with ThreadPoolExecutor(max_workers=16) as executor:
            ...     dfs = list(executor.map(lambda mp: mp.get_data_as_df(), message_paths))
            >>> combined = pd.concat(dfs).sort_index()
        """
        return self.__topic_data_service.get_data_as_df(
            topic_id=self.__record.topic_id,
            message_paths_include=[self.__record.source_path],
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def to_association(self) -> Association:
        """Return an association that refers to the message path, for APIs that take one.

        Examples:
            >>> message_path = MessagePath.from_id("mp_12345")
            >>> message_path.to_association().association_id
            'mp_12345'
        """
        return Association.msgpath(self.message_path_id)

    def __get_statistic(self, stat: MessagePathStatistic) -> PreComputedStat:
        return self.__record.metadata.get(stat.value)
