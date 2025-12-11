# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ....compat import import_optional_dependency
from ....logging import default_logger
from ..operations import AddMessagePathRequest
from ..record import (
    CanonicalDataType,
    MessagePathMetadataWellKnown,
    MessagePathStatistic,
)
from .parquet_parser import ParquetParser
from .timestamp import TimestampInfo

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


logger = default_logger()


def arrow_type_to_canonical_type(
    arrow_type: "pyarrow.DataType",
) -> CanonicalDataType:
    pa = import_optional_dependency("pyarrow", "ingestion")

    if pa.types.is_boolean(arrow_type):
        return CanonicalDataType.Boolean

    if pa.types.is_integer(arrow_type) or pa.types.is_decimal(arrow_type) or pa.types.is_floating(arrow_type):
        return CanonicalDataType.Number

    if pa.types.is_timestamp(arrow_type) and typing.cast("pyarrow.TimestampType", arrow_type).tz == "UTC":
        return CanonicalDataType.Timestamp

    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return CanonicalDataType.String

    if pa.types.is_dictionary(arrow_type):
        # Interpret a DictionaryArray as "categorical" data.
        # PyArrow's ability to auto-interpret a Parquet column as a DictionaryArray depends on
        # saving the Arrow schema in the Parquet file's FileMetadata.
        # Else, the ingestion action would need to know ahead of time which columns to parse as dictionaries
        # (i.e., via the `read_dictionary` __init__ arg to ParquetFile).
        return CanonicalDataType.Categorical

    if pa.types.is_map(arrow_type) or pa.types.is_struct(arrow_type):
        return CanonicalDataType.Object

    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):
        return CanonicalDataType.Array

    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return CanonicalDataType.Byte

    return CanonicalDataType.Unknown


def sanitize_column_name(field: "pyarrow.Field") -> str:
    return field.name.replace(".", "_")


def compute_numeric_statistics(
    data: typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"],
) -> dict[str, typing.Any]:
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    min_max = pc.min_max(data)
    mean = pc.mean(data)
    # GM(2025-04-20)
    # PyArrow does not implement a true median function.
    # It instead provides `pc.approximate_median`, which uses T-Digest under the hood.
    # That algorithm is optimized for accuracy at the tails of a distribution,
    # trading off for accuracy determining central tendency.
    # The primary knob we have to control is to set the compression parameter, which defaults (in PyArrow) to 100.
    # A higher value forces the algorithm to create and maintain more centroids,
    # which lead to finer-grained summaries and generally higher accuracy.
    # The number of centroids, and thus the memory footprint of the digest,
    # is roughly proportional to the compression value.
    # Higher accuracy comes at the cost of increased resource consumption.
    # Two other factors affect the accuracy:
    #   1. Size of data: larger series should produce more accurate estimates
    #   2. Data distribution: the accuracy is not uniform across all distrubtion shapes
    median = pc.tdigest(
        data,
        # median
        q=0.5,
        # See note above about choice of significantly larger compression value
        # Research by Apache Presto indicates a compression of 500 achieves very low error median approximations.
        # https://github.com/prestodb/presto/issues/12929
        delta=500,
    )
    return {
        MessagePathStatistic.Min.value: min_max["min"].as_py(),
        MessagePathStatistic.Max.value: min_max["max"].as_py(),
        MessagePathStatistic.Mean.value: mean.as_py(),
        MessagePathStatistic.Median.value: median[0].as_py(),
    }


def compute_boolean_statistics(
    data: typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"],
) -> dict[str, typing.Any]:
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    non_null_count = pc.count(data, mode="only_valid").as_py()
    if non_null_count == 0:
        return {"true_count": 0, "false_count": 0}
    true_count = pc.sum(data).as_py()  # True == 1, so sum() is count of True
    false_count = non_null_count - true_count
    return {"true_count": true_count, "false_count": false_count}


def compute_dictionary_metadata(
    column_name: str,
    data: typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"],
    max_dictionary_size: int = 2048,  # bytes (2kB; arbitrarily chosen)
) -> dict[str, typing.Any]:
    pa = import_optional_dependency("pyarrow", "ingestion")

    arr = data.combine_chunks() if isinstance(data, pa.ChunkedArray) else data
    if not isinstance(arr, pa.DictionaryArray):
        return dict()

    dictionary = typing.cast("pyarrow.DictionaryArray", arr).dictionary
    categories = dictionary.to_pylist()

    # Ensure the size of the categories list won't explode the size of the MessagePathRecord
    combined_byte_length = 0
    for category in categories:
        value = category.encode() if isinstance(category, str) else category
        size = len(value) if isinstance(value, collections.abc.Sized) else 0
        combined_byte_length += size

    if combined_byte_length > max_dictionary_size:
        logger.warning(
            "'%s': categories list is larger (%d bytes) than the allowed maximum (%d bytes). "
            "While this column will still be inferred as containing 'categorical' data, "
            "the Roboto Platform will be unable to map the categories to their integer values.",
            column_name,
            combined_byte_length,
            max_dictionary_size,
        )
        return dict()

    return {MessagePathMetadataWellKnown.Categories.value: categories}


def generate_metadata_for_field(
    field: "pyarrow.Field", parquet_parser: ParquetParser, timestamp: TimestampInfo
) -> dict[str, typing.Any]:
    metadata = {MessagePathMetadataWellKnown.ColumnName.value: field.name}

    if field == timestamp.field:
        metadata[MessagePathMetadataWellKnown.Unit.value] = str(timestamp.unit)
        return metadata

    canonical_data_type = arrow_type_to_canonical_type(field.type)
    if canonical_data_type == CanonicalDataType.Number:
        data = parquet_parser.get_data_for_column(field.name).column(0)
        metadata.update(compute_numeric_statistics(data))
        return metadata

    if canonical_data_type == CanonicalDataType.Boolean:
        data = parquet_parser.get_data_for_column(field.name).column(0)
        metadata.update(compute_boolean_statistics(data))
        return metadata

    if canonical_data_type == CanonicalDataType.Categorical:
        data = parquet_parser.get_data_for_column(field.name).column(0)
        metadata.update(compute_dictionary_metadata(field.name, data))
        return metadata

    return metadata


def field_to_message_path_request(
    field: "pyarrow.Field", parquet_file: ParquetParser, timestamp: TimestampInfo
) -> AddMessagePathRequest:
    canonical_data_type = arrow_type_to_canonical_type(field.type)
    if field == timestamp.field:
        canonical_data_type = CanonicalDataType.Timestamp

    metadata = generate_metadata_for_field(field, parquet_file, timestamp)

    return AddMessagePathRequest(
        canonical_data_type=canonical_data_type,
        data_type=str(field.type),
        message_path=sanitize_column_name(field),
        metadata=metadata,
    )
