# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing

import mcap.reader

from ....compat import import_optional_dependency
from ....domain.topics.record import FieldPath
from ....exceptions import RobotoInternalException
from ....formats.mcap import open_for_window
from ....storage import as_io_bytes
from ....time import TimeUnit
from ..batch_transforms import TIMESTAMP_FIELD_NAME, timestamp_field
from ..read_plan import (
    ReadPlanScanTask,
    ReadPlanTimestamp,
    TimeWindow,
)
from .common import ScanTaskDecodeParams, leaf_most

if typing.TYPE_CHECKING:
    import pyarrow  # pants: no-infer-dep

_SUPPORTED_SCHEMA_ENCODINGS = frozenset({"ros1msg", "ros2msg", "ros2idl", "omgidl", "jsonschema", "json"})
"""Schema encodings our ``mcap_codec`` batch decoder handles.

The ROS/CDR family (``ros1msg`` / ``ros2msg`` / ``ros2idl`` / ``omgidl``) plus the JSON family
(``jsonschema``, with ``json`` a wire-real alias the codec's ``SchemaEncoding::parse`` accepts).
msgpack channels carry a ``jsonschema`` schema, so they need no separate entry -- the codec
dispatches on the channel's message encoding, which this path already passes through.
"""


def decode_mcap_batches(
    scan_task: ReadPlanScanTask,
    timestamp: ReadPlanTimestamp,
    window: TimeWindow,
    projection_paths: collections.abc.Sequence[FieldPath],
    params: ScanTaskDecodeParams,
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Decode one MCAP scan task into native-order RecordBatches, filtered and projected.

    Every chunk's bytes go straight to the Rust ``mcap_codec`` batch decoder, which
    parses and decompresses the chunk, decodes each supported encoding's payloads into
    Arrow columns, and window-filters and timestamps rows in Rust — one RecordBatch per
    chunk.

    A chunked, single-schema file whose schema encoding the codec handles
    (:py:data:`_SUPPORTED_SCHEMA_ENCODINGS` — the ROS/CDR family plus JSON and msgpack,
    which rides a ``jsonschema`` schema) is supported, which is what topic-data ingestion
    produces. Unchunked, summary-less, multi-schema, and unsupported-encoding files are
    rejected.

    Batches come out in the file's persisted (native chunk) order, which the partition
    overlay and cross-partition concatenation rely on (see
    :py:meth:`DecodedScanTask.batches`).

    Raises:
        RobotoInternalException: The file is not a chunked, single-schema MCAP whose
            schema encoding this read path supports (e.g. an unchunked file or a
            ``protobuf`` channel).
    """
    start = window.start
    end = window.end

    signed_url = params.signed_url_resolver(scan_task.object.fs_node_id)
    if timestamp.kind == "message_log_time":
        # The chunk index is keyed by log time, so the window bounds the fetch directly.
        # The mcap end bound is exclusive; the window is inclusive.
        http_reader = open_for_window(signed_url, start_time=start, end_time=end + 1)
    else:
        # A non-log-time timestamp cannot be window-filtered by log time; fetch
        # everything and let the codec filter per row.
        http_reader = open_for_window(signed_url)

    try:
        summary = mcap.reader.SeekingReader(as_io_bytes(http_reader)).get_summary()
        encoding = _sole_schema_encoding(summary)
        if summary is None or not summary.chunk_indexes or encoding not in _SUPPORTED_SCHEMA_ENCODINGS:
            chunk_count = 0 if summary is None else len(summary.chunk_indexes)
            raise RobotoInternalException(
                "MCAP topic-data decode supports only chunked, single-schema files whose schema "
                f"encoding this read path handles (got schema encoding {encoding!r} with "
                f"{chunk_count} chunk indexes)."
            )
        yield from _decode_mcap_chunks(http_reader, summary, timestamp, window, projection_paths)
    finally:
        http_reader.close()


def _sole_schema_encoding(summary: typing.Any) -> typing.Optional[str]:
    """The schema encoding of a single-schema MCAP file, or ``None`` if undetermined.

    A topic representation file carries one channel and one schema; this reads its
    encoding to validate the decode path. Returns ``None`` when there is no summary
    or not exactly one schema.
    """
    if summary is None or len(summary.schemas) != 1:
        return None
    (schema,) = summary.schemas.values()
    return schema.encoding


def _decode_mcap_chunks(
    http_reader: typing.Any,
    summary: typing.Any,
    timestamp: ReadPlanTimestamp,
    window: TimeWindow,
    projection_paths: collections.abc.Sequence[FieldPath],
) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
    """Decode chunks through the Rust ``mcap_codec`` batch decoder.

    Each in-window chunk's raw bytes (read from the prefetch buffer) go to
    :py:class:`mcap_codec.McapBatchDecoder`, which parses and decompresses the chunk,
    decodes each supported encoding's payloads into Arrow columns, reads each row's
    timestamp, and window-filters and drops undecodable rows — one RecordBatch per
    chunk, which bounds memory to a chunk's rows. The timestamp column is re-tagged
    with the stored-time metadata the overlay keys on.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    # Imported lazily so the Rust extension loads only when a supported channel is read.
    from mcap_codec import McapBatchDecoder

    raw_start, raw_end = window.start, window.end
    (schema,) = summary.schemas.values()
    # The wire framing (``cdr`` / ``ros1``) lives on the channel, not the schema, and the codec
    # needs it to read the payload bytes. A topic-data file is single-schema, so every channel
    # shares it; take the framing off the channel that references this schema.
    message_encoding = next(
        channel.message_encoding for channel in summary.channels.values() if channel.schema_id == schema.id
    )

    # One value column per projected top-level root; the codec groups the leaf paths.
    projection = [list(path) for path in leaf_most(projection_paths)]

    if timestamp.kind == "message_log_time":
        ts_kind, ts_field_path, ts_unit = "log_time", None, None
    elif timestamp.kind == "message_publish_time":
        ts_kind, ts_field_path, ts_unit = "publish_time", None, None
    else:  # schema_field
        ts_kind = "field"
        ts_field_path = list(timestamp.field.path) if timestamp.field is not None else None
        ts_unit = timestamp.unit or TimeUnit.Nanoseconds.value

    try:
        decoder = McapBatchDecoder(
            schema.encoding,
            message_encoding,
            schema.data,
            schema.name,
            projection,
            ts_kind,
            # Requested base name. The codec suffixes it until it no longer collides
            # with a value column it actually emits (matched against the codec's own
            # canonical column names), then exposes the resolved name as a getter.
            TIMESTAMP_FIELD_NAME,
            ts_field_path,
            ts_unit,
        )
    except Exception:
        # The codec builds its Arrow layout from the schema and rejects a projection or
        # timestamp path the schema does not declare with a bare ValueError. Surface a
        # Roboto-context error that names what was being decoded and the guidance that
        # fixes it: paths must spell fields exactly as the file's schema declares them.
        raise RobotoInternalException(
            f"MCAP topic-data decode could not build a decoder for schema {schema.name!r} "
            f"(encoding {schema.encoding!r}) with projected paths {projection!r}."
        )

    # Read the resolved name back rather than re-deriving the value-column names
    # here: the decoder is the authority on what it emits, so this can't drift from
    # the codec's canonicalization the way a Python-side re-derivation would.
    ts_name = decoder.timestamp_column_name
    ts_arrow_field = timestamp_field(ts_name)
    log_time_window = timestamp.kind == "message_log_time"

    for chunk_index in sorted(summary.chunk_indexes, key=lambda ci: ci.chunk_start_offset):
        if log_time_window and (chunk_index.message_end_time < raw_start or chunk_index.message_start_time > raw_end):
            continue
        http_reader.seek(chunk_index.chunk_start_offset)
        chunk_bytes = http_reader.read(chunk_index.chunk_length)
        batch = decoder.decode_chunks([chunk_bytes], raw_start, raw_end)
        if batch.num_rows == 0:
            continue
        # Re-tag column 0 (the int64 timestamp) with the stored-time metadata marker.
        marked_schema = batch.schema.set(0, ts_arrow_field)
        yield pa.RecordBatch.from_arrays(batch.columns, schema=marked_schema)
