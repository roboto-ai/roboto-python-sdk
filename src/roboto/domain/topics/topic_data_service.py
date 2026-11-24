# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import pathlib
import typing

from ...compat import import_optional_dependency
from ...http import RobotoClient
from ...logging import default_logger
from ...time import (
    Time,
    to_epoch_nanoseconds,
)
from .mcap_topic_reader import McapTopicReader
from .parquet import ParquetTopicReader
from .record import (
    CanonicalDataType,
    MessagePathRecord,
    MessagePathRepresentationMapping,
    RepresentationSelector,
)
from .topic_reader import Timestamp, TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


def iterable_to_set(arg: collections.abc.Iterable[str]) -> set[str]:
    """Return ``arg`` as a set of strings, treating a single string as one item rather than as its characters.

    :py:meth:`~roboto.domain.topics.Topic.get_data` and the other methods that read topic data filter by message path
    through it, so most code never calls it.

    Args:
        arg: Strings to convert, or a single string.

    Returns:
        ``arg`` itself when it is a set, not a copy; otherwise a new set of its items.

    Raises:
        TypeError: ``arg`` is not iterable.
    """
    if isinstance(arg, set):
        return arg
    elif isinstance(arg, str):
        return {
            arg,
        }
    elif isinstance(arg, collections.abc.Iterable):
        return set(arg)
    else:
        raise TypeError("Input must be iterable.")


