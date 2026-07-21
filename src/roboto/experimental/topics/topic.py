# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import concurrent.futures
import pathlib
import typing

import pydantic

from ...compat import import_optional_dependency
from ...config import resolve_cache_dir
from ...domain.topics import (
    RepresentationStorageFormat,
    SchemaFieldRecord,
    Timestamp,
    TopicIdentityRecord,
)
from ...env import RobotoEnv
from ...exceptions import RobotoInternalException
from ...http import RobotoClient
from ...storage import CachePolicy
from ...time import Time, to_epoch_nanoseconds
from . import batch_transforms, plan_execution
from .decode import (
    CACHED_PARQUET_NAME_PATTERN,
    ScanTaskDecodeParams,
    make_scan_task_decoder,
)
from .operations import (
    FieldAddress,
    ReadPlanRequest,
    RepresentationPreference,
)
from .read_plan import ReadPlan

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep
    import pyarrow  # pants: no-infer-dep

FieldAddressLike = typing.Union[FieldAddress, collections.abc.Sequence[str]]
"""A field-subtree address, as a :py:class:`~roboto.experimental.topics.FieldAddress`
or explicit path components (``("pose", "position")`` for a nested field,
``("angular_velocity",)`` for a top-level one).

Each component is one ``path_in_schema`` element; there is no string delimiter, so
a component may itself contain a ``.``. A bare string is rejected even though it is
structurally a ``Sequence[str]`` — splitting it on ``.`` would guess at component
boundaries, and iterating it would address one field per character; pass the
components explicitly instead."""

TOPIC_DATA_CACHE_SUBDIR = "topic-data"
"""Subdirectory of the client's cache directory where fetched topic data files are cached."""

_MAX_SIGNED_URL_WORKERS = 32
"""Upper bound on the thread pool that mints scan-task signed URLs concurrently.

Minting is a pure network wait, so the bound follows the stdlib's
I/O-oriented executor default of 32 rather than scaling with core count."""


class SessionContext(pydantic.BaseModel):
    """The Session a Topic is scoped to: limits topic operations to the Session's associated files
    and supplies the Session's aggregate time window as the default window for those operations."""

    model_config = pydantic.ConfigDict(frozen=True)

    session_id: str

    start_time: typing.Optional[int] = None
    """Earliest time covered by the Session (Unix-epoch ns);
    the default start_time for get_data*. None when the Session includes no files."""

    end_time: typing.Optional[int] = None
    """Latest time covered by the Session (Unix-epoch ns);
    the default end_time for get_data*. None when the Session includes no files."""


