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
from ...time import (
    Time,
    TimeUnit,
    to_epoch_nanoseconds,
)
from .mcap_topic_reader import McapTopicReader
from .operations import (
    MessagePathRepresentationMapping,
)
from .parquet import ParquetTopicReader
from .record import (
    CanonicalDataType,
    MessagePathRecord,
)
from .topic_reader import TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


class TopicDataService:
    """Internal service for retrieving topic data.

    This service handles the low-level operations for accessing topic data that has been
    ingested by the Roboto platform. It manages downloads, filtering, and processing
    various data formats to provide efficient access to time-series robotics data.

    Note:
        This is not intended as a public API.
        To access topic data, prefer the ``get_data`` or ``get_data_as_df`` methods
        on :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`,
        or :py:class:`~roboto.domain.events.Event`.
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
        log_time_unit: TimeUnit = TimeUnit.Nanoseconds,
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
            log_time_unit: Time unit for the log_time field in the returned records.
            cache_dir_override: Override the default cache directory for downloads.

        Yields:
            Dictionary records containing the filtered topic data, with a 'log_time'
            field indicating the timestamp of each record.
        """
        cache_dir = self.__ensure_cache_dir(cache_dir_override)

        message_path_repr_mappings = self.__get_message_path_mappings(topic_id)
        filtered_message_path_repr_mappings = self.__filter_message_path_mappings(
            message_path_repr_mappings,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
        )

        start_time_ns = (
            to_epoch_nanoseconds(start_time) if start_time is not None else None
        )
        end_time_ns = to_epoch_nanoseconds(end_time) if end_time is not None else None

        if McapTopicReader.accepts(filtered_message_path_repr_mappings):
            reader: TopicReader = McapTopicReader(self.__roboto_client, cache_dir)
            yield from reader.get_data(
                filtered_message_path_repr_mappings,
                log_time_attr_name=TopicDataService.LOG_TIME_ATTR_NAME,
                log_time_unit=log_time_unit,
                start_time=start_time_ns,
                end_time=end_time_ns,
            )
        elif ParquetTopicReader.accepts(filtered_message_path_repr_mappings):
            reader = ParquetTopicReader(self.__roboto_client)
            timestamp_mapping = self.__find_timestamp_message_path_mapping(
                message_path_repr_mappings
            )
            yield from reader.get_data(
                filtered_message_path_repr_mappings,
                log_time_attr_name=TopicDataService.LOG_TIME_ATTR_NAME,
                log_time_unit=log_time_unit,
                start_time=start_time_ns,
                end_time=end_time_ns,
                timestamp_message_path_representation_mapping=timestamp_mapping,
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
        log_time_unit: TimeUnit = TimeUnit.Nanoseconds,
        cache_dir_override: typing.Union[str, pathlib.Path, None] = None,
    ) -> "pandas.DataFrame":
        """Retrieve data for a specific topic as a pandas DataFrame with optional filtering.

        Downloads and processes topic data representations, applying message path and temporal filters as specified.
        Merges data from multiple representations when necessary and returns the result as a pandas DataFrame.

        Args:
            topic_id: Unique identifier of the topic to retrieve data for.
            message_paths_include: Dot notation paths to include in the results.
                If None, all paths are included.
            message_paths_exclude: Dot notation paths to exclude from the results.
                If None, no paths are excluded.
            start_time: Start time (inclusive) for temporal filtering.
            end_time: End time (exclusive) for temporal filtering.
            log_time_unit: Time unit for the log_time field in the returned DataFrame.
            cache_dir_override: Override the default cache directory for downloads.

        Returns:
            pandas.DataFrame containing the filtered topic data,
            with log_time as the index if available.
        """
        cache_dir = self.__ensure_cache_dir(cache_dir_override)

        message_path_repr_mappings = self.__get_message_path_mappings(topic_id)
        filtered_message_path_repr_mappings = self.__filter_message_path_mappings(
            message_path_repr_mappings,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
        )

        start_time_ns = (
            to_epoch_nanoseconds(start_time) if start_time is not None else None
        )
        end_time_ns = to_epoch_nanoseconds(end_time) if end_time is not None else None

        if McapTopicReader.accepts(filtered_message_path_repr_mappings):
            reader: TopicReader = McapTopicReader(self.__roboto_client, cache_dir)
            df = reader.get_data_as_df(
                filtered_message_path_repr_mappings,
                log_time_attr_name=TopicDataService.LOG_TIME_ATTR_NAME,
                log_time_unit=log_time_unit,
                start_time=start_time_ns,
                end_time=end_time_ns,
            )
        elif ParquetTopicReader.accepts(filtered_message_path_repr_mappings):
            reader = ParquetTopicReader(self.__roboto_client)
            timestamp_mapping = self.__find_timestamp_message_path_mapping(
                message_path_repr_mappings
            )
            df = reader.get_data_as_df(
                filtered_message_path_repr_mappings,
                log_time_attr_name=TopicDataService.LOG_TIME_ATTR_NAME,
                log_time_unit=log_time_unit,
                start_time=start_time_ns,
                end_time=end_time_ns,
                timestamp_message_path_representation_mapping=timestamp_mapping,
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
        message_path_records: collections.abc.Sequence[MessagePathRecord],
        include_paths: typing.Optional[collections.abc.Sequence[str]],
        exclude_paths: typing.Optional[collections.abc.Sequence[str]],
    ) -> collections.abc.Sequence[MessagePathRecord]:
        if not include_paths and not exclude_paths:
            return message_path_records

        filtered = []
        include_paths_set = set(include_paths) if include_paths is not None else set()
        exclude_paths_set = set(exclude_paths) if exclude_paths is not None else set()

        for record in message_path_records:
            paths = set(record.parents())
            paths.add(record.source_path)
            paths.add(
                # May be different from source_path, support specifying either one
                record.message_path
            )

            if include_paths and paths.isdisjoint(include_paths_set):
                continue

            if exclude_paths and not paths.isdisjoint(exclude_paths_set):
                continue

            filtered.append(record)

        return filtered

    def __filter_message_path_mappings(
        self,
        message_path_repr_mappings: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> list[MessagePathRepresentationMapping]:
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

    def __find_timestamp_message_path_mapping(
        self,
        message_path_repr_mappings: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
    ) -> typing.Optional[MessagePathRepresentationMapping]:
        for mapping in message_path_repr_mappings:
            for message_path in mapping.message_paths:
                if message_path.canonical_data_type != CanonicalDataType.Timestamp:
                    continue

                return MessagePathRepresentationMapping(
                    message_paths=[message_path], representation=mapping.representation
                )

        return None

    def __get_message_path_mappings(
        self,
        topic_id: str,
    ) -> list[MessagePathRepresentationMapping]:
        message_path_repr_mappings_response = self.__roboto_client.get(
            f"v1/topics/id/{topic_id}/message-path/representations"
        )
        return message_path_repr_mappings_response.to_record_list(
            MessagePathRepresentationMapping
        )
