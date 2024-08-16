# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

from ...http import RobotoClient
from ...time import Time
from .record import (
    MessagePathRecord,
    MessagePathStatistic,
)
from .topic_data_service import TopicDataService

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

    @property
    def count(self) -> PreComputedStat:
        return self.__get_statistic(MessagePathStatistic.Count)

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
    def min(self) -> PreComputedStat:
        return self.__get_statistic(MessagePathStatistic.Min)

    @property
    def path(self) -> str:
        return self.__record.message_path

    @property
    def record(self) -> MessagePathRecord:
        return self.__record

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

            Collect data into a dataframe. Requires installing ``pandas`` into the same Python environment.

            >>> import math
            >>> import pandas as pd
            >>> topic = Topic.from_name_and_association(...)
            >>> angular_velocity_x = topic.get_message_path("angular_velocity.x")
            >>> df = pd.json_normalize(data=list(angular_velocity_x.get_data()))
            >>> assert math.isclose(angular_velocity_x.mean, df[angular_velocity_x.path].mean())
        """

        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=[self.__record.message_path],
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def __get_statistic(self, stat: MessagePathStatistic) -> PreComputedStat:
        return self.__record.metadata.get(stat.value)
