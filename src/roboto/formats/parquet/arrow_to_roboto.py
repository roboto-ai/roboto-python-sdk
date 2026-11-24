# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...compat import import_optional_dependency
from ...domain.topics.operations import AddMessagePathRequest
from ...domain.topics.record import (
    CanonicalDataType,
    MessagePathMetadataWellKnown,
    MessagePathStatistic,
)
from ...logging import default_logger
from .parquet_parser import ParquetParser
from .timestamp import TimestampInfo

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep


logger = default_logger()


def arrow_type_to_canonical_type(
    arrow_type: "pyarrow.DataType",
) -> CanonicalDataType:
    """Return the :py:class:`~roboto.domain.topics.CanonicalDataType` Roboto gives a Parquet field of ``arrow_type``.

    ``generate_message_path_requests`` gives each field its canonical data type through it, so most code never calls
    it. That function gives the file's timestamp field ``Timestamp`` whatever this returns. Types map as follows:

    - Booleans: ``Boolean``.
    - Integers, decimals and floating-point numbers: ``Number``.
    - Timestamps in UTC: ``Timestamp``. A timestamp in any other time zone, or in none, is ``Unknown``.
    - Strings: ``String``.
    - Dictionary-encoded columns: ``Categorical``.
    - Maps and structs: ``Object``.
    - Lists, of any of pyarrow's three list types: ``NumberArray`` when the elements are integers wider than 8 bits,
      floating-point numbers or decimals, and ``Array`` otherwise. A list of 8-bit integers is ``Array`` because it
      typically holds raw bytes, such as an image or a serialized blob, rather than a signal to plot.
    - Binary values: ``Byte``.
    - Any other type: ``Unknown``.

    Args:
        arrow_type: pyarrow type of the field.
    """
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
        # pyarrow reads a Parquet column as a dictionary only when the file stores its Arrow schema, which pyarrow
        # writes by default. ParquetParser passes ParquetFile no read_dictionary argument to choose such columns itself.
        return CanonicalDataType.Categorical

    if pa.types.is_map(arrow_type) or pa.types.is_struct(arrow_type):
        return CanonicalDataType.Object

    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type) or pa.types.is_fixed_size_list(arrow_type):
        value_type = typing.cast(
            "pyarrow.ListType | pyarrow.LargeListType | pyarrow.FixedSizeListType", arrow_type
        ).value_type
        if pa.types.is_int8(value_type) or pa.types.is_uint8(value_type):
            return CanonicalDataType.Array
        if pa.types.is_integer(value_type) or pa.types.is_floating(value_type) or pa.types.is_decimal(value_type):
            return CanonicalDataType.NumberArray
        return CanonicalDataType.Array

    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return CanonicalDataType.Byte

    return CanonicalDataType.Unknown


def sanitize_column_name(field: "pyarrow.Field") -> str:
    """Return the field's name with each ``.`` replaced by ``_``, the form a message path uses for it.

    A message path separates nested fields with dots, so a dot within a field name would read as nesting.

    Args:
        field: pyarrow field whose name to convert.
    """
    return field.name.replace(".", "_")


