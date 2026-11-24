# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import abc
import collections.abc
import typing

from .record import (
    MessagePathRepresentationMapping,
)

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


Timestamp: typing.TypeAlias = typing.Union[int, float]
"""Time of a topic message, in nanoseconds since the Unix epoch."""


class TopicReader(abc.ABC):
    """Interface for reading topic data stored in one storage format, such as MCAP or Parquet.

    The SDK's own code uses it; to read topic data, use the ``get_data`` or ``get_data_as_df`` method of
    :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`, or
    :py:class:`~roboto.domain.events.Event` instead.

    :py:class:`~roboto.domain.topics.TopicDataService` reads a topic with the first reader whose ``accepts`` returns
    ``True`` for the topic's selected representations.
    """

    @staticmethod
    @abc.abstractmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
    ) -> bool:
        """Return whether this reader can read every mapping's representation.

        Args:
            message_paths_to_representations: Message paths to read, each paired with the representation that
                stores it.
        """
        ...

    @abc.abstractmethod
    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield ``(timestamp, record)`` pairs for the message paths, limited to a time range.

        Args:
            message_paths_to_representations: Message paths to read, each paired with the representation that
                stores it.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the
                range unbounded below.
            end_time: Exclusive end of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
                unbounded above.
            timestamp_message_path_representation_mapping: Mapping whose message paths include the one with
                canonical data type :py:attr:`~roboto.domain.topics.CanonicalDataType.Timestamp`, whose values
                become each record's timestamp. A reader whose storage format records each message's time, as
                MCAP does, ignores it.

        Yields:
            ``(timestamp, record)`` tuples: the timestamp in nanoseconds since the Unix epoch, and a dictionary of
            the record's requested fields.
        """
        ...

    @abc.abstractmethod
    def get_data_as_df(
        self,
        message_paths_to_representations: collections.abc.Iterable[MessagePathRepresentationMapping],
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[MessagePathRepresentationMapping] = None,
    ) -> tuple[pandas.Series, pandas.DataFrame]:
        """Fetch the records ``get_data`` yields, as a series of timestamps and a data frame.

        Args:
            message_paths_to_representations: Message paths to read, as for ``get_data``.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the
                range unbounded below.
            end_time: Exclusive end of the time range, in nanoseconds since the Unix epoch. ``None`` leaves the range
                unbounded above.
            timestamp_message_path_representation_mapping: Mapping that holds the timestamp message path, as for
                ``get_data``.

        Returns:
            ``(timestamps, df)``: the timestamp of each row in nanoseconds since the Unix epoch, and a data frame with
            one row per record.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
        """
        ...
