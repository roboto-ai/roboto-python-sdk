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
        value_type = typing.cast("pyarrow.ListType", arrow_type).value_type
        # list<numeric> -> NumberArray, list<non-numeric> or list<struct> -> Array
        if pa.types.is_integer(value_type) or pa.types.is_floating(value_type) or pa.types.is_decimal(value_type):
            return CanonicalDataType.NumberArray
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

    arr = typing.cast("pyarrow.ChunkedArray", data).combine_chunks() if isinstance(data, pa.ChunkedArray) else data
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


def get_nested_column_data(
    parser: ParquetParser,
    column_name: str,
    field_path: list[str],
) -> typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"]:
    """Extract data for nested fields from a PyArrow table.

    Navigates through struct fields using the provided field path to extract
    the data for a nested field.

    Args:
        parser: ParquetParser instance to read data from.
        column_name: Name of the top-level column.
        field_path: List of field names to traverse (excluding the column name).

    Returns:
        The extracted Array or ChunkedArray for the nested field.

    Raises:
        KeyError: If a field in the path does not exist.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    data = parser.get_data_for_column(column_name).column(0)

    for component in field_path:
        # Use pc.struct_field to extract nested struct fields from ChunkedArray
        data = pc.struct_field(data, component)

    return data


def get_list_element_data(
    parser: ParquetParser,
    column_name: str,
    field_path: list[str],
) -> typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"]:
    """Extract flattened data from list columns for statistics computation.

    For list<primitive> columns, flattens all list elements into a single array.
    For list<struct> columns, flattens and then accesses the struct field.

    Args:
        parser: ParquetParser instance to read data from.
        column_name: Name of the top-level column.
        field_path: List of field names to traverse after flattening the list.

    Returns:
        The flattened Array or ChunkedArray suitable for statistics computation.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    data = parser.get_data_for_column(column_name).column(0)

    # Flatten the list to get all elements
    data = pc.list_flatten(data)

    # If there are field path components, navigate into struct fields
    for component in field_path:
        data = pc.struct_field(data, component)

    return data