class TopicDataService:
    """Reader of topic data for the ``get_data`` and ``get_data_as_df`` methods of topics, message paths and events.

    The SDK's own code uses it; to read topic data, use the ``get_data`` or ``get_data_as_df`` methods of
    :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`, or
    :py:class:`~roboto.domain.events.Event` instead.

    It fetches the representations that hold each of a topic's message paths, keeps the message paths and
    representations a read asks for, and reads them with the reader for their storage format, MCAP or Parquet.

    Args:
        roboto_client: Client to make requests to Roboto with.
        cache_dir: Directory to download Parquet-stored topic data to and reuse it from. ``None`` uses
            ``DEFAULT_CACHE_DIR``.
    """

    DEFAULT_CACHE_DIR: typing.ClassVar[pathlib.Path] = pathlib.Path.home() / ".cache" / "roboto" / "topic-data"
    """Directory Parquet-stored topic data is downloaded to when no other is given: ``~/.cache/roboto/topic-data``."""

    __cache_dir: pathlib.Path
    __roboto_client: RobotoClient

    def __init__(
        self,
        roboto_client: RobotoClient,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ):
        self.__roboto_client = roboto_client
        self.__cache_dir = pathlib.Path(cache_dir) if cache_dir is not None else TopicDataService.DEFAULT_CACHE_DIR

    def get_data(
        self,
        topic_id: str,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir_override: typing.Union[str, pathlib.Path, None] = None,
        representation_selector: RepresentationSelector = RepresentationSelector.raw(),
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield a topic's messages, optionally limited to some message paths and a time range.

        A message path matches a path in ``message_paths_include`` or ``message_paths_exclude`` when that path is its
        :py:attr:`~roboto.domain.topics.MessagePathRecord.message_path`, its
        :py:attr:`~roboto.domain.topics.MessagePathRecord.source_path`, or the path of one of its ancestors. The
        filters never leave out a message path whose data type is a timestamp.

        Args:
            topic_id: ID of the topic to read.
            message_paths_include: Message paths to include. ``None`` includes every message path.
            message_paths_exclude: Message paths to leave out. ``None`` leaves out none.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            cache_dir_override: Directory to download Parquet-stored data to for this read. ``None`` uses the
                directory the service was created with.
            representation_selector: Which of the topic's stored representations to read. Defaults to the original
                data, with no transformations.

        Yields:
            ``(timestamp, message)`` tuples: the timestamp in nanoseconds since the Unix epoch, and a dictionary that
            follows the topic's schema.

        Raises:
            NotImplementedError: The representations selected for the read are not all stored as MCAP or all as
                Parquet. It surfaces on the first iteration.
        """
        message_path_repr_mappings = self.__get_message_path_mappings(topic_id)
        filtered_message_path_repr_mappings = self.__filter_message_path_mappings(
            message_path_repr_mappings,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
        )
        selected_mappings = representation_selector.select_representations(filtered_message_path_repr_mappings)

        start_time_ns = to_epoch_nanoseconds(start_time) if start_time is not None else None
        end_time_ns = to_epoch_nanoseconds(end_time) if end_time is not None else None

        if McapTopicReader.accepts(selected_mappings):
            reader: TopicReader = McapTopicReader(self.__roboto_client)
            yield from reader.get_data(
                selected_mappings,
                start_time=start_time_ns,
                end_time=end_time_ns,
            )
        elif ParquetTopicReader.accepts(selected_mappings):
            reader = ParquetTopicReader(self.__roboto_client, cache_dir=self.__resolve_cache_dir(cache_dir_override))
            timestamp_mapping = self.__find_timestamp_message_path_mapping(selected_mappings)
            yield from reader.get_data(
                selected_mappings,
                start_time=start_time_ns,
                end_time=end_time_ns,
                timestamp_message_path_representation_mapping=timestamp_mapping,
            )
        else:
            raise NotImplementedError("No compatible reader found for this data. Please reach out to Roboto support.")

    def get_data_as_df(
        self,
        topic_id: str,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir_override: typing.Union[str, pathlib.Path, None] = None,
        representation_selector: RepresentationSelector = RepresentationSelector.raw(),
    ) -> pandas.DataFrame:
        """Fetch a topic's messages as a pandas DataFrame, optionally limited to some message paths and a time range.

        The message paths are filtered as ``get_data`` describes.

        Args:
            topic_id: ID of the topic to read.
            message_paths_include: Message paths to include. ``None`` includes every message path.
            message_paths_exclude: Message paths to leave out. ``None`` leaves out none.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            cache_dir_override: Directory to download Parquet-stored data to for this read. ``None`` uses the
                directory the service was created with.
            representation_selector: Which of the topic's stored representations to read. Defaults to the original
                data, with no transformations.

        Returns:
            A data frame with one row per message, indexed by each message's timestamp: a UTC
            ``pandas.DatetimeIndex`` named ``_index``.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            NotImplementedError: The representations selected for the read are not all stored as MCAP or all as
                Parquet.
        """
        pd = import_optional_dependency("pandas", "analytics")

        message_path_repr_mappings = self.__get_message_path_mappings(topic_id)
        filtered_message_path_repr_mappings = self.__filter_message_path_mappings(
            message_path_repr_mappings,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
        )
        selected_mappings = representation_selector.select_representations(filtered_message_path_repr_mappings)

        start_time_ns = to_epoch_nanoseconds(start_time) if start_time is not None else None
        end_time_ns = to_epoch_nanoseconds(end_time) if end_time is not None else None

        if McapTopicReader.accepts(selected_mappings):
            reader: TopicReader = McapTopicReader(self.__roboto_client)
            timestamps, df = reader.get_data_as_df(
                selected_mappings,
                start_time=start_time_ns,
                end_time=end_time_ns,
            )
        elif ParquetTopicReader.accepts(selected_mappings):
            reader = ParquetTopicReader(self.__roboto_client, cache_dir=self.__resolve_cache_dir(cache_dir_override))
            timestamp_mapping = self.__find_timestamp_message_path_mapping(selected_mappings)
            timestamps, df = reader.get_data_as_df(
                selected_mappings,
                start_time=start_time_ns,
                end_time=end_time_ns,
                timestamp_message_path_representation_mapping=timestamp_mapping,
            )
        else:
            raise NotImplementedError("No compatible reader found for this data. Please reach out to Roboto support.")

        timestamps_as_datetimes = pd.to_datetime(timestamps, unit="ns", utc=True)
        df = df.set_index(timestamps_as_datetimes)
        # Topic.create_from_df() writes the index as a Parquet column, which becomes a message path. Naming it gives
        # that message path a readable name instead of an autogenerated one such as "__index_level_0__". The leading
        # underscore marks it as added by Roboto and avoids a conflict with a column named "index".
        df.index.name = "_index"

        return df

    def __resolve_cache_dir(self, cache_dir_override: typing.Union[str, pathlib.Path, None] = None) -> pathlib.Path:
        # Does not create the directory: the Parquet reader creates it only when it writes a file to it. Creating it
        # here would also create it for reads of MCAP-stored data, which never use it.
        return pathlib.Path(cache_dir_override) if cache_dir_override is not None else self.__cache_dir

    def __filter_message_paths(
        self,
        message_path_records: collections.abc.Iterable[MessagePathRecord],
        include_paths: typing.Optional[collections.abc.Iterable[str]],
        exclude_paths: typing.Optional[collections.abc.Iterable[str]],
    ) -> list[MessagePathRecord]:
        """Return the records that pass the filters.

        A record matches a filter path that equals its ``message_path``, its ``source_path``, or one of its
        :py:meth:`~roboto.domain.topics.MessagePathRecord.parents`. Empty and ``None`` filters both select every
        record.
        """
        if not include_paths and not exclude_paths:
            return list(message_path_records)

        filtered = []
        include_paths_set = iterable_to_set(include_paths) if include_paths is not None else set()
        exclude_paths_set = iterable_to_set(exclude_paths) if exclude_paths is not None else set()

        for record in message_path_records:
            # Keep timestamp message paths whatever the filters say: the Parquet reader reads one to apply start_time
            # and end_time and to give each yielded row its timestamp.
            if record.canonical_data_type == CanonicalDataType.Timestamp:
                filtered.append(record)
                continue

            paths = set(record.parents())
            paths.add(record.source_path)
            paths.add(
                # Can differ from source_path; a filter may name either.
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
        message_path_repr_mappings: collections.abc.Iterable[MessagePathRepresentationMapping],
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
    ) -> list[MessagePathRepresentationMapping]:
        # Drop each mapping the filters leave with no message paths.
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

        # Warn when the filters leave only timestamp paths, which __filter_message_paths always keeps.
        if (message_paths_include or message_paths_exclude) and not any(
            message_path.canonical_data_type != CanonicalDataType.Timestamp
            for message_path_repr_map in message_path_repr_mappings
            for message_path in message_path_repr_map.message_paths
        ):
            logger.warning(
                "The request for topic data selects no message paths other than timestamps, "
                "so its results will hold no other data. "
                "Please check that the 'message_paths_include' and 'message_paths_exclude' parameters "
                "are not filtering out all available message paths for this topic."
            )

        return message_path_repr_mappings

    def __find_timestamp_message_path_mapping(
        self,
        message_path_repr_mappings: collections.abc.Iterable[MessagePathRepresentationMapping],
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
        return message_path_repr_mappings_response.to_record_list(MessagePathRepresentationMapping)
