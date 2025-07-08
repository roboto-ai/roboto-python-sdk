# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from .operations import (
    MessagePathRepresentationMapping,
)
from .record import RepresentationStorageFormat
from .topic_reader import TopicReader

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


class ParquetTopicReader(TopicReader):
    @staticmethod
    def accepts(
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
    ) -> bool:
        for mapping in message_paths_to_representations:
            if (
                mapping.representation.storage_format
                != RepresentationStorageFormat.PARQUET
            ):
                return False
        return True

    def get_data(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        log_time_attr_name: str,
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        raise NotImplementedError(
            "Support for getting data via the Roboto SDK from files ingested as Parquet is coming soon!"
        )

    def get_data_as_df(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
        log_time_attr_name: str,
        start_time: typing.Optional[int] = None,
        end_time: typing.Optional[int] = None,
    ) -> "pandas.DataFrame":
        raise NotImplementedError(
            "Support for getting data via the Roboto SDK from files ingested as Parquet is coming soon!"
        )
