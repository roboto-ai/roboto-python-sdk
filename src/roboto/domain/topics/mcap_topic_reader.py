# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import logging
import typing

import mcap.reader

from ...association import AssociationType
from ...compat import import_optional_dependency
from ...http import RobotoClient
from ...logging import default_logger
from .http_range_reader import HttpRangeReader, as_io_bytes
from .mcap_reader import McapReader
from .operations import (
    MessagePathRepresentationMapping,
)
from .record import (
    RepresentationStorageFormat,
)
from .topic_reader import Timestamp, TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


class McapTopicReader(TopicReader):
    """Private interface for retrieving topic data stored in MCAP files.

    Uses HTTP Range requests to efficiently fetch only required chunks from remote
    storage, avoiding full file downloads.

    Note:
        This is not intended as a public API.
        To access topic data, prefer the ``get_data`` or ``get_data_as_df`` methods
        on :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`,
        or :py:class:`~roboto.domain.events.Event`.
    """

    __roboto_client: RobotoClient

    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ) -> bool:
        for mapping in message_paths_to_representations:
            if mapping.representation.storage_format != RepresentationStorageFormat.MCAP:
                return False
        return True

    def __init__(self, roboto_client: RobotoClient):
        """Initialize the MCAP topic reader.

        Args:
            roboto_client: Client for making Roboto API requests.
        """
        self.__roboto_client = roboto_client

    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        # Convert to list to allow multiple iterations
        mappings_list = list(message_paths_to_representations)

        http_readers: list[HttpRangeReader] = []
        mcap_readers: list[McapReader] = []

        try:
            for message_path_repr_map in mappings_list:
                representation = message_path_repr_map.representation
                association = representation.association

                if association.association_type != AssociationType.File:
                    logger.warning(
                        "Unable to get data for message paths %r (not a file association)",
                        [record.message_path for record in message_path_repr_map.message_paths],
                    )
                    continue

                file_id = association.association_id
                signed_url_response = self.__roboto_client.get(f"v1/files/{file_id}/signed-url")
                signed_url = signed_url_response.to_dict(json_path=["data", "url"])

                http_reader = HttpRangeReader(signed_url)
                http_readers.append(http_reader)

                # Phase 1: Read summary to get chunk index (this fetches footer + summary)
                seeking_reader = mcap.reader.SeekingReader(as_io_bytes(http_reader))
                summary = seeking_reader.get_summary()

                # Phase 2: Identify chunks needed for the time range and prefetch them
                if summary and summary.chunk_indexes:
                    fetch_start: int | None = None
                    fetch_end: int | None = None
                    chunk_count = 0

                    for chunk_index in summary.chunk_indexes:
                        chunk_start_time = chunk_index.message_start_time
                        chunk_end_time = chunk_index.message_end_time

                        # Skip chunks outside the time range
                        if start_time is not None and chunk_end_time < start_time:
                            continue
                        if end_time is not None and chunk_start_time > end_time:
                            continue

                        chunk_start = chunk_index.chunk_start_offset
                        chunk_end = chunk_start + chunk_index.chunk_length - 1
                        chunk_count += 1

                        if fetch_start is None or chunk_start < fetch_start:
                            fetch_start = chunk_start
                        if fetch_end is None or chunk_end > fetch_end:
                            fetch_end = chunk_end

                    # Prefetch the byte range
                    if fetch_start is not None and fetch_end is not None:
                        total_bytes = fetch_end - fetch_start + 1
                        logger.info(
                            "Prefetching %d chunks, %.1f MB for file %s (time range: %s - %s)",
                            chunk_count,
                            total_bytes / 1024 / 1024,
                            file_id,
                            start_time,
                            end_time,
                        )
                        http_reader.prefetch_range(fetch_start, fetch_end)

                # Phase 3: Reset reader position and create McapReader for iteration
                http_reader.seek(0)
                mcap_reader = McapReader(
                    stream=as_io_bytes(http_reader),
                    message_paths=message_path_repr_map.message_paths,
                    start_time=start_time,
                    end_time=end_time,
                )
                mcap_readers.append(mcap_reader)

            if logger.isEnabledFor(logging.DEBUG):
                for reader in mcap_readers:
                    logger.debug(
                        "Reader will pick %r message_paths from data",
                        reader.message_paths,
                    )

            while any(reader.has_next for reader in mcap_readers):
                full_record = {}
                timestamp = min(reader.next_timestamp for reader in mcap_readers)
                for reader in mcap_readers:
                    if reader.next_message_is_time_aligned(timestamp):
                        decoded_message = reader.next()
                        if decoded_message is None:
                            continue
                        full_record.update(decoded_message.to_dict())

                yield timestamp, full_record

        finally:
            for http_reader in http_readers:
                http_reader.close()

    def get_data_as_df(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
    ) -> tuple[pandas.Series, pandas.DataFrame]:
        pd = import_optional_dependency("pandas", "analytics")
        timestamps = []
        data = []
        for timestamp, record in self.get_data(
            message_paths_to_representations=message_paths_to_representations,
            start_time=start_time,
            end_time=end_time,
        ):
            timestamps.append(timestamp)
            data.append(record)

        return pd.Series(timestamps), pd.json_normalize(data=data)
