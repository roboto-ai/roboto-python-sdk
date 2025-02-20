# Copyright (c) 2024 Roboto Technologies, Inc.
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
from ...compat import import_optional_dependency
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
    """
    The set of data created by mapping over :py:class:`~roboto.domain.topics.Topic` data,
    picking out just those values from each datum at a given attribute path.
    """

    DELIMITER: typing.ClassVar = "."

    __record: MessagePathRecord
    __roboto_client: RobotoClient
    __topic_data_service: TopicDataService

    @staticmethod
    def parents(path: str) -> list[str]:
        """
        Given message path in dot notation, return list of its parent paths (also in dot notation).

        Example:
            >>> path = "pose.pose.position.x"
            >>> MessagePath.parents(path)
            ['pose.pose.position', 'pose.pose', 'pose']
        """
        parent_parts = MessagePath.parts(path)[:-1]
        return [
            MessagePath.DELIMITER.join(parent_parts[:i])
            for i in range(len(parent_parts), 0, -1)
        ]

    @staticmethod
    def parts(path: str) -> list[str]:
        """
        Split message path in dot notation into its constituent path parts.

        Example:
            >>> path = "pose.pose.position.x"
            >>> MessagePath.parts(path)
            ['pose', 'pose', 'position', 'x']
        """
        return path.split(MessagePath.DELIMITER)

    @classmethod
    def from_id(
        cls,
        message_path_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ) -> "MessagePath":
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
        return self.__get_statistic(MessagePathStatistic.Count)

    @property
    def created(self) -> datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def data_type(self) -> str:
        """Native data type for this message path, e.g. 'float32'"""

        return self.__record.data_type

    @property
    def max(self) -> PreComputedStat:
        return self.__get_statistic(MessagePathStatistic.Max)

    @property
    def mean(self) -> PreComputedStat:
        return self.__get_statistic(MessagePathStatistic.Mean)

    @property
    def median(self) -> PreComputedStat:
        return self.__get_statistic(MessagePathStatistic.Median)

    @property
    def message_path_id(self) -> str:
        return self.__record.message_path_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        return dict(self.__record.metadata)

    @property
    def min(self) -> PreComputedStat:
        return self.__get_statistic(MessagePathStatistic.Min)

    @property
    def modified(self) -> datetime:
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        return self.__record.modified_by

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def path(self) -> str:
        return self.__record.message_path

    @property
    def record(self) -> MessagePathRecord:
        return self.__record

    @property
    def topic_id(self) -> str:
        return self.__record.topic_id

    def get_data(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """
        Return a projection of topic data: the set of data created by mapping over data collected within a topic,
        picking out just those values at this message path.

        If ``start_time`` or ``end_time`` are defined,
        they should either be integers that represent nanoseconds since UNIX epoch,
        or convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
        Either or both may be omitted.
        ``start_time`` is inclusive, while ``end_time`` is exclusive.

        If ``cache_dir`` is defined, topic data will be downloaded to this location if necessary.
        If not provided, ``cache_dir`` defaults to
        :py:attr:`~roboto.domain.topics.topic_data_service.TopicDataService.DEFAULT_CACHE_DIR`.

        For each example below, assume the following is a sample datum record
        that can be found in this MessagePath's associated topic:

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
            Print all data to stdout.

            >>> topic = Topic.from_name_and_association(...)
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> for record in angular_velocity_x.get_data():
            >>>      print(record)

            Collect data into a dataframe. Requires installing the ``roboto[analytics]`` extra.

            >>> import math
            >>> import pandas as pd
            >>> topic = Topic.from_name_and_association(...)
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> df = angular_velocity_x.get_data_as_df()
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
        """
        Return this message path's underlying data as a pandas DataFrame.

        Requires installing this package using the ``roboto[analytics]`` extra.

        See :py:meth:`~roboto.domain.topics.message_path.MessagePath.get_data` for more information on the parameters.
        """
        pandas = import_optional_dependency("pandas", "analytics")

        df = pandas.json_normalize(
            data=list(
                self.get_data(
                    start_time=start_time,
                    end_time=end_time,
                    cache_dir=cache_dir,
                )
            )
        )

        if TopicDataService.LOG_TIME_ATTR_NAME in df.columns:
            return df.set_index(TopicDataService.LOG_TIME_ATTR_NAME)

        return df

    def to_association(self) -> Association:
        return Association.msgpath(self.message_path_id)

    def __get_statistic(self, stat: MessagePathStatistic) -> PreComputedStat:
        return self.__record.metadata.get(stat.value)