def compute_field_metadata(
    parser: ParquetParser,
    column_name: str,
    field_path: list[str],
    canonical_data_type: CanonicalDataType,
    is_inside_list: bool = False,
) -> dict[str, typing.Any]:
    """Compute metadata including statistics for a field.

    Handles both top-level and nested fields, extracting data appropriately
    based on the field's location in the schema hierarchy.

    Args:
        parser: ParquetParser instance to read data from.
        column_name: Name of the top-level column.
        field_path: List of field names to traverse (empty for top-level fields).
        canonical_data_type: The canonical type of the field.
        is_inside_list: Whether this field is inside a list (affects data extraction).

    Returns:
        Metadata dictionary with statistics if applicable.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    full_path = ".".join([column_name] + field_path)
    metadata: dict[str, typing.Any] = {}

    # Determine which types need data extraction for statistics
    types_needing_stats = (
        CanonicalDataType.Number,
        CanonicalDataType.NumberArray,
        CanonicalDataType.Boolean,
        CanonicalDataType.Categorical,
    )
    if canonical_data_type not in types_needing_stats:
        return metadata

    try:
        # Extract data based on field location
        if is_inside_list:
            # Field inside a list<struct> - flatten and extract
            data = get_list_element_data(parser, column_name, field_path)
        else:
            data = get_nested_column_data(parser, column_name, field_path)
            if canonical_data_type == CanonicalDataType.NumberArray:
                data = pc.list_flatten(data)

        # Compute type-specific statistics
        if canonical_data_type in (CanonicalDataType.Number, CanonicalDataType.NumberArray):
            metadata.update(compute_numeric_statistics(data))
        elif canonical_data_type == CanonicalDataType.Boolean:
            metadata.update(compute_boolean_statistics(data))
        elif canonical_data_type == CanonicalDataType.Categorical:
            metadata.update(compute_dictionary_metadata(full_path, data))

    except Exception as e:
        logger.warning(
            "Failed to compute statistics for nested field '%s': %s",
            full_path,
            str(e),
        )

    return metadata


def _traverse_field(
    field: "pyarrow.Field",
    path_prefix: str,
    field_path: list[str],
    column_name: str,
    parser: ParquetParser,
    timestamp: TimestampInfo,
    depth: int,
    max_depth: int,
    is_inside_list: bool,
) -> typing.Generator[AddMessagePathRequest, None, None]:
    """Recursively traverse a field and yield AddMessagePathRequest objects.

    Args:
        field: The PyArrow field to traverse.
        path_prefix: The dot-delimited path prefix for this field.
        field_path: List of field names from the column to this field (for data extraction).
        column_name: The top-level column name (for data extraction).
        parser: ParquetParser instance.
        timestamp: Timestamp information.
        depth: Current recursion depth.
        max_depth: Maximum recursion depth.
        is_inside_list: Whether we are inside a list type (affects child type mapping).

    Yields:
        AddMessagePathRequest objects for this field and its children.
    """
    pa = import_optional_dependency("pyarrow", "ingestion")

    # Build the message path for this field
    field_name_sanitized = field.name.replace(".", "_")
    message_path = f"{path_prefix}.{field_name_sanitized}" if path_prefix else field_name_sanitized

    # Determine canonical type
    arrow_type = field.type
    canonical_data_type = arrow_type_to_canonical_type(arrow_type)

    # Special handling for timestamp field
    if field == timestamp.field:
        canonical_data_type = CanonicalDataType.Timestamp

    # For fields inside a list<struct>, numeric types stay as Number (not NumberArray)
    # because the list parent already indicates the array nature

    # Build path_in_schema for this field
    full_field_path = [column_name] + field_path

    # Handle struct types - yield parent as Object, then recurse into children
    if pa.types.is_struct(arrow_type):
        yield AddMessagePathRequest(
            canonical_data_type=CanonicalDataType.Object,
            data_type=str(arrow_type),
            message_path=message_path,
            metadata={},
            path_in_schema=full_field_path,
        )

        # Recurse into struct fields if within depth limit
        if depth < max_depth:
            struct_type = typing.cast("pyarrow.StructType", arrow_type)
            for i in range(struct_type.num_fields):
                child_field = struct_type.field(i)
                child_field_path = field_path + [child_field.name]
                yield from _traverse_field(
                    field=child_field,
                    path_prefix=message_path,
                    field_path=child_field_path,
                    column_name=column_name,
                    parser=parser,
                    timestamp=timestamp,
                    depth=depth + 1,
                    max_depth=max_depth,
                    is_inside_list=is_inside_list,
                )
        else:
            logger.warning(
                "'%s' has nested data beyond the maximum supported depth (%d). "
                "Its child fields will not be individually searchable or plottable, "
                "and will instead appear as a raw nested object.",
                message_path,
                max_depth,
            )
        return

    # Handle list types
    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):
        value_type = typing.cast("pyarrow.ListType", arrow_type).value_type

        # Yield the list field itself
        metadata = compute_field_metadata(
            parser=parser,
            column_name=column_name,
            field_path=field_path,
            canonical_data_type=canonical_data_type,
            is_inside_list=is_inside_list,
        )
        yield AddMessagePathRequest(
            canonical_data_type=canonical_data_type,
            data_type=str(arrow_type),
            message_path=message_path,
            metadata=metadata,
            path_in_schema=full_field_path,
        )

        # For list<struct>, recurse into struct fields
        if pa.types.is_struct(value_type):
            if depth < max_depth:
                struct_type = typing.cast("pyarrow.StructType", value_type)
                for i in range(struct_type.num_fields):
                    child_field = struct_type.field(i)
                    child_field_path = field_path + [child_field.name]
                    yield from _traverse_field(
                        field=child_field,
                        path_prefix=message_path,
                        field_path=child_field_path,
                        column_name=column_name,
                        parser=parser,
                        timestamp=timestamp,
                        depth=depth + 1,
                        max_depth=max_depth,
                        is_inside_list=True,  # Mark that we're inside a list
                    )
            else:
                logger.warning(
                    "'%s' has nested data beyond the maximum supported depth (%d). "
                    "Its child fields will not be individually searchable or plottable, "
                    "and will instead appear as a raw nested object.",
                    message_path,
                    max_depth,
                )
        return

    metadata = compute_field_metadata(
        parser=parser,
        column_name=column_name,
        field_path=field_path,
        canonical_data_type=canonical_data_type,
        is_inside_list=is_inside_list,
    )

    # Special handling for timestamp field metadata
    if field == timestamp.field:
        metadata[MessagePathMetadataWellKnown.Unit.value] = str(timestamp.unit)

    yield AddMessagePathRequest(
        canonical_data_type=canonical_data_type,
        data_type=str(arrow_type),
        message_path=message_path,
        metadata=metadata,
        path_in_schema=full_field_path,
    )


def generate_message_path_requests(
    parser: ParquetParser,
    timestamp: TimestampInfo,
    max_depth: int = 10,
) -> typing.Generator[AddMessagePathRequest, None, None]:
    """Generate AddMessagePathRequest objects for all fields in a Parquet schema.

    Traverses the schema recursively to generate message paths for nested types
    (structs, lists) in addition to top-level fields.

    Args:
        parser: ParquetParser instance containing the schema and data.
        timestamp: Timestamp information for the topic.
        max_depth: Maximum recursion depth for nested types (default: 10).

    Yields:
        AddMessagePathRequest objects for each field and nested field in the schema.

    Examples:
        For a schema with a struct column `position: struct<x: float, y: float>`:
        - Yields `position` (Object)
        - Yields `position.x` (Number)
        - Yields `position.y` (Number)

        For a schema with `values: list<float64>`:
        - Yields `values` (NumberArray)

        For a schema with `points: list<struct<x: float, y: float>>`:
        - Yields `points` (Array)
        - Yields `points.x` (Number)
        - Yields `points.y` (Number)
    """
    for field in parser.fields:
        yield from _traverse_field(
            field=field,
            path_prefix="",
            field_path=[],
            column_name=field.name,
            parser=parser,
            timestamp=timestamp,
            depth=0,
            max_depth=max_depth,
            is_inside_list=False,
        )