def compute_numeric_statistics(
    data: typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"],
) -> dict[str, typing.Any]:
    """Compute the minimum, maximum, mean and approximate median of ``data``, skipping nulls.

    ``generate_message_path_requests`` computes the statistics of ``Number`` and ``NumberArray`` fields through it, so
    most code never calls it.

    Args:
        data: Numeric values of the field.

    Returns:
        The four statistics, keyed by their :py:class:`~roboto.domain.topics.MessagePathStatistic` values (``min``,
        ``max``, ``mean`` and ``median``). Each is ``None`` when ``data`` has no values other than nulls.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    min_max = pc.min_max(data)
    mean = pc.mean(data)
    # pyarrow has no exact median. tdigest estimates one with a t-digest, which is most accurate at the tails of a
    # distribution and less so near its middle; its accuracy also varies with the data's size and shape. delta is the
    # digest's compression: a larger value keeps proportionally more centroids, using more memory for a more accurate
    # estimate. pyarrow defaults it to 100; Presto found that 500 gives a median with very low error.
    median = pc.tdigest(
        data,
        q=0.5,
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
    """Count the true and false values in ``data``, skipping nulls.

    ``generate_message_path_requests`` counts the values of ``Boolean`` fields through it, so most code never calls it.

    Args:
        data: Boolean values of the field.

    Returns:
        ``{"true_count": <count>, "false_count": <count>}``.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    non_null_count = pc.count(data, mode="only_valid").as_py()
    # sum() of no values is null, not 0.
    if non_null_count == 0:
        return {"true_count": 0, "false_count": 0}
    true_count = pc.sum(data).as_py()  # sum() counts each true value as 1
    false_count = non_null_count - true_count
    return {"true_count": true_count, "false_count": false_count}


