# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import builtins
import collections.abc
import typing
import urllib.parse

from ...http import HttpClient, RobotoClient
from ...sentinels import NotSet, NotSetType, is_set, remove_not_set
from ...waiters import wait_for
from ._batching import (
    INLINE_BATCH_MAX_BYTES,
    PlannedBatch,
    RowsInput,
    estimate_inline_bytes,
    plan_batches,
    to_json_rows,
    to_parquet_bytes,
    to_table,
)
from .exceptions import RobotoEmbeddingBatchRejectedException
from .operations import (
    CreateEmbeddingBatchRequest,
    CreateEmbeddingBatchResponse,
    EmbeddingCoverageResponse,
    InlineEmbeddingBatchRequest,
    RegisterEmbeddingSpaceRequest,
    UpdateEmbeddingSpaceRequest,
)
from .record import (
    EmbeddingBatchRecord,
    EmbeddingBatchStatus,
    EmbeddingLevel,
    EmbeddingRow,
    EmbeddingSessionCoverage,
    EmbeddingSessionCoverageRecord,
    EmbeddingSpaceKind,
    EmbeddingSpaceRecord,
    PutRowsResult,
)
from .search import (
    EmbeddingAnomaliesRequest,
    EmbeddingAnomaliesResponse,
    EmbeddingRowRecord,
    EmbeddingRowsPage,
    EmbeddingRowsRequest,
    EmbeddingSessionScope,
    EmbeddingSimilarRequest,
    EmbeddingSimilarResponse,
)

COVERAGE_SESSIONS_PER_REQUEST = 150
"""Maximum number of sessions one coverage request names.

``EmbeddingSpace.coverage`` and ``EmbeddingSpace.coverage_of`` send any number of sessions in requests of this many.
Each session repeats ``session_ids=`` in the URL, and this limit keeps the URL a few kilobytes long; Roboto accepts up
to 1,000 sessions per request.
"""

_FINISHED = (EmbeddingBatchStatus.Committed, EmbeddingBatchStatus.Failed)


