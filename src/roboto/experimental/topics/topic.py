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
    TimelineExtentRecord,
    Timestamp,
    TopicIdentityRecord,
)
from ...domain.topics.record import FieldPath
from ...env import RobotoEnv
from ...http import RobotoClient
from ...storage import CachePolicy
from ...time import Time, to_epoch_nanoseconds
from . import batch_transforms, plan_execution
from .decode import (
    CACHED_PARQUET_NAME_PATTERN,
    FileDecodeParams,
    make_file_decoder_opener,
)
from .operations import (
    FieldAddress,
    ReadPlanRequest,
    RepresentationPreference,
    SetTopicUnixOffsetRequest,
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


class FileContext(pydantic.BaseModel):
    """The file a Topic is scoped to: limits topic operations to the topic's data in that file.

    An omitted ``start_time`` or ``end_time`` defaults to the start or end of the topic's data in the file, resolved by
    the service when the data is read."""

    model_config = pydantic.ConfigDict(frozen=True)

    file_id: str


class DatasetContext(pydantic.BaseModel):
    """The dataset a Topic is scoped to: limits topic operations to the topic's data in the dataset's files.

    An omitted ``start_time`` or ``end_time`` defaults to the start or end of the topic's data in those files,
    resolved by the service when the data is read."""

    model_config = pydantic.ConfigDict(frozen=True)

    dataset_id: str


class DeviceContext(pydantic.BaseModel):
    """The device a Topic is scoped to: limits topic operations to the topic's data in the device's files.

    A file belongs to the device it names, or, when it names none, to the device its dataset names. An omitted
    ``start_time`` or ``end_time`` defaults to the start or end of the topic's data in those files, resolved by the
    service when the data is read."""

    model_config = pydantic.ConfigDict(frozen=True)

    device_id: str


TopicContext = typing.Union[SessionContext, FileContext, DatasetContext, DeviceContext]
"""The scope a :py:class:`Topic` reads within: one Session, file, dataset or device."""


class Topic:
    """A logical stream of robotics data, identified durably across the files that carry it.

    Within an organization, topic names are unique;
    contributions from different files with the same topic name share a single topic identity.
    By default a ``Topic`` reads org-wide and its data-returning methods require an explicit time window.

    A ``Topic`` carrying a :py:data:`TopicContext` instead scopes topic operations like ``get_data*`` to the
    topic's data in that context, and never reads the topic's data elsewhere.

    * A :py:class:`SessionContext`, as on a Topic yielded by
      :py:meth:`~roboto.experimental.sessions.Session.list_topics` or
      :py:meth:`~roboto.experimental.sessions.Session.get_topic`,
      scopes to that Session's files and defaults the window to the span of time the Session covers.
    * A :py:class:`FileContext`, :py:class:`DatasetContext` or :py:class:`DeviceContext` scopes to that file, to that
      dataset's files, or to that device's files, and defaults the window to the start and end of the topic's data
      there.

    A Topic's context is fixed when it is built.
    """

    __context: typing.Optional[TopicContext]
    __record: TopicIdentityRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        context: typing.Optional[TopicContext] = None,
    ) -> Topic:
        """Load an existing topic by its id.

        Args:
            topic_id: Identifier of the topic (``ti_*``).
            roboto_client: Roboto client instance. Uses the default if omitted.
            context: Optional. When provided, limits topic operations to the topic's data in one Session, file,
                dataset or device, and supplies the default read window, as described on :py:class:`Topic`.
                ``None`` reads org-wide.

        Returns:
            The loaded topic.

        Raises:
            RobotoNotFoundException: No topic with this id exists.
            RobotoUnauthorizedException: The caller lacks topic view access in the org that owns the topic.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> topic.name
            '/camera/image_raw'

            Read all of the topic's data in one file:

            >>> from roboto.experimental.topics import FileContext
            >>> file_topic = Topic.from_id("ti_abc123", context=FileContext(file_id="fl_abc123"))
            >>> rows = list(file_topic.get_data())
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v2/topics/id/{topic_id}",
        ).to_record(TopicIdentityRecord)
        return cls(record, roboto_client, context=context)

    @classmethod
    def from_record(
        cls,
        record: TopicIdentityRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        context: typing.Optional[TopicContext] = None,
    ) -> Topic:
        """Wrap an already-loaded topic identity record.

        Args:
            record: The topic identity record to wrap.
            roboto_client: Roboto client instance. Uses the default if omitted.
            context: Optional scope; see :py:meth:`from_id`.

        Returns:
            A topic backed by ``record``, with no further service calls.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_record(record)
            >>> topic.topic_id  # doctest: +SKIP
            'ti_abc123'
        """
        return cls(record, RobotoClient.defaulted(roboto_client), context=context)

    def __init__(
        self,
        record: TopicIdentityRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        context: typing.Optional[TopicContext] = None,
    ):
        self.__context = context
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        if self.__context is None:
            return self.__record.model_dump_json()
        return f"Topic(record={self.__record.model_dump_json()}, context={self.__context!r})"

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

    def clear_unix_offset(self) -> list[TimelineExtentRecord]:
        """Return this Topic's data in its Session to an offset of 0.

        Its stored timestamps are then read as nanoseconds since the Unix epoch with nothing added.
        This call reaches the same data as :py:meth:`set_unix_offset`, and a file's declared time range in
        the Session moves back under the same condition: only when everything that range covers moved by
        the same distance.

        Returns:
            One :py:class:`~roboto.domain.topics.TimelineExtentRecord` per timeline extent whose offset
            changed. An extent already at an offset of 0 is left untouched and absent from the list, so
            an empty list means there was no anchor to clear.

        Raises:
            ValueError: This Topic carries no Session context; see :py:meth:`set_unix_offset`.
            RobotoInvalidRequestException: Some of this Topic's own timestamps are negative, so an offset of 0
                would place that data before the Unix epoch; or a time range declared over the data would start
                before the epoch once moved back with it.
            RobotoConflictException: A concurrent writer added files to the Session while the offset
                was being cleared; retry the call.
            RobotoNotFoundException: The Session does not exist, or holds no data for this Topic.
            RobotoUnauthorizedException: The caller cannot view the Session, or cannot edit some
                file behind the data being written.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> session = Session.from_id("se_abc123")  # doctest: +SKIP
            >>> topic = session.get_topic("/camera/image_raw")  # doctest: +SKIP
            >>> topic.clear_unix_offset()  # doctest: +SKIP
        """
        return self.__roboto_client.delete(
            f"v2/topics/id/{self.topic_id}/unix-offset",
            query={"session_id": self.__require_session_id("clear_unix_offset")},
        ).to_record_list(TimelineExtentRecord)

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
            RobotoNotFoundException: See :py:meth:`get_data_as_record_batches`.
            RobotoInvalidRequestException: See :py:meth:`get_data_as_record_batches`.
            RobotoReadPlanExecutionException: See :py:meth:`get_data_as_record_batches`.
            RobotoInternalException: See :py:meth:`get_data_as_record_batches`.
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
            flatten: Expand struct-typed fields into dot-delimited leaf columns.
                When ``False``, each struct-typed field is a single object-dtype column of dicts.
            cache_policy: See :py:meth:`get_data_as_record_batches`.
            cache_dir: See :py:meth:`get_data_as_record_batches`.

        Returns:
            DataFrame of the in-window rows indexed by a timezone-aware ``DatetimeIndex``.

        Raises:
            RobotoNotFoundException: See :py:meth:`get_data_as_record_batches`.
            RobotoInvalidRequestException: See :py:meth:`get_data_as_record_batches`.
            RobotoReadPlanExecutionException: See :py:meth:`get_data_as_record_batches`.
            RobotoInternalException: See :py:meth:`get_data_as_record_batches`.
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

        Batch sizes and boundaries carry no meaning, and a window matching no rows yields no batches, as does a
        context holding no data for the topic.
        A topic's data can span several files ("topic partitions");
        rows from different partitions are never mixed within a batch.
        Partitions arrive ordered by when each file's data begins.
        Within a partition, rows keep their stored order, and rows from different partitions are never interleaved.
        So batches arrive as whole partitions in start order, not as a globally time-sorted row stream.
        Sort downstream if a strict row-level time order is needed.

        Requires the ``roboto[analytics]`` extra.

        Args:
            start_time: Inclusive window lower bound, as nanoseconds since the
                Unix epoch or anything convertible via :py:func:`~roboto.time.to_epoch_nanoseconds`.
                ``None`` defaults to the start of the topic's data in this topic's file, dataset or device context,
                or to the earliest time the Session covers in a :py:class:`SessionContext` (such as on a topic
                obtained from :py:meth:`~roboto.experimental.sessions.Session.list_topics` or
                :py:meth:`~roboto.experimental.sessions.Session.get_topic`);
                otherwise required (a ``ValueError`` is raised when it cannot be resolved).
                An explicit bound narrows the read within the context and never widens it.
            end_time: Inclusive window upper bound, same forms as ``start_time``;
                defaults to the end of the topic's data, or to the latest time the Session covers, on the same terms.
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
            RobotoNotFoundException: This topic's file or dataset context names a file or dataset that does not
                exist.
            RobotoInvalidRequestException: The window spans multiple schemas and
                none was chosen with ``schema_id`` or ``schema_checksum``, a named
                schema or timeline source does not match the window's data, no
                stored representation satisfies a representation preference, or
                ``fields_include`` and ``fields_exclude`` together select no field.
                The error carries an actionable message.
            RobotoReadPlanExecutionException: The topic's data cannot be read as the service's read plan describes
                it; a ``RobotoInternalException`` whose ``kind`` says why:

                * ``field-not-in-file``: a file backing this topic lacks a field the read takes from it, such as a
                  projected field or the field holding each row's timestamp. ``field_path`` runs from that field's
                  top-level field down to the first component the file lacks.
                * ``unsupported-timestamp``: the read cannot take timestamps from where the data keeps them, such as
                  a message time on a Parquet file, or a Parquet timestamp field that is not a number.
                * ``invalid-timestamp``: a stored timestamp is NaN or infinite, is a DECIMAL holding a fraction of a
                  nanosecond, or leaves the signed 64-bit range once shifted to absolute time. ``row_number`` names
                  the row by its 0-based position among the topic's rows in its file.
                * ``scan-task-row-mismatch``: files that store different fields of the same rows hold different rows
                  in the window.
                * ``field-split-inside-non-struct``: files that store different fields of the same rows split a field
                  that one of them stores as other than a struct, such as a list or a map.
                * ``projected-field-in-no-scan-task``: no scan task of a topic partition reads the whole schema or a
                  subtree containing a projected field.
                * ``inconsistent-scan-tasks-on-file``: the plan reads one file two ways, with a different format,
                  transformations or topic name.
                * ``partition-schema-mismatch``: a topic partition's files give the read a different schema than the
                  first topic partition's files. It is raised when that partition's files open, before any of its
                  rows, so even when it has no rows in the window.
                * ``plan-without-schema``: the plan reads every field of its schema and has a topic partition with a
                  scan task, but names no schema.
                * ``data-range-not-in-file``: a topic partition's declared slice of its file (``data_range``) ends
                  past the file's stored row count, so the slice does not match the file.
            RobotoInternalException: An MCAP file backing this topic cannot be decoded, such as one with no chunk or
                message index, or one whose messages are ``protobuf``-encoded.
            RobotoUnauthorizedException: The caller lacks read access to at
                least one in-window file backing this topic, or cannot view the file or dataset this topic's
                context names.

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

        projected = plan_execution.projected_paths(plan, self.__schema_field_paths)

        resolved_cache_dir = (
            pathlib.Path(cache_dir)
            if cache_dir is not None
            # A fresh RobotoEnv reads ROBOTO_CACHE_DIR as of this call, falling back to the
            # platform-conventional per-user cache directory; ensure_exists=False never creates it.
            else resolve_cache_dir(RobotoEnv(), ensure_exists=False) / TOPIC_DATA_CACHE_SUBDIR
        )

        # Mint every scan task's signed URL concurrently; each decode worker blocks only on its own URL's future.
        url_executor, url_futures = self.__prefetch_signed_urls(plan, cache_policy, resolved_cache_dir)
        try:

            def signed_url_resolver(fs_node_id: str) -> str:
                future = url_futures.get(fs_node_id)
                return future.result() if future is not None else self.__signed_url_for_file(fs_node_id)

            open_file_decoder = make_file_decoder_opener(
                FileDecodeParams(
                    signed_url_resolver=signed_url_resolver,
                    cache_policy=cache_policy,
                    cache_dir=resolved_cache_dir,
                )
            )

            for batch in plan_execution.execute_read_plan(plan, projected, open_file_decoder):
                yield batch_transforms.drop_row_number_column(batch)
        finally:
            if url_executor is not None:
                url_executor.shutdown(wait=False, cancel_futures=True)

    def set_unix_offset(self, anchor: Time) -> list[TimelineExtentRecord]:
        """Anchor this Topic's data in its Session to wall-clock time.

        ``anchor`` is the wall-clock instant at which stored time 0 of that data occurred. Converted to
        nanoseconds since the Unix epoch, it is added to the stored timestamps of every part of this Topic
        the Session holds, so each timestamp reads as wall-clock time. Use this call
        for a Session whose data all starts from one time 0 but is stored apart: a topic chunked across
        several files, or several Sessions packed into slices of one shared file where this Session
        holds one of the slices. Every part moves in one transaction, so a failure leaves every one
        of them at the offset it already had.

        This call covers one Topic within one Session. To anchor everything in a Session, use
        :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset`; to anchor a whole file
        regardless of Session, use :py:meth:`~roboto.domain.files.File.set_timeline_offset`; to
        anchor exactly the slice a declaration names, supply that declaration's ``anchor_ns`` at
        ingest.

        Two consequences:

        1. The data written is shared, not copied. Any other Session holding the same data reads
           the same anchor.
        2. A file's declared time range in the Session moves only when everything that range covers
           moved by the same distance. A file whose range also covers another topic's data, which
           this call leaves alone, keeps the range it has.

        Args:
            anchor: Wall-clock instant of stored time 0: an ``int`` of nanoseconds since the Unix epoch,
                or any other :py:data:`~roboto.time.Time`, read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime`` or ISO 8601 string
                is that instant; a ``float``, ``Decimal``, or numeric string is seconds since the epoch).
                Must fall after the Unix epoch: zero is not an anchor (use :py:meth:`clear_unix_offset` to
                return this Topic's data in the Session to an offset of 0), and earlier instants are
                rejected.

        Returns:
            One :py:class:`~roboto.domain.topics.TimelineExtentRecord` per timeline extent whose offset
            changed. An extent already anchored at ``anchor`` is left untouched and absent from the list,
            so an empty list means the anchor was already in place.

        Raises:
            ValueError: This Topic carries no Session context, so there is no way to tell which of
                the Topic's data is meant; reach it through
                :py:meth:`~roboto.experimental.sessions.Session.get_topic` or
                :py:meth:`~roboto.experimental.sessions.Session.list_topics`.
            TypeError: ``anchor`` is not one of the :py:data:`~roboto.time.Time` types.
            ValueError: ``anchor`` is a boolean, a string that is neither seconds nor ISO 8601, zero, before
                the Unix epoch, or too large for a signed 64-bit integer of nanoseconds; rejected
                client-side, before any request is made. A range refusal is raised as
                :py:exc:`pydantic.ValidationError`, a subclass of ``ValueError``.
            RobotoInvalidRequestException: The anchor would move this Topic's data, or a time range declared over
                it, before the Unix epoch or past the largest storable Unix-epoch nanosecond value; anchor the data
                at the instant it was recorded.
            RobotoConflictException: A concurrent writer added files to the Session while the anchor
                was being applied; retry the call.
            RobotoNotFoundException: The Session does not exist, or holds no data for this Topic.
            RobotoUnauthorizedException: The caller cannot view the Session, or cannot edit some
                file behind the data being written.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> session = Session.from_id("se_abc123")  # doctest: +SKIP
            >>> topic = session.get_topic("/camera/image_raw")  # doctest: +SKIP
            >>> topic.set_unix_offset(1_700_000_000_000_000_000)  # doctest: +SKIP

            The same anchor given as a ``datetime``:

            >>> import datetime
            >>> topic.set_unix_offset(
            ...     datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.timezone.utc)
            ... )  # doctest: +SKIP
        """
        return self.__roboto_client.post(
            f"v2/topics/id/{self.topic_id}/unix-offset",
            data=SetTopicUnixOffsetRequest(
                session_id=self.__require_session_id("set_unix_offset"),
                unix_epoch_offset_ns=to_epoch_nanoseconds(anchor),
            ),
        ).to_record_list(TimelineExtentRecord)

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

    def __require_session_id(self, operation: str) -> str:
        """Return the id of the Session this Topic is scoped to.

        :py:meth:`set_unix_offset` and :py:meth:`clear_unix_offset` act on the data one Session
        holds. Without a Session they would have nothing to act on but the Topic's data org-wide,
        across every file that ever carried the topic name.

        Args:
            operation: Name of the calling method; it opens the error message.

        Raises:
            ValueError: This Topic carries no Session context.
        """
        context = self.__context
        if not isinstance(context, SessionContext):
            raise ValueError(
                f"{operation} needs a Topic scoped to a Session; reach this Topic through "
                "Session.get_topic or Session.list_topics, or anchor a whole file with "
                "File.set_timeline_offset."
            )
        return context.session_id

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
        context = self.__context
        start_ns = to_epoch_nanoseconds(start_time) if start_time is not None else None
        end_ns = to_epoch_nanoseconds(end_time) if end_time is not None else None
        session_id: typing.Optional[str] = None
        if isinstance(context, SessionContext):
            session_id = context.session_id
            start_ns = start_ns if start_ns is not None else context.start_time
            end_ns = end_ns if end_ns is not None else context.end_time

        # A file, dataset or device context leaves an omitted bound for the service to default. Checking here, ahead of
        # ReadPlanRequest's own check, gives an error in terms of the Topic's contexts rather than the request's fields.
        if (start_ns is None or end_ns is None) and not isinstance(
            context, (FileContext, DatasetContext, DeviceContext)
        ):
            raise ValueError(
                "start_time and end_time are required; they default to the span of the topic's data in a file, "
                "dataset or device context, and to the session's time window for a topic obtained from "
                "Session.list_topics() or Session.get_topic() (only when that session has bounds)."
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
            session_id=session_id,
            file_id=context.file_id if isinstance(context, FileContext) else None,
            dataset_id=context.dataset_id if isinstance(context, DatasetContext) else None,
            device_id=context.device_id if isinstance(context, DeviceContext) else None,
        )
        return self.__roboto_client.post(
            f"v2/topics/id/{self.topic_id}/read-plan",
            data=request,
        ).to_record(ReadPlan)

    def __schema_field_paths(self, schema_id: str) -> list[FieldPath]:
        """Fetch the path of every field the schema ``schema_id`` declares."""
        records = self.__roboto_client.get(f"v2/topics/schema/id/{schema_id}/fields").to_record_list(SchemaFieldRecord)
        return [record.path_in_schema for record in records]

    def __signed_url_for_file(self, fs_node_id: str) -> str:
        response = self.__roboto_client.get(f"v1/files/{fs_node_id}/signed-url")
        return response.to_dict(json_path=["data", "url"])


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
