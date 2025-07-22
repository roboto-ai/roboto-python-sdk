# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import collections.abc
import typing

from ...time import TimeUnit
from .operations import (
    MessagePathRepresentationMapping,
)

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


class TopicReader(abc.ABC):
    """Private interface for retrieving topic data of a particular format.

    Note:
        This is not intended as a public API.
        To access topic data, prefer the ``get_data`` or ``get_data_as_df`` methods
        on :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`,
        or :py:class:`~roboto.domain.events.Event`.
    """

    @staticmethod
    @abc.abstractmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
    ) -> bool: ...

    @abc.abstractmethod
    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        log_time_attr_name: str,
        log_time_unit: TimeUnit = TimeUnit.Nanoseconds,
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[
            MessagePathRepresentationMapping
        ] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]: ...

    @abc.abstractmethod
    def get_data_as_df(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        log_time_attr_name: str,
        log_time_unit: TimeUnit = TimeUnit.Nanoseconds,
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
        timestamp_message_path_representation_mapping: typing.Optional[
            MessagePathRepresentationMapping
        ] = None,
    ) -> "pandas.DataFrame": ...
