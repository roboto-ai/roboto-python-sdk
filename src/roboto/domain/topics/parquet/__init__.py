# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Support for topic data stored as Parquet files: reading it, and uploading it for a new topic.

:py:meth:`~roboto.domain.topics.Topic.get_data` and :py:meth:`~roboto.domain.topics.Topic.get_data_as_df` read
Parquet-backed topics through it, and :py:meth:`~roboto.domain.topics.Topic.create_from_df` stores a DataFrame as a
topic through it, so most code never calls it.
"""

from ....formats.parquet import (
    ParquetParser,
    generate_message_path_requests,
)
from .ingestion import (
    make_topic_filename_safe,
    upload_representation_file,
)
from .parquet_topic_reader import (
    ParquetTopicReader,
)

__all__ = (
    "generate_message_path_requests",
    "make_topic_filename_safe",
    "ParquetParser",
    "ParquetTopicReader",
    "upload_representation_file",
)
