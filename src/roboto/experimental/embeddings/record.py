# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

EmbeddingSpaceKind = typing.Literal["embedding", "map"]
"""Kind of an embedding space: whether distances in it mean similarity.

- ``embedding``: distances in the space mean similarity.
- ``map``: a 2-D layout the producer computed from other spaces, such as with UMAP, in which each row's vector is its
  ``[x, y]`` point, so ``dim`` is 2. Boards plot a map. Its distances are the layout's, so Roboto never searches it,
  scores anomalies on it, or projects it again; measure distances in the spaces it was built from.
"""

EmbeddingLevel = typing.Literal["window", "event", "session"]
"""Level of an embedding row: a fixed-length window of a session, one of the session's events, or the whole session."""


class EmbeddingSpaceRecord(pydantic.BaseModel):
    """Data record of an embedding space, as the Roboto API returns it.

    An embedding space holds one vector per window, event or whole session of an organization's sessions, all computed
    the same way, so that nearby vectors mean similar data. Roboto validates every row a producer puts into the space
    against this record. ``EmbeddingSpace`` wraps this record and exposes it as ``EmbeddingSpace.record``.
    """

    org_id: str
    """ID of the organization that owns the space."""

    space_id: str
    """Unique ID of the space within its organization, which Roboto derives from ``spec``.

    The ID is the SHA-256 digest, as 64 lowercase hexadecimal digits, of the UTF-8 encoding of
    ``json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``. Registering the same spec again
    in the organization therefore finds the same space.
    """

    name: str
    """Human-readable name of the space, which need not be unique.

    A producer that refits a space registers the successor under the old name. A reader that picks a space by name
    takes the newest space of that name that is not retired, or the newest one if all of them are retired.
    """

    kind: EmbeddingSpaceKind
    """Kind of the space: ``embedding`` if distances in it mean similarity, ``map`` if it is a 2-D layout."""

    dim: int
    """Length of every row's vector in the space, from 1 to 4,000; always 2 for a ``map``."""

    levels: list[str]
    """Levels a row of the space may have: one or more of ``window``, ``event`` and ``session``, each at most once."""

    window_ns: typing.Optional[int] = None
    """Length of every window row, in nanoseconds, or ``None`` when ``levels`` lacks ``window``."""

    stride_ns: typing.Optional[int] = None
    """Distance between the starts of a session's consecutive windows, in nanoseconds.

    It is ``None`` when ``levels`` lacks ``window``.
    """

    retired: bool = False
    """Whether the space is retired: readers no longer show it and it takes no new rows, but Roboto keeps its rows."""

    producer: str
    """Name of the producer that owns the space, such as ``roboto-embed@2`` or ``external``.

    Roboto stores it when the space is first registered; registering the space again does not change it.
    """

    spec: dict[str, typing.Any]
    """Producer's definition of the space, stored as sent; Roboto reads it only to derive ``space_id``."""

    display: typing.Optional[dict[str, typing.Any]] = None
    """Details readers show about the space, or ``None`` if it has none.

    Readers show the keys ``topics``, ``paths`` and ``description`` when present.
    """

    producer_state: typing.Optional[dict[str, typing.Any]] = None
    """State the producer reads back on its next run, such as a fitted basis, or ``None`` if it has none.

    Roboto returns it only when asked, by ``EmbeddingSpace.from_id`` with ``include_producer_state=True``. The
    records ``EmbeddingSpace.register`` and ``EmbeddingSpace.list`` return leave it ``None`` whatever the space holds.
    """

    created_by: str
    """Principal that registered the space, as ``<type>:<id>``, such as ``user:<user_id>``."""

    created: datetime.datetime
    """Time the space was registered."""

    modified: datetime.datetime
    """Time the space was last modified."""


class EmbeddingSessionCoverage(pydantic.BaseModel):
    """Coverage a producer reports for one session of a batch, beside the session's rows.

    A session's coverage in a space records which inputs its rows were computed from, or why it has none, so that a
    later run can embed only the sessions that changed. Carried in ``EmbeddingBatchRecord.sessions``.
    ``EmbeddingSpace.put_rows`` builds it from its ``inputs_hash``, ``no_rows_reason`` and ``replace_levels``
    arguments.
    """

    inputs_hash: typing.Optional[str] = None
    """Producer's key for the inputs the session's rows were computed from, or ``None`` to record none.

    The producer compares it on a later run to decide whether the session is stale.
    """

    no_rows_reason: typing.Optional[str] = None
    """Why the session produced no rows, such as ``topic missing: /imu``, or ``None`` when it produced rows.

    A session with a reason carries no rows, and committing the batch removes any rows the session held in the space.
    """

    replace_levels: typing.Optional[list[EmbeddingLevel]] = None
    """Levels the batch replaces in full for the session.

    ``None`` replaces only the levels the batch carries rows of. At a level named here that the batch carries no rows
    of for the session, the session ends up holding no rows.
    """


