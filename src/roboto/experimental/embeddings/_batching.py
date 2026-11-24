# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import base64
import collections.abc
import dataclasses
import io
import os
import pathlib
import struct
import typing

from ...compat import import_optional_dependency
from ...exceptions import RobotoInvalidRequestException
from .record import EmbeddingSessionCoverage

if typing.TYPE_CHECKING:  # pragma: no cover
    import pandas  # pants: no-infer-dep
    import pyarrow  # pants: no-infer-dep

RowsInput = typing.Union["pyarrow.Table", "pandas.DataFrame", str, os.PathLike]
"""Rows for ``EmbeddingSpace.put_rows``, in the forms its ``rows`` argument describes."""

ROW_COLUMNS = ("session_id", "level", "event_id", "start_ns", "end_ns", "space_id", "n_samples", "activity", "vector")
"""Columns every row of an embedding batch carries.

``EmbeddingSpace.put_rows`` fills in ``space_id``, ``event_id`` and ``n_samples`` when the rows lack them, and a row
may also carry ``in_reference``. No SDK method reads it.
"""

MAX_BATCH_ROWS = 50_000
"""Maximum number of rows in one embedding batch.

``EmbeddingSpace.put_rows`` splits rows into batches of at most this many and rejects a session with more, because
all of a session's rows travel in one batch.
"""

INLINE_BATCH_MAX_BYTES = 1_500_000
"""Number of bytes of estimated JSON above which ``EmbeddingSpace.put_rows`` uploads a batch as a Parquet file.

A batch at or below it is sent in the request itself. Roboto refuses an inline request body above 2 MB, so the
threshold stays below that limit.
"""

_ROW_JSON_OVERHEAD_BYTES = 320
"""Upper estimate of the bytes one row adds to an inline request besides its vector.

Covers the row's keys, IDs, ``level``, times, ``activity`` and ``n_samples``.
"""

_SESSION_JSON_OVERHEAD_BYTES = 200
"""Upper estimate of the bytes one named session's coverage adds to an inline request.

``estimate_inline_bytes`` counts the request's own keys and ``space_id`` as one more session.
"""


@dataclasses.dataclass(frozen=True)
class PlannedBatch:
    """Rows and session coverage that one batch carries, as ``plan_batches`` splits them."""

    table: "pyarrow.Table"
    """Rows of the batch, in the columns ``to_table`` builds."""

    sessions: dict[str, EmbeddingSessionCoverage]
    """Coverage the batch reports, by session ID.

    It covers each session named in ``EmbeddingSpace.put_rows``'s arguments whose rows the batch holds, and on the
    last batch, each named session with no rows.
    """


def to_table(rows: RowsInput, space_id: str) -> "pyarrow.Table":
    """Build a pyarrow Table of the batch columns from ``rows``, with each vector as a list of float32 values.

    A missing ``space_id`` column is filled with ``space_id``, a missing ``event_id`` column with nulls, and a
    missing ``n_samples`` column with 1. Columns other than ``session_id`` and ``vector`` keep their values and types.

    Args:
        rows: A pyarrow Table, a pandas DataFrame, or the path of a Parquet file.

    Raises:
        ImportError: The ``roboto[analytics]`` extra is not installed.
        RobotoInvalidRequestException: The rows have no ``session_id``, ``activity`` or ``vector`` column, or a
            row's ``session_id`` is null.
    """
    pa = import_optional_dependency("pyarrow", "analytics")

    if isinstance(rows, (str, os.PathLike)):
        pq = import_optional_dependency("pyarrow.parquet", "analytics")
        table = pq.read_table(pathlib.Path(rows))
    elif isinstance(rows, pa.Table):
        table = rows
    else:
        table = pa.Table.from_pandas(rows, preserve_index=False)

    for required in ("session_id", "activity", "vector"):
        if required not in table.column_names:
            raise RobotoInvalidRequestException(f"Embedding rows need the column {required}.")
    if table["session_id"].null_count:
        raise RobotoInvalidRequestException("Every embedding row needs a session_id.")
    if "space_id" not in table.column_names:
        table = table.append_column("space_id", pa.array([space_id] * table.num_rows, type=pa.string()))
    if "event_id" not in table.column_names:
        table = table.append_column("event_id", pa.nulls(table.num_rows, type=pa.string()))
    if "n_samples" not in table.column_names:
        table = table.append_column("n_samples", pa.array([1] * table.num_rows, type=pa.int64()))

    for name, type_ in (("session_id", pa.string()), ("vector", pa.list_(pa.float32()))):
        table = table.set_column(table.column_names.index(name), name, table[name].cast(type_))
    return table


