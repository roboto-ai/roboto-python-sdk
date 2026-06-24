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
    """Resolves a file ID to a signed download URL."""

    def __call__(self, file_id: str) -> str: ...


class RobotoClientUrlResolver:
    """A :class:`SignedUrlResolver` that fetches signed URLs via the Roboto API."""

    def __init__(self, roboto_client: RobotoClient):
        self.__roboto_client = roboto_client

    def __call__(self, file_id: str) -> str:
        signed_url_response = self.__roboto_client.get(f"v1/files/{file_id}/signed-url")
        return signed_url_response.to_dict(json_path=["data", "url"])


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

    __signed_url_resolver: SignedUrlResolver

    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ) -> bool:
        for mapping in message_paths_to_representations:
            if mapping.representation.storage_format != RepresentationStorageFormat.MCAP:
                return False
        return True

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        signed_url_resolver: typing.Optional[SignedUrlResolver] = None,
    ):
        """Initialize the MCAP topic reader.

        Provide either a ``roboto_client`` (which will fetch signed URLs via the Roboto API)
        or a ``signed_url_resolver`` that maps file IDs to signed download URLs directly.

        Args:
            roboto_client: Client for making Roboto API requests. Used to resolve signed URLs
                via the ``v1/files/{file_id}/signed-url`` endpoint.
            signed_url_resolver: A :class:`SignedUrlResolver` that returns a signed download URL
                for a given file ID. Takes precedence over ``roboto_client``.
        """
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
                signed_url = self.__signed_url_resolver(file_id)

                http_reader = open_for_window(signed_url, start_time=start_time, end_time=end_time)
                http_readers.append(http_reader)

                mcap_reader = McapReader(
                    stream=as_io_bytes(http_reader),
                    fields=[record.to_field_selection() for record in message_path_repr_map.message_paths],
                    start_time=start_time,
                    end_time=end_time,
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