def compute_dictionary_metadata(
    column_name: str,
    data: typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"],
    max_dictionary_size: int = 2048,
) -> dict[str, typing.Any]:
    """Build the categories metadata of a dictionary-encoded field: its dictionary's values, in order.

    ``generate_message_path_requests`` records the categories of ``Categorical`` fields through it, so most code never
    calls it. The categories let Roboto show each stored integer as the value it stands for.

    Args:
        column_name: Path of the field, used only to name it in the warning logged when its categories are too large.
        data: Values of the field.
        max_dictionary_size: Largest combined size of the categories, in bytes, to record, which keeps the message
            path record small. A string counts its UTF-8 length and a value with no length, such as an integer, counts
            as zero. Larger categories are left out and a warning is logged; the field stays ``Categorical``.

    Returns:
        The categories under the :py:attr:`~roboto.domain.topics.MessagePathMetadataWellKnown.Categories` key, or
        an empty dictionary when ``data`` is not dictionary-encoded or its categories are larger than
        ``max_dictionary_size``.
    """
    pa = import_optional_dependency("pyarrow", "ingestion")

    arr = typing.cast("pyarrow.ChunkedArray", data).combine_chunks() if isinstance(data, pa.ChunkedArray) else data
    if not isinstance(arr, pa.DictionaryArray):
        return dict()

    dictionary = typing.cast("pyarrow.DictionaryArray", arr).dictionary
    categories = dictionary.to_pylist()

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
    """Read the values of a field nested in structs under a top-level column of the Parquet file.

    ``generate_message_path_requests`` reads the values of a field that is not inside a list of structs through it,
    so most code never calls it.

    Args:
        parser: Parser of the Parquet file to read from.
        column_name: Name of the top-level column that holds the field.
        field_path: Names of the struct fields from the column down to the field. Empty reads the column itself.

    Raises:
        IndexError: The file has no column named ``column_name``.
        pyarrow.ArrowInvalid: A name in ``field_path`` matches no field of the struct it is looked up in.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    data = parser.get_data_for_column(column_name).column(0)

    for component in field_path:
        data = pc.struct_field(data, component)

    return data


def get_list_element_data(
    parser: ParquetParser,
    column_name: str,
    field_path: list[str],
) -> typing.Union["pyarrow.Array", "pyarrow.ChunkedArray"]:
    """Read the values of a field inside a top-level list column of the Parquet file, across every list element.

    ``generate_message_path_requests`` reads the values of a field inside a list of structs through it, so most code
    never calls it. The elements of every row's list are joined into one array, so statistics computed from it cover
    all of them.

    Args:
        parser: Parser of the Parquet file to read from.
        column_name: Name of the top-level column, which must be a list.
        field_path: Names of the struct fields from the list's elements down to the field. Empty reads the elements
            themselves.

    Raises:
        IndexError: The file has no column named ``column_name``.
        pyarrow.ArrowNotImplementedError: The column is not a list.
        pyarrow.ArrowInvalid: A name in ``field_path`` matches no field of the struct it is looked up in.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    data = parser.get_data_for_column(column_name).column(0)

    data = pc.list_flatten(data)

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
    """Compute the statistics metadata of one field from its values in the Parquet file.

    ``generate_message_path_requests`` computes the metadata of every field except structs through it, so most code
    never calls it. The field's :py:class:`~roboto.domain.topics.CanonicalDataType` selects the metadata:

    - ``Number`` and ``NumberArray``: minimum, maximum, mean and approximate median, over every element of an array.
    - ``Boolean``: ``true_count`` and ``false_count``.
    - ``Categorical``: the field's categories.
    - Any other type: none.

    When reading the values or computing the statistics raises any exception, logs a warning and returns an empty
    dictionary, so one field's failure leaves the file's other fields with their statistics.

    Args:
        parser: Parser of the Parquet file to read the field's values from.
        column_name: Name of the top-level column that holds the field.
        field_path: Names of the struct fields from the column down to the field, or, inside a list of structs, from
            the list's elements down to the field. Empty for the column itself.
        canonical_data_type: Canonical data type of the field.
        is_inside_list: Whether the field is inside a list of structs, so its values are read across every list
            element.
    """
    pc = import_optional_dependency("pyarrow.compute", "ingestion")

    full_path = ".".join([column_name] + field_path)
    metadata: dict[str, typing.Any] = {}

    types_needing_stats = (
        CanonicalDataType.Number,
        CanonicalDataType.NumberArray,
        CanonicalDataType.Boolean,
        CanonicalDataType.Categorical,
    )
    if canonical_data_type not in types_needing_stats:
        return metadata

    try:
        if is_inside_list:
            data = get_list_element_data(parser, column_name, field_path)
        else:
            data = get_nested_column_data(parser, column_name, field_path)
            if canonical_data_type == CanonicalDataType.NumberArray:
                data = pc.list_flatten(data)

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
    """Yield the message path requests of one field and, within ``max_depth``, of the fields nested in it.

    Args:
        field: pyarrow field to describe.
        path_prefix: Message path of the field's parent, with dots in its names replaced. Empty for a top-level
            column.
        field_path: Unchanged names of the struct fields from ``column_name`` down to this field, which locate its
            values for ``compute_field_metadata``.
        column_name: Name of the top-level column that holds the field.
        parser: Parser of the Parquet file the field belongs to.
        timestamp: Timestamp field of the file and its unit.
        depth: Number of levels this field is below its top-level column.
        max_depth: Deepest level, counted as ``depth`` is, that gets message paths.
        is_inside_list: Whether the field is inside a list of structs.
    """
    pa = import_optional_dependency("pyarrow", "ingestion")

    # A message path separates nested fields with dots, so a dot within a field name becomes an underscore.
    field_name_sanitized = field.name.replace(".", "_")
    message_path = f"{path_prefix}.{field_name_sanitized}" if path_prefix else field_name_sanitized

    arrow_type = field.type
    canonical_data_type = arrow_type_to_canonical_type(arrow_type)

    # The file's timestamp field may be numeric or a timestamp outside UTC, which would map to another type.
    if field == timestamp.field:
        canonical_data_type = CanonicalDataType.Timestamp

    # The field's unchanged names from the top-level column down, sent as path_in_schema on every request.
    full_field_path = [column_name] + field_path

    # A struct and a list of structs both get a message path for each field of a struct. Each branch below sets
    # which struct that is and whether its fields are inside a list; the recursion after the branches serves both.
    struct_children: typing.Optional["pyarrow.StructType"] = None
    children_inside_list = is_inside_list

    if pa.types.is_struct(arrow_type):
        # The struct itself is an Object with no statistics.
        yield AddMessagePathRequest(
            canonical_data_type=CanonicalDataType.Object,
            data_type=str(arrow_type),
            message_path=message_path,
            metadata={},
            path_in_schema=full_field_path,
        )
        struct_children = typing.cast("pyarrow.StructType", arrow_type)
    elif pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type) or pa.types.is_fixed_size_list(arrow_type):
        value_type = typing.cast(
            "pyarrow.ListType | pyarrow.LargeListType | pyarrow.FixedSizeListType", arrow_type
        ).value_type

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

        if pa.types.is_struct(value_type):
            struct_children = typing.cast("pyarrow.StructType", value_type)
            children_inside_list = True
    else:
        metadata = compute_field_metadata(
            parser=parser,
            column_name=column_name,
            field_path=field_path,
            canonical_data_type=canonical_data_type,
            is_inside_list=is_inside_list,
        )
        if field == timestamp.field:
            metadata[MessagePathMetadataWellKnown.Unit.value] = str(timestamp.unit)
        yield AddMessagePathRequest(
            canonical_data_type=canonical_data_type,
            data_type=str(arrow_type),
            message_path=message_path,
            metadata=metadata,
            path_in_schema=full_field_path,
        )
        return

    # A list of anything but structs has no fields of its own.
    if struct_children is None:
        return

    if depth < max_depth:
        for i in range(struct_children.num_fields):
            child_field = struct_children.field(i)
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
                is_inside_list=children_inside_list,
            )
    else:
        logger.warning(
            "'%s' has nested data beyond the maximum supported depth (%d). "
            "Its child fields will not be individually searchable or plottable, "
            "and will instead appear as a raw nested object.",
            message_path,
            max_depth,
        )


