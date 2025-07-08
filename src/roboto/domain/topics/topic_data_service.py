# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

from ...http import RobotoClient
from ...logging import default_logger
from ...time import Time, to_epoch_nanoseconds
from .mcap_topic_reader import McapTopicReader
from .operations import (
    MessagePathRepresentationMapping,
)
from .parquet_topic_reader import (
    ParquetTopicReader,
)
from .record import MessagePathRecord
from .topic_reader import TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


class TopicDataService:
    """Internal service for retrieving and managing topic data.

    This service handles the low-level operations for accessing topic data that has been
    ingested by the Roboto platform. It manages representation downloads, filtering,
    and processing of various data formats to provide efficient access to time-series robotics data.

    Note:
        This is an internal service class and is not intended as a public API.
        To access topic data, prefer :py:meth:`~roboto.domain.topics.Topic.get_data`
        or :py:meth:`~roboto.domain.topics.MessagePath.get_data` instead.
    """

    DEFAULT_CACHE_DIR: typing.ClassVar[pathlib.Path] = (
        pathlib.Path.home() / ".cache" / "roboto" / "topic-data"
    )
    LOG_TIME_ATTR_NAME: typing.ClassVar[str] = "log_time"

    __cache_dir: pathlib.Path
    __roboto_client: RobotoClient

    def __init__(
        self,
        roboto_client: RobotoClient,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ):
        self.__roboto_client = roboto_client
        self.__cache_dir = (
            pathlib.Path(cache_dir)
            if cache_dir is not None
            else TopicDataService.DEFAULT_CACHE_DIR
        )

    def get_data(
        self,
        topic_id: str,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir_override: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """Retrieve data for a specific topic with optional filtering.

        Downloads and processes topic data representations, applying message path and temporal filters as specified.
        Merges data from multiple representations when necessary.

        Args:
            topic_id: Unique identifier of the topic to retrieve data for.
            message_paths_include: Dot notation paths to include in the results.
                If None, all paths are included.
            message_paths_exclude: Dot notation paths to exclude from the results.
                If None, no paths are excluded.
            start_time: Start time (inclusive) for temporal filtering.
            end_time: End time (exclusive) for temporal filtering.
            cache_dir_override: Override the default cache directory for downloads.

        Yields:
            Dictionary records containing the filtered topic data, with a 'log_time'
            field indicating the timestamp of each record.
        """
        cache_dir = self.__ensure_cache_dir(cache_dir_override)

        message_path_repr_mappings = self.__get_filtered_message_path_mappings(
            topic_id=topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
        )

        normalized_start_time = (
            to_epoch_nanoseconds(start_time) if start_time is not None else None
        )
        normalized_end_time = (
            to_epoch_nanoseconds(end_time) if end_time is not None else None
        )

        if McapTopicReader.accepts(message_path_repr_mappings):
            reader: TopicReader = McapTopicReader(self.__roboto_client, cache_dir)
            yield from reader.get_data(
                message_path_repr_mappings,
                TopicDataService.LOG_TIME_ATTR_NAME,
                normalized_start_time,
                normalized_end_time,
            )
        elif ParquetTopicReader.accepts(message_path_repr_mappings):
            reader = ParquetTopicReader()
            yield from reader.get_data(
                message_path_repr_mappings,
                TopicDataService.LOG_TIME_ATTR_NAME,
                normalized_start_time,
                normalized_end_time,
            )
        else:
            raise NotImplementedError(
                "No compatible reader found for this data. Please reach out to Roboto support."
            )

    def get_data_as_df(
        self,
        topic_id: str,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir_override: typing.Union[str, pathlib.Path, None] = None,
    ) -> "pandas.DataFrame":
        cache_dir = self.__ensure_cache_dir(cache_dir_override)

        message_path_repr_mappings = self.__get_filtered_message_path_mappings(
            topic_id=topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
        )

        normalized_start_time = (
            to_epoch_nanoseconds(start_time) if start_time is not None else None
        )
        normalized_end_time = (
            to_epoch_nanoseconds(end_time) if end_time is not None else None
        )

        if McapTopicReader.accepts(message_path_repr_mappings):
            reader: TopicReader = McapTopicReader(self.__roboto_client, cache_dir)
            df = reader.get_data_as_df(
                message_path_repr_mappings,
                TopicDataService.LOG_TIME_ATTR_NAME,
                normalized_start_time,
                normalized_end_time,
            )
        elif ParquetTopicReader.accepts(message_path_repr_mappings):
            reader = ParquetTopicReader()
            df = reader.get_data_as_df(
                message_path_repr_mappings,
                TopicDataService.LOG_TIME_ATTR_NAME,
                normalized_start_time,
                normalized_end_time,
            )
        else:
            raise NotImplementedError(
                "No compatible reader found for this data. Please reach out to Roboto support."
            )

        if TopicDataService.LOG_TIME_ATTR_NAME in df.columns:
            return df.set_index(TopicDataService.LOG_TIME_ATTR_NAME)

        return df

    def __ensure_cache_dir(
        self, cache_dir_override: typing.Union[str, pathlib.Path, None] = None
    ) -> pathlib.Path:
        cache_dir = (
            pathlib.Path(cache_dir_override)
            if cache_dir_override is not None
            else self.__cache_dir
        )
        if not cache_dir.exists():
            cache_dir.mkdir(parents=True)

        return cache_dir

    def __filter_message_paths(
        self,
        seq: collections.abc.Sequence[MessagePathRecord],
        include_paths: typing.Optional[collections.abc.Sequence[str]],
        exclude_paths: typing.Optional[collections.abc.Sequence[str]],
    ) -> collections.abc.Sequence[MessagePathRecord]:
        if not include_paths and not exclude_paths:
            return seq

        filtered = []
        include_paths_set = set(include_paths or [])
        exclude_paths_set = set(exclude_paths or [])
        for message_path_record in seq:
            message_path_parts = message_path_record.message_path.split(".")
            message_path_parents = set(
                ".".join(message_path_parts[:i])
                for i in range(len(message_path_parts), 0, -1)
            )

            if include_paths and message_path_parents.isdisjoint(include_paths_set):
                continue

            if exclude_paths and not message_path_parents.isdisjoint(exclude_paths_set):
                continue

            filtered.append(message_path_record)

        return filtered

    def __get_filtered_message_path_mappings(
        self,
        topic_id: str,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> list[MessagePathRepresentationMapping]:
        message_path_repr_mappings_response = self.__roboto_client.get(
            f"v1/topics/id/{topic_id}/message-path/representations"
        )
        message_path_repr_mappings = message_path_repr_mappings_response.to_record_list(
            MessagePathRepresentationMapping
        )

        # Exclude a MessagePathRepresentationMapping if no message paths remain after applying message path filters.
        message_path_repr_mappings = [
            message_path_repr_map.model_copy(
                update={
                    "message_paths": self.__filter_message_paths(
                        message_path_repr_map.message_paths,
                        include_paths=message_paths_include,
                        exclude_paths=message_paths_exclude,
                    )
                }
            )
            for message_path_repr_map in message_path_repr_mappings
        ]
        message_path_repr_mappings = [
            message_path_repr_map
            for message_path_repr_map in message_path_repr_mappings
            if message_path_repr_map.message_paths
        ]

        # WARN if no message paths are left after filtering
        if not any(
            len(message_path_repr_map.message_paths) > 0
            for message_path_repr_map in message_path_repr_mappings
        ):
            logger.warning(
                "The request for topic data will not yield any results. "
                "Please check that the 'message_paths_include' and 'message_paths_exclude' parameters "
                "are not filtering out all available message paths for this topic."
            )

        return message_path_repr_mappings