class EmbeddingSpace:
    """An embedding space of an organization's sessions, and the rows a producer has put into it.

    An embedding space holds one vector per window, event or whole session of an organization's sessions, all computed
    the same way, so that nearby vectors mean similar data. A producer, such as an action that computes embeddings,
    registers a space by its ``spec``, its own definition of the space, and then puts rows into it. Roboto validates
    every row against the space (vector length, levels, window grid, and that its sessions and events belong to the
    organization) and serves the rows to search, boards and Roboto's AI.

    Get an ``EmbeddingSpace`` from ``register``, ``from_id`` or ``list``. To wrap an ``EmbeddingSpaceRecord`` already
    fetched from Roboto, build an ``EmbeddingSpace`` from it directly. Each instance holds a copy of the space's
    record, which ``update`` and ``retire`` update from Roboto's response.

    Args:
        record: Record of the space.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.

    Note:
        Embeddings are in preview; contact Roboto to enable them for your organization.
    """

    __record: EmbeddingSpaceRecord
    __roboto_client: RobotoClient

    @classmethod
    def register(
        cls,
        name: str,
        *,
        kind: EmbeddingSpaceKind = "embedding",
        dim: int,
        levels: collections.abc.Sequence[EmbeddingLevel],
        window_ns: typing.Optional[int] = None,
        stride_ns: typing.Optional[int] = None,
        producer: str,
        spec: dict[str, typing.Any],
        display: typing.Optional[dict[str, typing.Any]] = None,
        producer_state: typing.Optional[dict[str, typing.Any]] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> EmbeddingSpace:
        """Register an embedding space, or fetch the space the organization registered before with the same ``spec``.

        Roboto derives the space's ID from ``spec``, as ``EmbeddingSpaceRecord.space_id`` describes, so the same spec
        always means the same space. Registering a spec the organization has already registered, with the same
        arguments, returns that space unchanged, so a producer can register on every run. A different ``kind``,
        ``dim``, ``levels``, window grid (``window_ns`` and ``stride_ns``), ``name`` or ``display`` raises
        ``RobotoConflictException`` rather than being ignored: change ``display`` with ``update``, and give a space
        with another name another spec. Roboto stores ``producer`` and ``producer_state`` only when the space is first
        registered; replace ``producer_state`` with ``update``.

        Args:
            name: Human-readable name of the space, which need not be unique.
            kind: ``embedding`` for a space whose distances mean similarity, or ``map`` for a 2-D layout computed
                from other spaces, which boards plot and Roboto never searches. ``EmbeddingSpaceKind`` describes both.
            dim: Length of every row's vector, from 1 to 4,000. A ``map`` space's is 2.
            levels: Levels the space's rows may have: one or more of ``window``, ``event`` and ``session``, each at
                most once.
            window_ns: Length of every window row, in nanoseconds. Required, and positive, when ``levels`` holds
                ``window``; otherwise ``None``.
            stride_ns: Time between the starts of a session's consecutive windows, in nanoseconds. Required, and
                positive, when ``levels`` holds ``window``; otherwise ``None``.
            producer: Name of the producer that owns the space, such as ``roboto-embed@2`` or ``external``.
            spec: Producer's definition of the space, such as its topics and featurizer, stored as sent. Put in it
                everything that makes two spaces different, and nothing that changes between runs.
            display: Details readers show about the space: the keys ``topics``, ``paths`` and ``description``, when
                present. ``None`` sets none.
            producer_state: State the producer reads back on its next run, such as a fitted basis. ``None`` sets
                none.
            owner_org_id: Organization to register the space in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The registered space. Its ``record`` leaves ``producer_state`` ``None``; fetch it with ``from_id`` and
            ``include_producer_state=True``.

        Raises:
            pydantic.ValidationError: ``kind`` is not ``embedding`` or ``map``, or a level is not ``window``,
                ``event`` or ``session``.
            RobotoInvalidRequestException: ``dim`` is outside 1 to 4,000 or a map's is not 2, ``levels`` is empty or
                repeats a level, or the window grid is missing or not positive for a space with window rows, or given
                for one without.
            RobotoConflictException: The organization has a space with this ``spec`` registered with another
                ``kind``, ``dim``, ``levels``, window grid, ``name`` or ``display``.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.register(
            ...     "imu-spectral",
            ...     dim=64,
            ...     levels=["window", "session"],
            ...     window_ns=2_000_000_000,
            ...     stride_ns=1_000_000_000,
            ...     producer="my-embedder@1",
            ...     spec={"topics": ["/imu"], "featurizer": "spectral"},
            ...     display={"topics": ["/imu"], "description": "IMU spectra in 2 s windows"},
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = RegisterEmbeddingSpaceRequest(
            name=name,
            kind=kind,
            dim=dim,
            levels=builtins.list(levels),
            window_ns=window_ns,
            stride_ns=stride_ns,
            producer=producer,
            spec=spec,
            display=display,
            producer_state=producer_state,
        )
        record = roboto_client.post(
            "v1/embeddings/spaces", data=request.model_dump(mode="json"), caller_org_id=owner_org_id
        ).to_record(EmbeddingSpaceRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_id(
        cls,
        space_id: str,
        include_producer_state: bool = False,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> EmbeddingSpace:
        """Fetch a registered space, retired or not.

        Args:
            space_id: Unique ID of the space.
            include_producer_state: Whether to include the space's ``producer_state``, which can be large. ``False``
                leaves it ``None`` in the record.
            owner_org_id: Organization that owns the space. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has registered no space with this ID.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.from_id("3f2a" * 16, include_producer_state=True)
            >>> basis = (space.record.producer_state or {}).get("basis")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/embeddings/spaces/id/{urllib.parse.quote(space_id, safe='')}",
            query={"include_producer_state": "true"} if include_producer_state else None,
            caller_org_id=owner_org_id,
        ).to_record(EmbeddingSpaceRecord)
        return cls(record, roboto_client)

    @classmethod
    def list(
        cls,
        include_retired: bool = False,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> builtins.list[EmbeddingSpace]:
        """List the organization's registered spaces, map spaces included, oldest first.

        A map space's ``EmbeddingSpaceRecord.kind`` is ``map``. Each record leaves ``producer_state`` ``None``;
        ``from_id`` fetches it.

        Args:
            include_retired: Whether to list retired spaces too, which readers no longer show and which take no new
                rows.
            owner_org_id: Organization whose spaces to list. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> for space in EmbeddingSpace.list():
            ...     print(space.name, space.space_id, space.record.kind, space.record.levels)
            >>> mine = [
            ...     s
            ...     for s in EmbeddingSpace.list(include_retired=True)
            ...     if s.record.producer.startswith("roboto-embed@")
            ... ]
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get(
            "v1/embeddings/spaces",
            query={"include_retired": "true"} if include_retired else None,
            caller_org_id=owner_org_id,
        ).to_record_list(EmbeddingSpaceRecord)
        return [cls(record, roboto_client) for record in records]

    @staticmethod
    def coverage_of(
        space_ids: collections.abc.Iterable[str],
        session_ids: collections.abc.Iterable[str],
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> dict[str, dict[str, EmbeddingSessionCoverageRecord]]:
        """Fetch each session's coverage in each of several spaces, for a producer deciding what to embed again.

        ``coverage`` describes what a session's coverage holds.

        Args:
            space_ids: IDs of the spaces to read coverage in. A repeated ID is read once.
            session_ids: IDs of the sessions to read coverage of.
            owner_org_id: Organization that owns the spaces. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            Coverage by space ID, then by session ID, of each session that has coverage or rows in the space. A
            session left out has not been embedded in that space.

        Raises:
            RobotoNotFoundException: The organization has registered no space with one of ``space_ids``.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> coverage = EmbeddingSpace.coverage_of(["3f2a" * 16, "9c1e" * 16], ["se_1", "se_2"])
            >>> stale = [s for s in ["se_1", "se_2"] if s not in coverage["3f2a" * 16]]
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        sessions = builtins.list(session_ids)
        return {
            space_id: _read_coverage(roboto_client, space_id, sessions, caller_org_id=owner_org_id)
            for space_id in dict.fromkeys(space_ids)
        }

    def __init__(self, record: EmbeddingSpaceRecord, roboto_client: typing.Optional[RobotoClient] = None) -> None:
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def dim(self) -> int:
        """Length of every row's vector in the space, from 1 to 4,000; always 2 for a ``map``."""
        return self.__record.dim

    @property
    def name(self) -> str:
        """Human-readable name of the space, which need not be unique.

        ``EmbeddingSpaceRecord.name`` says how a reader picks a space by name.
        """
        return self.__record.name

    @property
    def record(self) -> EmbeddingSpaceRecord:
        """Record of the embedding space that this instance holds."""
        return self.__record

    @property
    def space_id(self) -> str:
        """Unique ID of the space within its organization, which Roboto derives from ``spec``.

        ``EmbeddingSpaceRecord.space_id`` says how.
        """
        return self.__record.space_id

    def coverage(self, session_ids: collections.abc.Iterable[str]) -> dict[str, EmbeddingSessionCoverageRecord]:
        """Fetch each session's coverage in this space: its ``inputs_hash``, why it produced no rows, the levels held.

        A session's coverage records which inputs its rows were computed from, or why it produced none, so that a
        later run can compare ``inputs_hash`` with its own and embed only the sessions that changed.

        Args:
            session_ids: IDs of the sessions to read coverage of.

        Returns:
            Coverage by session ID of each session that has coverage or rows in the space. A session left out has not
            been embedded in the space.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.from_id("3f2a" * 16)
            >>> coverage = space.coverage(["se_1", "se_2"])
            >>> current = {s for s, c in coverage.items() if c.inputs_hash == "files-v7"}
        """
        return _read_coverage(self.__roboto_client, self.space_id, session_ids, caller_org_id=self.__record.org_id)

    def put_rows(
        self,
        rows: RowsInput,
        *,
        inputs_hash: typing.Optional[collections.abc.Mapping[str, str]] = None,
        no_rows_reason: typing.Optional[collections.abc.Mapping[str, typing.Optional[str]]] = None,
        replace_levels: typing.Optional[collections.abc.Mapping[str, collections.abc.Sequence[EmbeddingLevel]]] = None,
        wait: bool = True,
        timeout_s: float = 600,
    ) -> PutRowsResult:
        """Put rows into the space, replacing what each session held at each level the rows carry.

        For each session and level a batch carries rows of, those rows replace the rows the session held at that level
        in the space, so re-embedding a session replaces its old rows rather than adding to them. A level the rows
        carry nothing of for a session keeps the session's rows there, unless ``replace_levels`` names it.

        Each row has these columns:

        - ``session_id``: ID of the session the row's span belongs to.
        - ``level``: ``window``, ``event`` or ``session``.
        - ``event_id``: ID of the event an ``event`` row pools, which must be an event of the row's session; null at
          the other levels. Filled with nulls when absent.
        - ``start_ns`` and ``end_ns``: Start and end of the span, in nanoseconds since the Unix epoch.
        - ``activity``: How active the span was, as ``EmbeddingRow.activity`` describes.
        - ``vector``: List or array of ``dim`` numbers.
        - ``n_samples``: Number of samples the span pooled. Filled with 1 when absent.
        - ``space_id``: Filled with this space's ID when absent.
        - ``in_reference``: Optional. True on the window rows of the space's fleet reference sample, which
          ``reference_rows`` yields.

        ``put_rows`` sends the rows in these steps:

        1. It splits them into batches of at most 50,000 rows (``MAX_BATCH_ROWS``), each holding every row of each
           session it holds.
        2. It sends each batch in the request itself when the batch is small enough, and otherwise uploads it as a
           Parquet file.
        3. Roboto validates each batch whole before writing any of it, so a batch with one invalid row writes
           nothing, and then writes the batch in the background.
        4. Unless ``wait`` is ``False``, ``put_rows`` waits for each batch to be written before sending the next.

        It needs the ``analytics`` extra, whatever form ``rows`` takes: ``pip install 'roboto[analytics]'``.

        Args:
            rows: Rows to put: a pyarrow Table, a pandas DataFrame, or the path of a Parquet file.
            inputs_hash: Producer's key for the inputs each session's rows were computed from, by session ID. Roboto
                records it so that a later run can tell, with ``coverage``, which sessions are stale. A session named
                in ``no_rows_reason`` or ``replace_levels`` but not here has its recorded ``inputs_hash`` cleared.
                ``None`` names no session.
            no_rows_reason: Why each session produced no rows, by session ID, such as ``topic missing: /imu``. A
                session named here must carry no rows, or its batch is rejected; committing the batch removes any
                rows the session held in the space. ``None`` names no session.
            replace_levels: Levels each session's rows replace in full, by session ID. At a level named here that the
                rows carry nothing of for the session, the session ends up holding no rows; name ``event``, for
                example, to remove a session's event rows once all of its events are deleted. A session named in
                ``no_rows_reason`` loses its rows at every level whatever this says. ``None`` names no session.
            wait: Whether to wait for each batch to be written before sending the next, and raise if Roboto rejects
                one. With ``False``, each batch is committed and left for Roboto to write; follow it with
                ``get_batch``.
            timeout_s: Seconds to wait for each batch to be written.

        Returns:
            The batches the rows were sent in, and how many rows Roboto wrote.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            RobotoEmbeddingBatchRejectedException: Roboto rejected a batch; the exception lists the first problems
                found. Batches committed before it stay written, and no batch after it is sent.
            RobotoInvalidRequestException: The rows lack a ``session_id``, ``activity`` or ``vector`` column, a row's
                ``session_id`` is null, a session has more than 50,000 rows, or Roboto refused a request, for example
                because the space is retired.
            roboto.waiters.TimeoutError: A batch was not written within ``timeout_s``.

        Examples:
            Put a session's window rows and record what they were computed from:

            >>> import pyarrow as pa
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.from_id("3f2a" * 16)
            >>> rows = pa.table(
            ...     {
            ...         "session_id": ["se_1", "se_1"],
            ...         "level": ["window", "window"],
            ...         "event_id": [None, None],
            ...         "start_ns": [0, 1_000_000_000],
            ...         "end_ns": [2_000_000_000, 3_000_000_000],
            ...         "n_samples": [200, 200],
            ...         "activity": [0.4, 0.5],
            ...         "vector": [[0.1] * 64, [0.2] * 64],
            ...     }
            ... )
            >>> result = space.put_rows(rows, inputs_hash={"se_1": "files-v7"})
            >>> result.rows_accepted
            2

            Record that a session produced nothing from its inputs:

            >>> space.put_rows(
            ...     rows.slice(0, 0),
            ...     inputs_hash={"se_2": "files-v3"},
            ...     no_rows_reason={"se_2": "topic missing: /imu"},
            ... )

            Replace a session's window rows and remove its event rows, now that it has no events:

            >>> space.put_rows(
            ...     rows,
            ...     inputs_hash={"se_1": "files-v8"},
            ...     replace_levels={"se_1": ["window", "event"]},
            ... )
        """
        named: dict[str, EmbeddingSessionCoverage] = {}
        for session_id, hashed in (inputs_hash or {}).items():
            named.setdefault(session_id, EmbeddingSessionCoverage()).inputs_hash = hashed
        for session_id, reason in (no_rows_reason or {}).items():
            named.setdefault(session_id, EmbeddingSessionCoverage()).no_rows_reason = reason
        for session_id, replaced in (replace_levels or {}).items():
            named.setdefault(session_id, EmbeddingSessionCoverage()).replace_levels = builtins.list(replaced)

        result = PutRowsResult()
        for planned in plan_batches(to_table(rows, self.space_id), named):
            if estimate_inline_bytes(planned, self.dim) <= INLINE_BATCH_MAX_BYTES:
                batch = self.__put_inline(planned)
            else:
                batch = self.__put_staged(planned)
            if wait:
                batch = self.__wait_until_written(batch, timeout_s)
            if batch.status == EmbeddingBatchStatus.Failed:
                raise RobotoEmbeddingBatchRejectedException(batch, committed=result.batches)
            result.batches.append(batch)
            result.rows_accepted += batch.rows_accepted or 0
        return result

    def get_batch(self, batch_id: str) -> EmbeddingBatchRecord:
        """Fetch a batch of rows put into this space: its status, how many rows it wrote, or why Roboto rejected it.

        Roboto keeps a batch's record for 7 days after it is created.

        Args:
            batch_id: Unique ID of the batch, beginning with ``eb_``, as ``PutRowsResult.batches`` holds it.

        Raises:
            RobotoNotFoundException: The organization has no batch with this ID, or its record has expired.
        """
        return self.__roboto_client.get(
            f"v1/embeddings/batches/id/{urllib.parse.quote(batch_id, safe='')}", caller_org_id=self.__record.org_id
        ).to_record(EmbeddingBatchRecord)

    def reference_rows(self, page_size: int = 500) -> collections.abc.Generator[EmbeddingRow, None, None]:
        """Yield the space's fleet reference sample: the window rows put with ``in_reference``, vectors included.

        Rows come ordered by session ID, then start, then end.

        Args:
            page_size: Maximum number of rows per request, from 1 to 1,000.

        Raises:
            RobotoInvalidRequestException: The space has no window rows, or ``page_size`` is outside 1 to 1,000. It
                surfaces on the first iteration.

        Examples:
            >>> import numpy as np
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.from_id("3f2a" * 16)
            >>> reference = np.array([row.vector for row in space.reference_rows()], dtype=np.float32)
        """
        page_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {"limit": page_size}
            if page_token is not None:
                query["page_token"] = page_token
            page = self.__roboto_client.get(
                f"v1/embeddings/spaces/id/{urllib.parse.quote(self.space_id, safe='')}/reference",
                query=query,
                caller_org_id=self.__record.org_id,
            ).to_paginated_list(EmbeddingRowRecord)
            for row in page.items:
                fields = row.model_dump(
                    include={"session_id", "event_id", "start_ns", "end_ns", "activity", "n_samples"}
                )
                yield EmbeddingRow(**fields, vector=row.vector_values() or [])
            if not page.next_token:
                return
            page_token = page.next_token

    @staticmethod
    def read_rows(
        request: EmbeddingRowsRequest,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator[EmbeddingRowsPage, None, None]:
        """Yield the pages of a rows request, each with the rows and what else the request asked for.

        Besides its rows, each page describes the space they were read from and the sessions the request found, and
        any projection, distances or sample the request asked for. ``get_rows`` reads rows with the common options;
        this method takes every option of ``EmbeddingRowsRequest``, such as a 2-D projection or a stable sample.
        Every exception below surfaces on the first iteration.

        Args:
            request: Rows to read, and what to return with them.
            owner_org_id: Organization that owns the space. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoInvalidRequestException: The request names more sessions than it may, a ``where`` condition or
                label column Roboto cannot apply, a level the space does not hold, or a projection Roboto cannot fit.
            RobotoNotFoundException: The space, or a session the request names, is not the organization's.

        Examples:
            Place a fleet's events on the axes that best set apart a custom field's values:

            >>> from roboto.experimental.embeddings import EmbeddingSpace, EmbeddingRowsRequest
            >>> request = EmbeddingRowsRequest.model_validate(
            ...     {
            ...         "space_id": "3f2a" * 16,
            ...         "level": "event",
            ...         "session_ids": ["se_1", "se_2"],
            ...         "projection": {"method": "discriminant", "separate_by": "custom.verb"},
            ...     }
            ... )
            >>> for page in EmbeddingSpace.read_rows(request):
            ...     for row in page.items:
            ...         x, y = row.vector_values()
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        body = request.model_dump(mode="json", exclude_none=True)
        page_token: typing.Optional[str] = None
        while True:
            page = roboto_client.post(
                "v1/embeddings/rows",
                data=body,
                query=None if page_token is None else {"page_token": page_token},
                caller_org_id=owner_org_id,
            ).to_record(EmbeddingRowsPage)
            yield page
            if not page.next_token:
                return
            page_token = page.next_token

    def get_rows(
        self,
        level: EmbeddingLevel,
        session_ids: typing.Optional[collections.abc.Iterable[str]] = None,
        *,
        scope: typing.Optional[EmbeddingSessionScope] = None,
        where: typing.Optional[dict[str, typing.Any]] = None,
        start_ns: typing.Optional[int] = None,
        end_ns: typing.Optional[int] = None,
        include_vector: bool = False,
        attributes: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> collections.abc.Generator[EmbeddingRowRecord, None, None]:
        """Yield the space's rows at one level across the given sessions, ordered by session, then start.

        Every exception below surfaces on the first iteration.

        Args:
            level: Level of the rows to read: ``window``, ``event`` or ``session``.
            session_ids: IDs of the sessions whose rows to read, at most 100. Give exactly one of ``session_ids`` and
                ``scope``.
            scope: Search that selects the sessions to read, any number of them.
            where: Filter the rows must pass, in the form the ``roboto.experimental.embeddings.search`` module
                describes. ``None`` keeps every row.
            start_ns: Keep only rows that end at or after this time, in nanoseconds since the Unix epoch. ``None``
                sets no lower bound.
            end_ns: Keep only rows that start at or before this time, in the same form. ``None`` sets no upper
                bound.
            include_vector: Whether to return each row's vector; read it with ``EmbeddingRowRecord.vector_values``.
            attributes: Label columns to return with each row, such as ``event_name``, ``session_tags`` or
                ``custom.<field>``, as ``EmbeddingRowsRequest.attributes`` lists them. ``None`` returns none.

        Raises:
            pydantic.ValidationError: Neither or both of ``session_ids`` and ``scope`` are given, ``session_ids``
                holds more than 1,000 sessions, or ``level`` is not one of the three levels.
            RobotoInvalidRequestException: ``session_ids`` holds more than 100 sessions, Roboto cannot apply a
                ``where`` condition or label column, or the space does not hold ``level``.
            RobotoNotFoundException: A session in ``session_ids`` is not the organization's.

        Examples:
            >>> import numpy as np
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.from_id("3f2a" * 16)
            >>> rows = list(space.get_rows("window", ["se_1"], include_vector=True, attributes=["event_name"]))
            >>> vectors = np.array([row.vector_values() for row in rows], dtype=np.float32)
        """
        request = EmbeddingRowsRequest(
            space_id=self.space_id,
            level=level,
            session_ids=None if session_ids is None else builtins.list(session_ids),
            scope=scope,
            where=where,
            start_ns=start_ns,
            end_ns=end_ns,
            include_vector=include_vector,
            attributes=None if attributes is None else builtins.list(attributes),
        )
        for page in EmbeddingSpace.read_rows(request, self.__record.org_id, self.__roboto_client):
            yield from page.items

    @staticmethod
    def find_similar(
        request: EmbeddingSimilarRequest,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> EmbeddingSimilarResponse:
        """Fetch the spans most like a seed across the organization's sessions, nearest first.

        The seed is a stored row, an event, a session or a span of one, or a vector. Each space the request searches
        measures each candidate's distance to the seed, and the hits are ordered by those distances combined.

        Args:
            request: Seed, spaces to search, and conditions a hit must meet.
            owner_org_id: Organization to search. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoInvalidRequestException: The request names a space, weight, seed, level or ``where`` condition the
                search cannot use.
            RobotoNotFoundException: The seed names a session or event that is not the organization's.

        Examples:
            Find the 10 spans most like the first four seconds of a session:

            >>> from roboto.experimental.embeddings import EmbeddingSimilarRequest, EmbeddingSpace
            >>> answer = EmbeddingSpace.find_similar(
            ...     EmbeddingSimilarRequest.model_validate(
            ...         {"seed": {"session_id": "se_1", "start_ns": 0, "end_ns": 4_000_000_000}, "k": 10}
            ...     )
            ... )
            >>> for hit in answer.hits:
            ...     print(hit.rank, hit.session_id, hit.start_ns, hit.distance)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        return roboto_client.post(
            "v1/embeddings/similar",
            data=request.model_dump(mode="json", exclude_none=True),
            caller_org_id=owner_org_id,
        ).to_record(EmbeddingSimilarResponse)

    @staticmethod
    def find_anomalies(
        request: EmbeddingAnomaliesRequest,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> EmbeddingAnomaliesResponse:
        """Fetch what is unusual: regions of sessions that stand out from a reference, or ranked sessions or events.

        At level ``window``, Roboto scores each session as it would score it alone, and a session it cannot score
        carries its reason in ``EmbeddingAnomaliesResponse.sessions`` while the others are answered. At ``session``
        and ``event``, it ranks sessions or events against each other.

        Args:
            request: Sessions or events to score, and what to score them against.
            owner_org_id: Organization to search. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoInvalidRequestException: The request combines arguments, or names a space or ``where`` condition,
                that the scoring cannot use, or no requested session can be scored.
            RobotoNotFoundException: A session in ``session_ids`` is not the organization's.

        Examples:
            Rank a session's unusual regions against the fleet:

            >>> from roboto.experimental.embeddings import EmbeddingAnomaliesRequest, EmbeddingSpace
            >>> answer = EmbeddingSpace.find_anomalies(EmbeddingAnomaliesRequest(session_ids=["se_1"]))
            >>> for region in answer.regions or []:
            ...     print(region.start_ns, region.end_ns, region.percentile)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        return roboto_client.post(
            "v1/embeddings/anomalies",
            data=request.model_dump(mode="json", exclude_none=True),
            caller_org_id=owner_org_id,
        ).to_record(EmbeddingAnomaliesResponse)

    def retire(self) -> EmbeddingSpace:
        """Retire the space, so that readers stop showing it and it takes no new rows.

        Roboto keeps the rows the space holds.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> EmbeddingSpace.from_id("3f2a" * 16).retire()
        """
        return self.__update(UpdateEmbeddingSpaceRequest(retired=True))

    def update(
        self,
        display: typing.Union[dict[str, typing.Any], None, NotSetType] = NotSet,
        producer_state: typing.Union[dict[str, typing.Any], None, NotSetType] = NotSet,
    ) -> EmbeddingSpace:
        """Update the space's ``display`` or ``producer_state``; an argument left unset (``NotSet``) keeps its value.

        What rows are validated against (``kind``, ``dim``, ``levels`` and the window grid) never changes: a producer
        that changes those registers a new space.

        Args:
            display: Details readers show about the space: the keys ``topics``, ``paths`` and ``description``, when
                present. ``None`` clears them.
            producer_state: State the producer reads back on its next run. ``None`` clears it.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> from roboto.experimental.embeddings import EmbeddingSpace
            >>> space = EmbeddingSpace.from_id("3f2a" * 16)
            >>> space.update(producer_state={"basis": [[0.0, 1.0], [1.0, 0.0]]})
        """
        return self.__update(UpdateEmbeddingSpaceRequest(display=display, producer_state=producer_state))

    def __update(self, request: UpdateEmbeddingSpaceRequest) -> EmbeddingSpace:
        record = self.__roboto_client.put(
            f"v1/embeddings/spaces/id/{urllib.parse.quote(self.space_id, safe='')}",
            data=remove_not_set(request),
            caller_org_id=self.__record.org_id,
        ).to_record(EmbeddingSpaceRecord)
        # The response leaves producer_state out, so keep the one this object knows unless this call replaced it.
        self.__record = record.model_copy(
            update={
                "producer_state": (
                    request.producer_state if is_set(request.producer_state) else self.__record.producer_state
                )
            }
        )
        return self

    def __put_inline(self, planned: PlannedBatch) -> EmbeddingBatchRecord:
        request = InlineEmbeddingBatchRequest(
            space_id=self.space_id, sessions=planned.sessions, rows=to_json_rows(planned.table)
        )
        # RobotoClient.post retries this request when a response is lost. Each attempt that reached Roboto records its
        # own batch of the same rows, and writing them all leaves the space as writing one would, because each batch
        # replaces the rows of the sessions it carries.
        return self.__roboto_client.post(
            "v1/embeddings/batches/inline",
            data=request.model_dump(mode="json"),
            caller_org_id=self.__record.org_id,
        ).to_record(EmbeddingBatchRecord)

    def __put_staged(self, planned: PlannedBatch) -> EmbeddingBatchRecord:
        created = self.__roboto_client.post(
            "v1/embeddings/batches",
            data=CreateEmbeddingBatchRequest(space_id=self.space_id, sessions=planned.sessions).model_dump(mode="json"),
            caller_org_id=self.__record.org_id,
        ).to_record(CreateEmbeddingBatchResponse)
        # The URL is presigned: it carries its own authorization, and an Authorization header would be refused.
        HttpClient().put(created.upload_url, data=to_parquet_bytes(planned.table))
        # Committing a batch that is already committing, committed or failed returns it unchanged, so a commit that
        # RobotoClient.post retries after a lost response writes nothing twice.
        return self.__roboto_client.post(
            f"v1/embeddings/batches/id/{urllib.parse.quote(created.batch_id, safe='')}/commit",
            caller_org_id=self.__record.org_id,
        ).to_record(EmbeddingBatchRecord)

    def __wait_until_written(self, batch: EmbeddingBatchRecord, timeout_s: float) -> EmbeddingBatchRecord:
        latest = batch

        def finished() -> bool:
            nonlocal latest
            if latest.status not in _FINISHED:
                latest = self.get_batch(batch.batch_id)
            return latest.status in _FINISHED

        wait_for(
            finished,
            timeout=timeout_s,
            interval=lambda iteration: min(2 ** (iteration - 1), 10),
            timeout_msg=f"Embedding batch {batch.batch_id} was not written within {timeout_s} seconds.",
        )
        return latest


def _read_coverage(
    roboto_client: RobotoClient,
    space_id: str,
    session_ids: collections.abc.Iterable[str],
    caller_org_id: typing.Optional[str],
) -> dict[str, EmbeddingSessionCoverageRecord]:
    unique = builtins.list(dict.fromkeys(session_ids))
    found: dict[str, EmbeddingSessionCoverageRecord] = {}
    for start in range(0, len(unique), COVERAGE_SESSIONS_PER_REQUEST):
        chunk = unique[start : start + COVERAGE_SESSIONS_PER_REQUEST]
        # Encoded here because RobotoClient's query argument sends a list as its string form, not as one
        # `session_ids=` parameter per session.
        query = urllib.parse.urlencode({"space_id": space_id, "session_ids": chunk}, doseq=True)
        response = roboto_client.get(f"v1/embeddings/coverage?{query}", caller_org_id=caller_org_id)
        found.update(response.to_record(EmbeddingCoverageResponse).sessions)
    return found