def plan_batches(
    table: "pyarrow.Table", sessions: collections.abc.Mapping[str, EmbeddingSessionCoverage]
) -> list[PlannedBatch]:
    """Split ``table`` into batches of at most ``MAX_BATCH_ROWS`` rows, keeping each session's rows in one batch.

    A batch replaces each session's rows per level, so a session split across two batches would have the second
    batch's rows replace the first's. Sessions are packed into batches in the order they first appear, and a new
    batch starts when the next session's rows would not fit. Each named session goes into the batch that holds its
    rows; a named session without rows goes into the last batch, which carries no rows when ``table`` is empty.

    Args:
        table: Rows to split, as ``to_table`` builds them.
        sessions: Coverage of each session ``EmbeddingSpace.put_rows``'s arguments name, by session ID.

    Returns:
        The batches, in the order they are to be sent. Empty when ``table`` has no rows and ``sessions`` is empty.

    Raises:
        RobotoInvalidRequestException: One session has more than ``MAX_BATCH_ROWS`` rows.
    """
    pa = import_optional_dependency("pyarrow", "analytics")
    pc = import_optional_dependency("pyarrow.compute", "analytics")

    # Counter keeps insertion order, so the loop below packs sessions in the order they first appear.
    counts = collections.Counter(str(session_id) for session_id in table["session_id"].to_pylist())

    groups: list[list[str]] = []
    group_rows = 0
    for session_id, count in counts.items():
        if count > MAX_BATCH_ROWS:
            raise RobotoInvalidRequestException(
                f"Session {session_id} has {count} rows; one batch carries at most {MAX_BATCH_ROWS}, and a session's "
                "rows must all travel in one batch. If its rows span several levels, put each level in its own call."
            )
        if not groups or group_rows + count > MAX_BATCH_ROWS:
            groups.append([])
            group_rows = 0
        groups[-1].append(session_id)
        group_rows += count

    batches = [
        PlannedBatch(
            table=table.filter(pc.is_in(table["session_id"], value_set=pa.array(group, type=pa.string()))),
            sessions={session_id: sessions[session_id] for session_id in group if session_id in sessions},
        )
        for group in groups
    ]
    rowless = {session_id: coverage for session_id, coverage in sessions.items() if session_id not in counts}
    if rowless:
        if not batches:
            batches.append(PlannedBatch(table=table.slice(0, 0), sessions={}))
        batches[-1].sessions.update(rowless)
    return batches


def estimate_inline_bytes(batch: PlannedBatch, dim: int) -> int:
    """Return an upper estimate of the batch's size in bytes as an inline JSON request, with vectors as base64.

    Args:
        dim: Number of values in each of the space's vectors.
    """
    # Base64 writes 4 characters for every 3 bytes, rounded up, and each float32 value is 4 bytes.
    vector_bytes = 4 * ((4 * dim + 2) // 3)
    return batch.table.num_rows * (vector_bytes + _ROW_JSON_OVERHEAD_BYTES) + _SESSION_JSON_OVERHEAD_BYTES * (
        len(batch.sessions) + 1
    )


def to_parquet_bytes(table: "pyarrow.Table") -> bytes:
    """Return ``table`` as the bytes of a Parquet file."""
    pq = import_optional_dependency("pyarrow.parquet", "analytics")
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def to_json_rows(table: "pyarrow.Table") -> list[dict[str, typing.Any]]:
    """Return ``table``'s rows as JSON-compatible dictionaries, each vector as base64 of little-endian float32."""
    rows = table.to_pylist()
    for row in rows:
        row["vector"] = encode_vector(row["vector"])
    return rows


def encode_vector(values: collections.abc.Sequence[float]) -> str:
    """Render ``values`` as base64 of little-endian float32."""
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")


def decode_vector(encoded: str) -> list[float]:
    """Return the float32 values that base64 ``encoded`` holds, read little-endian."""
    raw = base64.b64decode(encoded)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))
