# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import logging
import typing

from ...association import AssociationType
from ...compat import import_optional_dependency
from ...formats.mcap import McapReader, open_for_window
from ...http import RobotoClient
from ...logging import default_logger
from ...storage import HttpRangeReader, as_io_bytes
from .record import (
    MessagePathRepresentationMapping,
    RepresentationStorageFormat,
)
from .topic_reader import Timestamp, TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


class SignedUrlResolver(typing.Protocol):
    """Callable that turns a file's ID into a signed URL its contents can be downloaded from."""

    def __call__(self, file_id: str) -> str:
        """Return a signed download URL for the file with this ID.

        Args:
            file_id: ID of the file to download, beginning with ``fl_``.
        """
        ...


class RobotoClientUrlResolver:
    """``SignedUrlResolver`` that fetches each URL from Roboto.

    :py:meth:`~roboto.domain.topics.Topic.get_data` fetches MCAP files' signed URLs through it, so most code never
    calls it. ``McapTopicReader`` builds one when it is given a ``roboto_client`` and no ``signed_url_resolver``.
    """

    def __init__(self, roboto_client: RobotoClient):
        self.__roboto_client = roboto_client

    def __call__(self, file_id: str) -> str:
        signed_url_response = self.__roboto_client.get(f"v1/files/{file_id}/signed-url")
        return signed_url_response.to_dict(json_path=["data", "url"])


class McapTopicReader(TopicReader):
    """Reader of topic data stored in MCAP files.

    The SDK's own code uses it; to read topic data, use the ``get_data`` or ``get_data_as_df`` methods
    of :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath` or
    :py:class:`~roboto.domain.events.Event` instead.

    Reads each file with HTTP range requests, so it downloads only the chunks that hold the requested messages
    rather than the whole file.

    Args:
        roboto_client: Client to make requests to Roboto with, to fetch each file's signed URL from
            ``v1/files/{file_id}/signed-url``. Ignored when ``signed_url_resolver`` is given.
        signed_url_resolver: Callable that returns a signed download URL for a file ID. Takes precedence over
            ``roboto_client``.

    Raises:
        ValueError: Neither ``roboto_client`` nor ``signed_url_resolver`` is given.
    """

    __signed_url_resolver: SignedUrlResolver

    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ) -> bool:
        """Return whether every mapping's representation is stored as MCAP, and so whether this reader can read it.

        An empty iterable returns ``True``.
        """
        for mapping in message_paths_to_representations:
            if mapping.representation.storage_format != RepresentationStorageFormat.MCAP:
                return False
        return True

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        signed_url_resolver: typing.Optional[SignedUrlResolver] = None,
    ):
        if signed_url_resolver is not None:
            self.__signed_url_resolver = signed_url_resolver
        elif roboto_client is not None:
            self.__signed_url_resolver = RobotoClientUrlResolver(roboto_client)
        else:
            raise ValueError("Either roboto_client or signed_url_resolver must be provided")

    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
        topic_name: typing.Optional[str] = None,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield ``(log_time, record)`` pairs from the mappings' MCAP files in log-time order.

        Each record merges, from every file whose next message has that log time, that message's fields at the
        requested message paths.

        Args:
            message_paths_to_representations: Message paths to read. Each
                :py:class:`~roboto.domain.topics.MessagePathRepresentationMapping` pairs message paths with the
                representation whose MCAP file stores them. A mapping whose representation does not belong to a file
                is skipped with a logged warning.
            start_time: Inclusive start of the log-time range, in nanoseconds. ``None`` leaves the range unbounded
                below.
            end_time: Exclusive end of the log-time range, in nanoseconds. ``None`` leaves the range unbounded above.
            timestamp_message_path_representation_mapping: Ignored: each record's timestamp is the log time of the
                messages it merges.
            topic_name: Topic whose MCAP channels to read. ``None`` reads every channel.

        Yields:
            ``(log_time, record)`` tuples: the log time in nanoseconds and the merged record.

        Raises:
            RobotoInternalException: ``topic_name`` is given and a file's summary lists no channel on that topic.
                It surfaces on the first iteration.
        """
        http_readers: list[HttpRangeReader] = []
        mcap_readers: list[McapReader] = []

        try:
            for message_path_repr_map in message_paths_to_representations:
                representation = message_path_repr_map.representation
                association = representation.association

                if association.association_type != AssociationType.File:
                    logger.warning(
                        "Unable to get data for message paths %r (not a file association)",
                        [record.message_path for record in message_path_repr_map.message_paths],
                    )
                    continue

                file_id = association.association_id
                signed_url = self.__signed_url_resolver(file_id)

                http_reader = open_for_window(
                    signed_url, start_time=start_time, end_time=end_time, topic_name=topic_name
                )
                http_readers.append(http_reader)

                mcap_reader = McapReader(
                    stream=as_io_bytes(http_reader),
                    fields=[record.to_field_selection() for record in message_path_repr_map.message_paths],
                    start_time=start_time,
                    end_time=end_time,
                    topic_name=topic_name,
                )
                mcap_readers.append(mcap_reader)

            if logger.isEnabledFor(logging.DEBUG):
                for reader in mcap_readers:
                    logger.debug(
                        "Reader will pick %r fields from data",
                        reader.field_paths,
                    )

            while any(reader.has_next for reader in mcap_readers):
                full_record = {}
                log_time = min(reader.next_envelope_timestamp.log_time for reader in mcap_readers)
                for reader in mcap_readers:
                    if reader.next_message_is_time_aligned(log_time):
                        decoded_message = reader.next()
                        if decoded_message is None:
                            continue
                        full_record.update(decoded_message.to_dict())

                yield log_time, full_record

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
        """Fetch this reader's records as a series of log times and a data frame of records.

        The records are the ones ``get_data`` yields.
        Reads every channel of each file. Nested fields become columns with dot-delimited names, such as
        ``pose.position.x``.

        Args:
            message_paths_to_representations: Message paths to read, as for ``get_data``.
            start_time: Inclusive start of the log-time range, in nanoseconds. ``None`` leaves the range unbounded
                below.
            end_time: Exclusive end of the log-time range, in nanoseconds. ``None`` leaves the range unbounded above.
            timestamp_message_path_representation_mapping: Ignored: each row's timestamp is the log time of the
                messages it merges.

        Returns:
            ``(log_times, records)``: the log time of each row in nanoseconds and a data frame with one row per merged
            record.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
        """
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