class Topic:
    """A logical stream of robotics data, identified durably across the files that carry it.

    Within an organization, topic names are unique;
    contributions from different files with the same topic name share a single topic identity.
    By default a ``Topic`` reads org-wide and its data-returning methods require an explicit time window.

    A ``Topic`` carrying a :py:class:`SessionContext`
    —e.g., yielded by :py:meth:`~roboto.experimental.sessions.Session.list_topics`,
    or  :py:meth:`~roboto.experimental.sessions.Session.get_topic`—
    instead scopes topic operations like `get_data*`` to that Session's files and defaults the
    window to the Session's aggregate bounds.
    """

    __record: TopicIdentityRecord
    __roboto_client: RobotoClient
    __session_context: typing.Optional[SessionContext]

    @classmethod
    def from_id(
        cls,
        topic_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        session_context: typing.Optional[SessionContext] = None,
    ) -> Topic:
        """Load an existing topic by its id.

        Args:
            topic_id: Identifier of the topic (``ti_*``).
            owner_org_id: Organization that owns the topic. If omitted,
                defaults to the caller's organization.
            roboto_client: Roboto client instance. Uses the default if omitted.
            session_context: Optional. When provided, scopes topic operations to the
                session's files and defaults the read window to the session's
                bounds. ``None`` reads org-wide.

        Returns:
            The loaded topic.

        Raises:
            RobotoNotFoundException: No topic with this id exists in the org.
            RobotoUnauthorizedException: The caller cannot search topics in the org.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> topic.name
            '/camera/image_raw'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v2/topics/id/{topic_id}",
            owner_org_id=owner_org_id,
        ).to_record(TopicIdentityRecord)
        return cls(record, roboto_client, session_context=session_context)

    @classmethod
    def from_record(
        cls,
        record: TopicIdentityRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        session_context: typing.Optional[SessionContext] = None,
    ) -> Topic:
        """Wrap an already-loaded topic identity record.

        Args:
            record: The topic identity record to wrap.
            roboto_client: Roboto client instance. Uses the default if omitted.
            session_context: Optional session scope; see :py:meth:`from_id`.

        Returns:
            A topic backed by ``record``, with no further service calls.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_record(record)
            >>> topic.topic_id  # doctest: +SKIP
            'ti_abc123'
        """
        return cls(record, RobotoClient.defaulted(roboto_client), session_context=session_context)

    def __init__(
        self,
        record: TopicIdentityRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        session_context: typing.Optional[SessionContext] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__session_context = session_context

    def __repr__(self) -> str:
        if self.__session_context is None:
            return self.__record.model_dump_json()
        return f"Topic(record={self.__record.model_dump_json()}, session_context={self.__session_context!r})"

    @property
    def context(self) -> typing.Optional[SessionContext]:
        return self.__session_context

    @property
    def name(self) -> str:
        """Human-readable topic name (e.g. ``"/camera/image_raw"``). Unique within an organization."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """Identifier of the organization that owns this topic."""
        return self.__record.org_id

    @property
    def record(self) -> TopicIdentityRecord:
        """The underlying topic identity record."""
        return self.__record

    @property
    def topic_id(self) -> str:
        """Durable identifier of this topic (``ti_*``)."""
        return self.__record.topic_id

    def get_data(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        fields_include: typing.Optional[collections.abc.Iterable[FieldAddressLike]] = None,
        fields_exclude: typing.Optional[collections.abc.Iterable[FieldAddressLike]] = None,
        prefer: typing.Optional[RepresentationPreference] = None,
        schema_id: typing.Optional[str] = None,
        schema_checksum: typing.Optional[str] = None,
        timeline_source_id: typing.Optional[str] = None,
        timeline_source_name: typing.Optional[str] = None,
        cache_policy: CachePolicy = CachePolicy.ADAPTIVE,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield this topic's data within a time window, as ``(timestamp, record)`` pairs.

        Convenience over :py:meth:`get_data_as_record_batches` that unpacks each
        Arrow RecordBatch into one ``(timestamp, record)`` tuple per row.
        ``timestamp`` is the row's absolute Unix-epoch nanosecond timestamp (an
        ``int``); ``record`` is a ``dict`` of the projected fields, with
        struct fields as nested dicts and list fields as lists.
        A field the data omits for a row is absent from (or null within) that row's dict.

        Time windowing, field projection, representation selection, sort order,
        and error behavior are all as documented on :py:meth:`get_data_as_record_batches`.

        Requires the ``roboto[analytics]`` extra.

        Args:
            start_time: See :py:meth:`get_data_as_record_batches`.
            end_time: See :py:meth:`get_data_as_record_batches`.
            fields_include: See :py:meth:`get_data_as_record_batches`.
            fields_exclude: See :py:meth:`get_data_as_record_batches`.
            prefer: See :py:meth:`get_data_as_record_batches`.
            schema_id: See :py:meth:`get_data_as_record_batches`.
            schema_checksum: See :py:meth:`get_data_as_record_batches`.
            timeline_source_id: See :py:meth:`get_data_as_record_batches`.
            timeline_source_name: See :py:meth:`get_data_as_record_batches`.
            cache_policy: See :py:meth:`get_data_as_record_batches`.
            cache_dir: See :py:meth:`get_data_as_record_batches`.

        Yields:
            ``(timestamp, record)`` tuples for the in-window rows, filtered and
            projected per the arguments.

        Raises:
            RobotoInvalidRequestException: See :py:meth:`get_data_as_record_batches`.
            RobotoUnauthorizedException: See :py:meth:`get_data_as_record_batches`.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> for timestamp, record in topic.get_data(start_time=t0, end_time=t1):
            ...     print(timestamp, record)
        """
        for batch in self.get_data_as_record_batches(
            start_time=start_time,
            end_time=end_time,
            fields_include=fields_include,
            fields_exclude=fields_exclude,
            prefer=prefer,
            schema_id=schema_id,
            schema_checksum=schema_checksum,
            timeline_source_id=timeline_source_id,
            timeline_source_name=timeline_source_name,
            cache_policy=cache_policy,
            cache_dir=cache_dir,
        ):
            timestamp_index = batch_transforms.timestamp_column_index(batch.schema)
            timestamps = batch.column(timestamp_index).to_pylist()
            field_names = [
                batch.schema.field(index).name for index in range(batch.num_columns) if index != timestamp_index
            ]
            rows = batch.select(field_names).to_pylist() if field_names else [{} for _ in timestamps]
            yield from zip(timestamps, rows)

    def get_data_as_record_batches(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        fields_include: typing.Optional[collections.abc.Iterable[FieldAddressLike]] = None,
        fields_exclude: typing.Optional[collections.abc.Iterable[FieldAddressLike]] = None,
        prefer: typing.Optional[RepresentationPreference] = None,
        schema_id: typing.Optional[str] = None,
        schema_checksum: typing.Optional[str] = None,
        timeline_source_id: typing.Optional[str] = None,
        timeline_source_name: typing.Optional[str] = None,
        cache_policy: CachePolicy = CachePolicy.ADAPTIVE,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator["pyarrow.RecordBatch", None, None]:
        """Yield this topic's data within a time window, as Arrow RecordBatches.

        Each batch carries one column per top-level projected field, with nested
        struct and list types mirroring the topic's schema, pruned to the
        projection, plus a dedicated ``int64`` column of Unix-epoch nanosecond
        timestamps; locate that column with :py:func:`~roboto.experimental.topics.timestamp_column_index`.
        A field the data omits for a row surfaces as null at the deepest level that
        represents the omission (a whole absent subtree is a single null).

        Batch sizes and boundaries carry no meaning, and a window matching no rows yields no batches.
        A topic's data can span several files ("topic partitions");
        rows from different partitions are never mixed within a batch.
        Partitions arrive ordered by where each file's data begins.
        Within a partition, rows keep their stored order, and rows from different partitions are never interleaved.
        So batches arrive as whole partitions in start order, not as a globally time-sorted row stream.
        Sort downstream if a strict row-level time order is needed.

        Requires the ``roboto[analytics]`` extra.

        Args:
            start_time: Inclusive window lower bound, as nanoseconds since the
                Unix epoch or anything convertible via :py:func:`~roboto.time.to_epoch_nanoseconds`.
                ``None`` defaults to the session's lower bound when this topic was obtained from
                :py:meth:`~roboto.experimental.sessions.Session.list_topics` or
                :py:meth:`~roboto.experimental.sessions.Session.get_topic`;
                otherwise required (a ``ValueError`` is raised when it cannot be resolved).
            end_time: Inclusive window upper bound, same forms as ``start_time``;
                defaults to the session's upper bound on the same terms.
            fields_include: Field subtrees to project. ``None`` projects every field.
            fields_exclude: Field subtrees to drop from the projection. ``None`` drops none.
            prefer: Preferred representation per field subtree, selecting which
                stored variant of a field to read. ``None`` applies the default
                selection everywhere.
            schema_id: Schema to read under, by id. Required only when the
                window spans data with more than one schema.
            schema_checksum: Schema to read under, by checksum. Mutually
                exclusive with ``schema_id``.
            timeline_source_id: Timeline source to resolve the window with, by
                id. ``None`` uses each schema's default source.
            timeline_source_name: Timeline source by name. Mutually exclusive
                with ``timeline_source_id``.
            cache_policy: Whether fetched Parquet files are cached to local
                disk. MCAP data always streams.
            cache_dir: Directory topic data files are cached under. Defaults
                to a ``topic-data`` subdirectory of ``ROBOTO_CACHE_DIR``, or
                the platform-conventional per-user cache directory when that is
                unset.

        Yields:
            :py:class:`pyarrow.RecordBatch` instances holding the in-window
            rows, filtered and projected per the arguments.

        Raises:
            RobotoInvalidRequestException: The window spans multiple schemas and
                none was chosen with ``schema_id`` or ``schema_checksum``, a named
                schema or timeline source does not match the window's data, or no
                stored representation satisfies a representation preference. The
                error carries an actionable message.
            RobotoUnauthorizedException: The caller lacks read access to at
                least one in-window file backing this topic.

        Examples:
            Print every record in a window:

            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> for batch in topic.get_data_as_record_batches(start_time=t0, end_time=t1):
            ...     print(batch.num_rows, batch.schema.names)

            Project to one field subtree, dropping one of its children:

            >>> for batch in topic.get_data_as_record_batches(
            ...     start_time=t0,
            ...     end_time=t1,
            ...     fields_include=[("angular_velocity",)],
            ...     fields_exclude=[("angular_velocity", "y")],
            ... ):
            ...     print(batch.to_pylist())
        """
        plan = self.__resolve_read_plan(
            start_time=start_time,
            end_time=end_time,
            fields_include=fields_include,
            fields_exclude=fields_exclude,
            prefer=prefer,
            schema_id=schema_id,
            schema_checksum=schema_checksum,
            timeline_source_id=timeline_source_id,
            timeline_source_name=timeline_source_name,
        )
        if not plan.partitions:
            return

        schema_fields = self.__fetch_schema_fields(plan)
        projection_paths = _resolve_projection_paths(plan, schema_fields)

        resolved_cache_dir = (
            pathlib.Path(cache_dir)
            if cache_dir is not None
            # A fresh RobotoEnv reads ROBOTO_CACHE_DIR as of this call, falling back to the
            # platform-conventional per-user cache directory; ensure_exists=False never creates it.
            else resolve_cache_dir(RobotoEnv(), ensure_exists=False) / TOPIC_DATA_CACHE_SUBDIR
        )

        # Mint every scan task's signed URL concurrently, each decode worker blocks only on its own URL's future.
        url_executor, url_futures = self.__prefetch_signed_urls(plan, cache_policy, resolved_cache_dir)
        try:

            def signed_url_resolver(fs_node_id: str) -> str:
                future = url_futures.get(fs_node_id)
                return future.result() if future is not None else self.__signed_url_for_file(fs_node_id)

            decoder = make_scan_task_decoder(
                ScanTaskDecodeParams(
                    signed_url_resolver=signed_url_resolver,
                    cache_policy=cache_policy,
                    cache_dir=resolved_cache_dir,
                )
            )

            yield from plan_execution.execute_plan(plan, projection_paths, decoder)
        finally:
            if url_executor is not None:
                url_executor.shutdown(wait=False, cancel_futures=True)

    def get_data_as_df(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        fields_include: typing.Optional[collections.abc.Iterable[FieldAddressLike]] = None,
        fields_exclude: typing.Optional[collections.abc.Iterable[FieldAddressLike]] = None,
        prefer: typing.Optional[RepresentationPreference] = None,
        schema_id: typing.Optional[str] = None,
        schema_checksum: typing.Optional[str] = None,
        timeline_source_id: typing.Optional[str] = None,
        timeline_source_name: typing.Optional[str] = None,
        flatten: bool = False,
        cache_policy: CachePolicy = CachePolicy.ADAPTIVE,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> pandas.DataFrame:
        """Return this topic's data within a time window as a pandas DataFrame.

        Same pipeline as :py:meth:`get_data_as_record_batches`, with the batches
        packed into a DataFrame whose index is a timezone-aware ``DatetimeIndex``.

        Rows return ordered by partition (each file's data in start order), not interleaved across partitions;
        within a partition rows keep their stored order.
        Call ``df.sort_index()`` for a strict row-level time-ordered view.

        A struct field is returned as a single schema-shaped column of dicts unless ``flatten`` is set,
        which expands every struct level into dot-delimited leaf columns (e.g. ``pose.position.x``).
        List-typed fields are unaffected by ``flatten``.

        Read parameters and error behavior are as documented on :py:meth:`get_data_as_record_batches`.

        Requires the ``roboto[analytics]``extra.

        Args:
            start_time: See :py:meth:`get_data_as_record_batches`.
            end_time: See :py:meth:`get_data_as_record_batches`.
            fields_include: See :py:meth:`get_data_as_record_batches`.
            fields_exclude: See :py:meth:`get_data_as_record_batches`.
            prefer: See :py:meth:`get_data_as_record_batches`.
            schema_id: See :py:meth:`get_data_as_record_batches`.
            schema_checksum: See :py:meth:`get_data_as_record_batches`.
            timeline_source_id: See :py:meth:`get_data_as_record_batches`.
            timeline_source_name: See :py:meth:`get_data_as_record_batches`.
            flatten: Expand struct-typed fields into dot-delimited leaf columns.
                When ``False``, each struct-typed field is a single object-dtype column of dicts.
            cache_policy: See :py:meth:`get_data_as_record_batches`.
            cache_dir: See :py:meth:`get_data_as_record_batches`.

        Returns:
            DataFrame of the in-window rows indexed by a timezone-aware ``DatetimeIndex``.

        Raises:
            RobotoInvalidRequestException: See :py:meth:`get_data_as_record_batches`.
            RobotoUnauthorizedException: See :py:meth:`get_data_as_record_batches`.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> df = topic.get_data_as_df(start_time=t0, end_time=t1)
        """
        pa = import_optional_dependency("pyarrow", "analytics")
        pd = import_optional_dependency("pandas", "analytics")

        batches = list(
            self.get_data_as_record_batches(
                start_time=start_time,
                end_time=end_time,
                fields_include=fields_include,
                fields_exclude=fields_exclude,
                prefer=prefer,
                schema_id=schema_id,
                schema_checksum=schema_checksum,
                timeline_source_id=timeline_source_id,
                timeline_source_name=timeline_source_name,
                cache_policy=cache_policy,
                cache_dir=cache_dir,
            )
        )

        if not batches:
            # With no batches there is no schema to build columns from: the
            # frame is empty and column-less, carrying only the index shape.
            df = pd.DataFrame()
            df = df.set_index(pd.to_datetime([], unit="ns", utc=True))
            df.index.name = "_index"
            return df

        # Batch schemas may differ across partitions and chunks (batch
        # boundaries carry no meaning); permissive promotion unifies them.
        table = pa.concat_tables(
            (pa.Table.from_batches([batch]) for batch in batches),
            promote_options="permissive",
        )
        timestamp_index = batch_transforms.timestamp_column_index(table.schema)
        timestamps = table.column(timestamp_index)
        body = table.remove_column(timestamp_index)
        if flatten:
            body = batch_transforms.flatten_table(body)

        df = body.to_pandas()
        df = df.set_index(pd.to_datetime(timestamps.to_pylist(), unit="ns", utc=True))
        df.index.name = "_index"
        return df

    def set_context(self, session_context: typing.Optional[SessionContext]) -> None:
        self.__session_context = session_context

    def __fetch_schema_fields(self, plan: ReadPlan) -> list[SchemaFieldRecord]:
        """Fetch every declared field for the plan's schema."""
        if plan.schema_ is None:
            # The plan model documents `schema` as set exactly when the plan is
            # non-empty, and the caller only gets here with partitions present.
            raise RobotoInternalException("Read plan has partitions but names no schema.")

        return self.__roboto_client.get(
            f"v2/topics/schema/id/{plan.schema_.schema_id}/fields",
            owner_org_id=self.org_id,
        ).to_record_list(SchemaFieldRecord)

    def __resolve_read_plan(
        self,
        start_time: typing.Optional[Time],
        end_time: typing.Optional[Time],
        fields_include: typing.Optional[collections.abc.Iterable[FieldAddressLike]],
        fields_exclude: typing.Optional[collections.abc.Iterable[FieldAddressLike]],
        prefer: typing.Optional[RepresentationPreference],
        schema_id: typing.Optional[str],
        schema_checksum: typing.Optional[str],
        timeline_source_id: typing.Optional[str],
        timeline_source_name: typing.Optional[str],
    ) -> ReadPlan:
        start_ns = (
            to_epoch_nanoseconds(start_time)
            if start_time is not None
            else (self.__session_context.start_time if self.__session_context else None)
        )
        end_ns = (
            to_epoch_nanoseconds(end_time)
            if end_time is not None
            else (self.__session_context.end_time if self.__session_context else None)
        )
        if start_ns is None or end_ns is None:
            raise ValueError(
                "start_time and end_time are required; they default to the session's time window only "
                "for a topic obtained from Session.list_topics() or Session.get_topic() "
                "(and only when that session has bounds)."
            )
        request = ReadPlanRequest(
            start_time=start_ns,
            end_time=end_ns,
            fields_include=_coerce_field_addresses(fields_include),
            fields_exclude=_coerce_field_addresses(fields_exclude),
            prefer=prefer,
            schema_id=schema_id,
            schema_checksum=schema_checksum,
            timeline_source_id=timeline_source_id,
            timeline_source_name=timeline_source_name,
            session_id=self.__session_context.session_id if self.__session_context else None,
        )
        return self.__roboto_client.post(
            f"v2/topics/id/{self.topic_id}/read-plan",
            data=request,
            owner_org_id=self.org_id,
        ).to_record(ReadPlan)

    def __prefetch_signed_urls(
        self,
        plan: ReadPlan,
        cache_policy: CachePolicy,
        cache_dir: pathlib.Path,
    ) -> tuple[typing.Optional[concurrent.futures.ThreadPoolExecutor], dict[str, concurrent.futures.Future[str]]]:
        """Start minting, concurrently, the signed URLs every scan task will need.

        Returns the minting executor (``None`` when nothing needs a URL) and one
        future per file id; the caller blocks on individual futures as decode
        reaches each file, and owns shutting the executor down.

        A Parquet scan task whose file is already in the local cache is read
        from disk and never mints a URL, so it is skipped here to avoid a wasted
        round trip; MCAP always streams and always needs one. The decode-time
        resolver falls back to a direct mint for any id missing from this map, so
        a skipped file that nonetheless ends up streaming stays correct.
        """
        fs_node_ids: set[str] = set()
        for partition in plan.partitions:
            for scan_task in partition.scan_tasks:
                fs_node_id = scan_task.object.fs_node_id
                if scan_task.format == RepresentationStorageFormat.PARQUET:
                    cached_outfile = cache_dir / CACHED_PARQUET_NAME_PATTERN.format(fs_node_id=fs_node_id)
                    if cache_policy is not CachePolicy.NEVER and cached_outfile.exists():
                        continue
                fs_node_ids.add(fs_node_id)

        if not fs_node_ids:
            return None, {}

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_SIGNED_URL_WORKERS, len(fs_node_ids)))
        return executor, {
            fs_node_id: executor.submit(self.__signed_url_for_file, fs_node_id) for fs_node_id in fs_node_ids
        }

    def __signed_url_for_file(self, fs_node_id: str) -> str:
        response = self.__roboto_client.get(f"v1/files/{fs_node_id}/signed-url")
        return response.to_dict(json_path=["data", "url"])


