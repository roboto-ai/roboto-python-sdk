# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ....association import AssociationType
from ....compat import import_optional_dependency
from ....http import RobotoClient
from ....logging import default_logger
from ....time import TimeUnit
from ..operations import (
    MessagePathRepresentationMapping,
)
from ..record import (
    CanonicalDataType,
    MessagePathRecord,
    RepresentationRecord,
    RepresentationStorageFormat,
)
from ..topic_reader import TopicReader
from .table_transforms import (
    drop_column,
    enrich_with_logtime_ns,
    extract_timestamp_field,
    filter_table_by_logtime_ns,
    scale_logtime,
    should_read_row_group,
)

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep
    import pyarrow  # pants: no-infer-dep
    import pyarrow.parquet  # pants: no-infer-dep


logger = default_logger()


class ParquetTopicReader(TopicReader):
    """Private interface for retrieving topic data stored in Parquet files.

    Note:
        This is not intended as a public API.
        To access topic data, prefer the ``get_data`` or ``get_data_as_df`` methods
        on :py:class:`~roboto.domain.topics.Topic`, :py:class:`~roboto.domain.topics.MessagePath`,
        or :py:class:`~roboto.domain.events.Event`.
    """

    __roboto_client: RobotoClient

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

    def __init__(self, roboto_client: RobotoClient):
        self.__roboto_client = roboto_client

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
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        if timestamp_message_path_representation_mapping is None:
            raise NotImplementedError(
                "Reading data from a Parquet file requires one column to be marked as a 'CanonicalDataType.Timestamp'. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support."
            )

        self.__ensure_single_parquet_file_per_topic(
            [
                *message_paths_to_representations,
                timestamp_message_path_representation_mapping,
            ]
        )

        mapping = next(iter(message_paths_to_representations), None)
        if mapping is None:
            return

        parquet_file = self.__representation_record_to_parquet_file(
            mapping.representation
        )
        timestamp_message_path = self.__timestamp_message_path(
            timestamp_message_path_representation_mapping
        )
        timestamp = extract_timestamp_field(
            parquet_file.schema_arrow, timestamp_message_path
        )

        columns = [
            # Always use `MessagePathRecord::source_path`,
            # which may be different from  `MessagePathRecord::message_path` if character substitutions were applied.
            mp.source_path
            for mp in mapping.message_paths
        ]

        # Even if the timestamp column wasn't requested in the column projection list,
        # request the data to enable timestamp filtering
        # and also to include log_time in the yielded dictionaries
        include_timestamp_message_path = timestamp_message_path.source_path in columns
        if not include_timestamp_message_path:
            columns.append(timestamp_message_path.source_path)

        for row_group_idx in range(parquet_file.metadata.num_row_groups):
            row_group_metadata = parquet_file.metadata.row_group(row_group_idx)
            if not should_read_row_group(
                row_group_metadata,
                timestamp,
                start_time,
                end_time,
            ):
                continue

            row_group_table = parquet_file.read_row_group(
                row_group_idx,
                columns=columns,
            )
            row_group_table = enrich_with_logtime_ns(
                row_group_table, log_time_attr_name, timestamp
            )

            if not include_timestamp_message_path:
                # The timestamp column was not included in the column projection list.
                row_group_table = drop_column(
                    row_group_table,
                    timestamp.field.name,
                )

            row_group_table = filter_table_by_logtime_ns(
                row_group_table,
                log_time_attr_name,
                start_time,
                end_time,
            )

            row_group_table = scale_logtime(
                row_group_table, log_time_attr_name, log_time_unit
            )

            for row in row_group_table.to_pylist():
                yield row

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
    ) -> "pandas.DataFrame":
        pd = import_optional_dependency("pandas", "analytics")
        pa = import_optional_dependency("pyarrow", "analytics")

        if timestamp_message_path_representation_mapping is None:
            raise NotImplementedError(
                "Reading data from a Parquet file requires one column to be marked as a 'CanonicalDataType.Timestamp'. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support."
            )

        self.__ensure_single_parquet_file_per_topic(
            [
                *message_paths_to_representations,
                timestamp_message_path_representation_mapping,
            ]
        )

        mapping = next(iter(message_paths_to_representations), None)
        if mapping is None:
            return pd.DataFrame()

        parquet_file = self.__representation_record_to_parquet_file(
            mapping.representation
        )
        timestamp_message_path = self.__timestamp_message_path(
            timestamp_message_path_representation_mapping
        )
        timestamp = extract_timestamp_field(
            parquet_file.schema_arrow, timestamp_message_path
        )

        tables = []
        columns = [
            # Always use `MessagePathRecord::source_path`,
            # which may be different from  `MessagePathRecord::message_path` if character substitutions were applied.
            mp.source_path
            for mp in mapping.message_paths
        ]

        # Even if the timestamp column wasn't requested in the column projection list,
        # request the data to enable timestamp filtering
        # and also to set the index of the dataframe appropriately
        include_timestamp_message_path = timestamp_message_path.source_path in columns
        if not include_timestamp_message_path:
            columns.append(timestamp_message_path.source_path)

        for row_group_idx in range(parquet_file.metadata.num_row_groups):
            row_group_metadata = parquet_file.metadata.row_group(row_group_idx)
            if not should_read_row_group(
                row_group_metadata,
                timestamp,
                start_time,
                end_time,
            ):
                continue

            row_group_table = parquet_file.read_row_group(
                row_group_idx,
                columns=columns,
            )

            row_group_table = enrich_with_logtime_ns(
                row_group_table, log_time_attr_name, timestamp
            )

            if not include_timestamp_message_path:
                # The timestamp column was not included in the column projection list.
                row_group_table = drop_column(
                    row_group_table,
                    timestamp.field.name,
                )

            row_group_table = filter_table_by_logtime_ns(
                row_group_table,
                log_time_attr_name,
                start_time,
                end_time,
            )

            row_group_table = scale_logtime(
                row_group_table, log_time_attr_name, log_time_unit
            )

            tables.append(row_group_table)

        if not tables:
            return pd.DataFrame()

        concatenated: "pyarrow.Table" = pa.concat_tables(tables)
        return concatenated.to_pandas()

    def __ensure_single_parquet_file_per_topic(
        self,
        message_paths_to_representations: collections.abc.Iterable[
            MessagePathRepresentationMapping
        ],
    ):
        """
        Support pulling data out of a single Parquet file per Topic.
        This is a non-essential limitation; it is done for expediency of initial implementation.
        This class can and should be extended to support splitting a Topic's MessagePaths
        across multiple underlying files.
        """
        repr_ids = {
            mapping.representation.representation_id
            for mapping in message_paths_to_representations
        }
        if len(repr_ids) > 1:
            raise NotImplementedError(
                "Support for reading data for topics whose data is split across multiple Parquet files  "
                "is not yet implemented. "
                "This is likely an issue with data ingestion. Please reach out to Roboto support."
            )

    def __get_signed_url_for_representation_file(
        self, representation: RepresentationRecord
    ) -> str:
        association = representation.association
        if association.association_type != AssociationType.File:
            raise NotImplementedError(
                "Unable to get topic data. "
                "Expected the data to be stored in a Parquet file, "
                f"but received a pointer to a '{association.association_type.value}' instead. "
                "This is likely a problem with data ingestion. Please reach out to Roboto support."
            )
        file_id = representation.association.association_id
        logger.debug("Getting signed url for file '%s'", file_id)
        signed_url_response = self.__roboto_client.get(f"v1/files/{file_id}/signed-url")
        return signed_url_response.to_dict(json_path=["data", "url"])

    def __representation_record_to_parquet_file(
        self, representation: RepresentationRecord
    ) -> "pyarrow.parquet.ParquetFile":
        fs = import_optional_dependency("pyarrow.fs", "analytics")
        fsspec_http = import_optional_dependency(
            "fsspec.implementations.http", "analytics"
        )
        pq = import_optional_dependency("pyarrow.parquet", "analytics")

        http_fs = fsspec_http.HTTPFileSystem()
        signed_url = self.__get_signed_url_for_representation_file(representation)
        return pq.ParquetFile(
            signed_url, filesystem=fs.PyFileSystem(fs.FSSpecHandler(http_fs))
        )

    def __timestamp_message_path(
        self, message_path_representation_mapping: MessagePathRepresentationMapping
    ) -> MessagePathRecord:
        for message_path in message_path_representation_mapping.message_paths:
            if message_path.canonical_data_type != CanonicalDataType.Timestamp:
                continue

            return message_path

        raise Exception(
            "Could not determine timestamp for topic ingested as Parquet. "
            "This is likely a problem with data ingestion. Please reach out to Roboto support."
        )