class EmbeddingSessionCoverageRecord(pydantic.BaseModel):
    """Data record of one session's coverage in an embedding space, as ``EmbeddingSpace.coverage`` returns it.

    ``EmbeddingSpace.coverage_of`` returns it too, for several spaces at once. Coverage records which inputs the
    session's rows were computed from, or why the session produced no rows, and the levels the space holds its rows
    at.
    """

    inputs_hash: typing.Optional[str] = None
    """``inputs_hash`` the session's last batch recorded.

    It is ``None`` if that batch gave none or no batch has named the session.
    """

    no_rows_reason: typing.Optional[str] = None
    """Why the session produced no rows, as its last batch reported, or ``None`` if it reported none."""

    levels_held: list[str] = pydantic.Field(default_factory=list)
    """Levels the space holds rows of the session at, or an empty list when it holds none."""

    updated_by: typing.Optional[str] = None
    """Principal whose batch last updated the session's coverage, or ``None`` when no batch has.

    It takes the ``<type>:<id>`` form of ``EmbeddingSpaceRecord.created_by``.
    """

    updated: typing.Optional[datetime.datetime] = None
    """Time a batch last updated the session's coverage, or ``None`` when no batch has."""


class EmbeddingBatchStatus(str, enum.Enum):
    """Status of an embedding batch: how far Roboto has got with writing its rows."""

    Staged = "staged"
    """Created and not yet committed; its Parquet file is being uploaded, or has been."""

    Committing = "committing"
    """Committed, and Roboto is validating and writing its rows."""

    Committed = "committed"
    """Validated, with every row written."""

    Failed = "failed"
    """Rejected whole, with nothing written; ``EmbeddingBatchRecord.rejected`` says why."""


class EmbeddingBatchProblem(pydantic.BaseModel):
    """One reason Roboto rejected an embedding batch. Carried in ``EmbeddingBatchRecord.rejected``."""

    row: typing.Optional[int] = None
    """Position of the row in the batch, counting from 0.

    It is ``None`` when the problem concerns the batch or a session rather than one row.
    """

    session_id: typing.Optional[str] = None
    """ID of the session the problem concerns, or ``None`` when it concerns none."""

    problem: str
    """Description of what is wrong."""


class EmbeddingBatchRecord(pydantic.BaseModel):
    """Data record of an embedding batch, as ``EmbeddingSpace.get_batch`` returns it.

    A batch is one upload of embedding rows into one space, which Roboto validates whole: it writes every row of the
    batch or none. ``EmbeddingSpace.put_rows`` returns the batches it sent in ``PutRowsResult.batches``. Roboto keeps
    a batch's record for 7 days after it is created.
    """

    batch_id: str
    """Unique ID of the batch, beginning with ``eb_``."""

    org_id: str
    """ID of the organization that owns the batch."""

    space_id: str
    """ID of the space the batch puts rows into."""

    status: EmbeddingBatchStatus
    """Status of the batch: how far Roboto has got with writing its rows."""

    sessions: dict[str, EmbeddingSessionCoverage] = pydantic.Field(default_factory=dict)
    """Coverage the batch reports for each session it names, keyed by session ID.

    Roboto records it when it writes the batch.
    """

    staging_key: typing.Optional[str] = None
    """Location of the copy of the batch's rows that Roboto holds until it writes them, or ``None`` if it holds none.

    The rows are the uploaded Parquet file, or the rows the request carried for a batch sent inline. Only Roboto reads
    this location.
    """

    rows_accepted: typing.Optional[int] = None
    """Number of rows Roboto wrote, or ``None`` until the status is ``Committed``."""

    rejected: typing.Optional[list[EmbeddingBatchProblem]] = None
    """First problems Roboto found, at most 100, when the status is ``Failed``; ``None`` otherwise."""

    invocation_id: typing.Optional[str] = None
    """ID of the invocation whose credentials created the batch, or ``None`` if no invocation's did."""

    created_by: str
    """Principal that created the batch, in the ``<type>:<id>`` form of ``EmbeddingSpaceRecord.created_by``."""

    created: datetime.datetime
    """Time the batch was created."""

    committed: typing.Optional[datetime.datetime] = None
    """Time Roboto finished writing the batch or rejected it, or ``None`` while it is staged or committing."""


class EmbeddingRow(pydantic.BaseModel):
    """One embedded span of a session and its vector, as ``EmbeddingSpace.reference_rows`` yields it."""

    session_id: str
    """ID of the session the span belongs to."""

    event_id: typing.Optional[str] = None
    """ID of the event an ``event`` row pools, or ``None`` at the other levels."""

    start_ns: int
    """Start of the span, in nanoseconds since the Unix epoch."""

    end_ns: int
    """End of the span, in nanoseconds since the Unix epoch."""

    activity: float
    """How active the span was, in units the producer chooses.

    For a signal, it is typically the root mean square of its samples. Similarity and anomaly searches treat the spans
    at the low end of a space's ``activity`` as idle and may leave them out. A space with no idle state gives every
    span the same ``activity``.
    """

    n_samples: int = 1
    """Number of samples the span pooled."""

    vector: list[float]
    """Vector of the span, as float32 values widened to Python floats."""


class PutRowsResult(pydantic.BaseModel):
    """Result of ``EmbeddingSpace.put_rows``: the batches it sent and how many rows Roboto wrote."""

    batches: list[EmbeddingBatchRecord] = pydantic.Field(default_factory=list)
    """Every batch the rows were sent in, in the order they were committed."""

    rows_accepted: int = 0
    """Number of rows written across the batches that had finished writing when ``put_rows`` returned.

    A batch still committing then (``wait=False``) adds nothing; read its outcome with ``EmbeddingSpace.get_batch``.
    """