def generate_message_path_requests(
    parser: ParquetParser,
    timestamp: TimestampInfo,
    max_depth: int = 10,
) -> typing.Generator[AddMessagePathRequest, None, None]:
    """Yield an :py:class:`~roboto.domain.topics.AddMessagePathRequest` for every field of a Parquet file.

    :py:meth:`~roboto.domain.topics.Topic.create_from_df` passes the requests to
    :py:meth:`~roboto.domain.topics.Topic.create` as the new topic's message paths. Each request carries:

    - A message path that joins the field's name to the names of the fields it is nested in, with dots. A dot within
      a name becomes an underscore; ``path_in_schema`` keeps the names unchanged.
    - The :py:class:`~roboto.domain.topics.CanonicalDataType` that ``arrow_type_to_canonical_type`` gives the field's
      type. The file's timestamp field is always ``Timestamp`` and records its unit under the
      :py:attr:`~roboto.domain.topics.MessagePathMetadataWellKnown.Unit` metadata key.
    - Statistics for numeric and boolean fields and categories for categorical ones, as ``compute_field_metadata``
      computes them. A field whose statistics cannot be computed gets none, and a warning is logged.

    A struct yields an ``Object`` message path and then one for each of its fields. A list of structs yields a message
    path for the list and then one for each struct field, whose statistics cover that field's values in every list
    element. For example:

    - ``position: struct<x: double, y: double>`` yields ``position`` (``Object``), then ``position.x`` and
      ``position.y`` (``Number``).
    - ``values: list<double>`` yields ``values`` (``NumberArray``).
    - ``points: list<struct<x: double, y: double>>`` yields ``points`` (``Array``), then ``points.x`` and
      ``points.y`` (``Number``).

    Args:
        parser: Parser of the Parquet file to describe, which the statistics are computed from.
        timestamp: Timestamp field of the file and its unit, from
            :py:meth:`~roboto.formats.parquet.ParquetParser.extract_timestamp_info`.
        max_depth: Number of levels below a top-level column that get message paths. A struct or list of structs at
            the deepest level gets a message path, but its fields do not, and a warning is logged.

    Examples:
        >>> import pathlib
        >>> from roboto.formats.parquet import ParquetParser, generate_message_path_requests
        >>> parser = ParquetParser(pathlib.Path("sensor_data.parquet"))
        >>> timestamp = parser.extract_timestamp_info("timestamp")
        >>> for request in generate_message_path_requests(parser, timestamp):
        ...     print(request.message_path, request.canonical_data_type)
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
