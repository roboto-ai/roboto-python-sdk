# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing

from ....compat import import_optional_dependency
from ....domain.topics.record import FieldPath
from ....exceptions import (
    ReadPlanExecutionErrorKind,
    RobotoInternalException,
    RobotoReadPlanExecutionException,
)
from ....storage import HttpRangeReader
from ..batch_transforms import (
    ROW_NUMBER_FIELD_NAME,
    TIMESTAMP_FIELD_NAME,
    row_number_column_index,
    timestamp_column_index,
)
from ..read_plan import ReadPlanPartition, TimeWindow
from .common import (
    FileDecodeParams,
    FileDecoder,
    ScanTaskGroup,
    SuppliedField,
)
from .timestamp_unit import plan_timestamp_unit

if typing.TYPE_CHECKING:
    import mcap_codec
    import pyarrow  # pants: no-infer-dep


class McapFileDecoder(FileDecoder):
    """Decoder that reads one MCAP file of a partition through a cursor of the ``mcap_codec`` package.

    ``make_file_decoder_opener`` builds one for each MCAP file a read takes.

    The cursor reads the channel on the group's topic, or the file's only channel when the group names no topic. It
    reads the fields the group supplies, keeps only the rows at the positions of the partition's ``data_range`` when it
    has one, adds the partition's ``time_offset_ns`` to each timestamp, and keeps the rows in the window.

    Opening the decoder reads the file's summary. The first batch then waits until every chunk that holds the topic's
    messages is downloaded; for a log-time timestamp, only the chunks whose log times can fall in the window.

    Iterating ``batches`` raises :py:class:`~roboto.exceptions.RobotoReadPlanExecutionException` with kind
    :py:attr:`~roboto.exceptions.ReadPlanExecutionErrorKind.INVALID_TIMESTAMP` at the first row whose timestamp has no
    signed 64-bit nanosecond value once shifted: a value of the wrong type, NaN or infinite, or out of range. It raises
    :py:class:`~roboto.exceptions.RobotoInternalException` when the codec cannot read a message. Either exception has
    the ``mcap_codec.CodecError`` as its ``__cause__``.

    Args:
        group: Scan tasks that read the file, and the fields they supply.
        partition: Partition the file belongs to.
        window: Window of the partition's rows to keep, in nanoseconds since the Unix epoch, both ends included.
        params: How to reach the file.

    Raises:
        ImportError: The ``roboto[analytics]`` extra is not installed.
        RobotoReadPlanExecutionException: With kind ``UNSUPPORTED_TIMESTAMP``, before the file is opened, when the
            partition's timestamp is not a message log time, a message publish time or a schema field, is a schema
            field with no path, or has a unit other than s, ms, us or ns. With kind ``FIELD_NOT_IN_FILE``, when the
            file lacks a supplied field or the timestamp field. With kind ``DATA_RANGE_NOT_IN_FILE``, when the
            partition's ``data_range`` ends past the topic's messages in the file. The last two have the
            ``mcap_codec.CodecError`` as their ``__cause__``.
        RobotoInternalException: The codec cannot open the file for another reason. Its ``__cause__`` is the
            ``mcap_codec.CodecError``, whose ``code`` is an ``mcap_codec.ErrorCode`` such as ``UNKNOWN_CHANNEL``,
            ``AMBIGUOUS_CHANNEL``, ``UNSUPPORTED_MCAP_LAYOUT`` or ``UNSUPPORTED_ENCODING``.
    """

    def __init__(
        self,
        group: ScanTaskGroup,
        partition: ReadPlanPartition,
        window: TimeWindow,
        params: FileDecodeParams,
    ) -> None:
        # The codec yields PyArrow batches. Checking here makes a missing PyArrow name the roboto[analytics] extra
        # rather than the codec's own extra.
        import_optional_dependency("pyarrow", "analytics")
        # Imported here so the compiled codec loads only when a read opens an MCAP file.
        import mcap_codec

        self.__group = group
        self.__partition = partition
        timestamp = _timestamp_source(partition)
        self.__http_reader = HttpRangeReader(params.signed_url_resolver(group.object))

        def read_bytes(offset: int, length: int) -> bytes:
            self.__http_reader.seek(offset)
            return self.__http_reader.read(length)

        try:
            self.__cursor = mcap_codec.open_mcap_file(
                read_bytes,
                self.__http_reader.size,
                timestamp=timestamp,
                projection=_projection(group.supplies),
                channel=mcap_codec.TopicName(group.topic_name) if group.topic_name is not None else None,
                time_window=(window.start, window.end),
                row_number_range=partition.data_range,
                timestamp_offset_ns=partition.time_offset_ns,
                timestamp_column_base=TIMESTAMP_FIELD_NAME,
                row_number_column_base=ROW_NUMBER_FIELD_NAME,
            )
        except mcap_codec.CodecError as exc:
            self.__http_reader.close()
            raise self.__open_error(exc) from exc
        except BaseException:
            self.__http_reader.close()
            raise
        try:
            schema = self.__cursor.schema
            row_number_and_timestamp = {row_number_column_index(schema), timestamp_column_index(schema)}
            self.__value_fields = [field for index, field in enumerate(schema) if index not in row_number_and_timestamp]
        except BaseException:
            self.close()
            raise

    @property
    def value_fields(self) -> list["pyarrow.Field"]:
        return list(self.__value_fields)

    def batches(self) -> collections.abc.Iterator["pyarrow.RecordBatch"]:
        import mcap_codec

        # Download exactly the Chunk records the cursor will read, so the reader answers its reads from memory.
        # Without this, a read the reader's cache cannot serve fetches 8 MiB from its position, which can include
        # chunks the cursor skips.
        for offset, length in self.__cursor.chunk_ranges:
            self.__http_reader.prefetch_range(offset, offset + length - 1)
        try:
            yield from self.__cursor
        except mcap_codec.CodecError as exc:
            raise self.__read_error(exc) from exc

    def close(self) -> None:
        self.__cursor.close()
        self.__http_reader.close()

    def struct_field_names(self, path: FieldPath) -> typing.Optional[list[str]]:
        pa = import_optional_dependency("pyarrow", "analytics")

        fields: collections.abc.Iterable["pyarrow.Field"] = self.__cursor.channel_schema
        names: typing.Optional[list[str]] = None
        for name in path:
            field = next((field for field in fields if field.name == name), None)
            if field is None or not pa.types.is_struct(field.type):
                return None
            fields = typing.cast("pyarrow.StructType", field.type)
            names = [child.name for child in fields]
        return names

    def __open_error(self, exc: "mcap_codec.CodecError") -> Exception:
        """Return the exception to raise when the codec cannot open the file."""
        import mcap_codec

        data_range = self.__partition.data_range
        # The plan's models reject a window or a data_range that ends before it starts, so the one input the codec can
        # reject at open is a data_range that ends past the topic's messages in the file.
        if exc.code == mcap_codec.ErrorCode.INVALID_INPUT and data_range is not None:
            start, end = data_range
            return RobotoReadPlanExecutionException(
                f"data_range [{start}, {end}) of topic partition {self.__partition.topic_part_id} names stored rows "
                "beyond the topic's messages in the file; the declared slice does not match the backing file. "
                "Please reach out to Roboto support.",
                kind=ReadPlanExecutionErrorKind.DATA_RANGE_NOT_IN_FILE,
            )
        return self.__read_error(exc)

    def __read_error(self, exc: "mcap_codec.CodecError") -> Exception:
        """Return the exception to raise for a failure the codec reports while it opens or reads the file."""
        import mcap_codec

        topic_part_id = self.__partition.topic_part_id
        if exc.code == mcap_codec.ErrorCode.INVALID_PROJECTION and exc.field_path is not None:
            return RobotoReadPlanExecutionException(
                f'The MCAP file of topic partition {topic_part_id} has no field "{".".join(exc.field_path)}".',
                kind=ReadPlanExecutionErrorKind.FIELD_NOT_IN_FILE,
                field_path=exc.field_path,
            )
        if exc.code == mcap_codec.ErrorCode.INVALID_TIMESTAMP and exc.row_number is not None:
            return RobotoReadPlanExecutionException(
                f"The timestamp of row {exc.row_number} of topic partition {topic_part_id} is invalid: {exc}",
                kind=ReadPlanExecutionErrorKind.INVALID_TIMESTAMP,
                row_number=exc.row_number,
            )
        return RobotoInternalException(
            f"Could not read topic data from MCAP file {self.__group.object.fs_node_id!r} ({exc.code}): {exc}"
        )