def _resolve_projection_paths(
    plan: ReadPlan, schema_fields: collections.abc.Sequence[SchemaFieldRecord]
) -> list[tuple[str, ...]]:
    """Materialize the plan's projection as explicit field paths.

    A narrowed projection enumerates its paths inline; the whole-schema sentinel
    takes every declared field's path.
    """
    if plan.projection.all:
        return [record.path_in_schema for record in schema_fields]
    return [field.path for field in plan.projection.fields or ()]


def _coerce_field_addresses(
    addresses: typing.Optional[collections.abc.Iterable[FieldAddressLike]],
) -> typing.Optional[tuple[FieldAddress, ...]]:
    if addresses is None:
        return None
    coerced: list[FieldAddress] = []
    for address in addresses:
        if isinstance(address, FieldAddress):
            coerced.append(address)
        elif isinstance(address, str):
            # A str is structurally a Sequence[str], so it would coerce silently —
            # splitting on "." would guess component boundaries, and tuple(address)
            # would address one field per character. Reject it loudly instead.
            raise TypeError(
                "field address must be given as its path components, not a string; "
                f"pass a tuple such as {tuple(address.split('.'))!r} (or a FieldAddress) instead of {address!r}"
            )
        else:
            coerced.append(FieldAddress(path=tuple(address)))
    return tuple(coerced)