def _projection(supplies: collections.abc.Sequence[SuppliedField]) -> "mcap_codec.Projection":
    """Build the codec's projection of the supplied fields: each at its path, less its excluded fields.

    The codec keeps a field when, of the include and exclude paths that name it or one of its ancestors, the longest is
    an include. An exclude wins over an equal include, so a path one supplied field excludes is left out of
    ``exclude`` when another supplied field is at that path.
    """
    import mcap_codec

    include = [list(supplied.path) for supplied in supplies]
    exclude = [list(path) for supplied in supplies for path in supplied.excluded if list(path) not in include]
    return mcap_codec.Projection(include=include, exclude=exclude)


def _timestamp_source(partition: ReadPlanPartition) -> "mcap_codec.TimestampSource":
    """Build the codec's timestamp source for the partition.

    Raises :py:class:`~roboto.exceptions.RobotoReadPlanExecutionException` with kind
    :py:attr:`~roboto.exceptions.ReadPlanExecutionErrorKind.UNSUPPORTED_TIMESTAMP` when the timestamp's kind is not a
    message log time, a message publish time or a schema field, when a schema field has no path, or when the unit is
    not s, ms, us or ns.
    """
    import mcap_codec

    timestamp = partition.timestamp

    def unsupported(reason: str) -> RobotoReadPlanExecutionException:
        return RobotoReadPlanExecutionException(
            f"Topic partition {partition.topic_part_id} is read from MCAP, and its timestamp {reason}.",
            kind=ReadPlanExecutionErrorKind.UNSUPPORTED_TIMESTAMP,
        )

    if timestamp.kind in ("message_log_time", "message_publish_time"):
        return mcap_codec.TimestampSource(timestamp.kind)
    if timestamp.kind != "schema_field":
        raise unsupported(f'kind "{timestamp.kind}" is not a message log time, message publish time or schema field')
    if timestamp.field is None or not timestamp.field.path:
        raise unsupported("field has no declared path")
    unit = plan_timestamp_unit(partition)
    return mcap_codec.TimestampSource(
        "schema_field",
        path=list(timestamp.field.path),
        unit=unit.value if unit is not None else None,
    )
