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
from ...storage.cache import cached_file_is_current
from ...time import Time, to_epoch_nanoseconds
from . import batch_transforms, plan_execution
from .decode import (
    FileDecodeParams,
    cached_parquet_name,
    make_file_decoder_opener,
)
from .named_array import named_array_type
from .operations import (
    FieldAddress,
    ReadPlanRequest,
    RepresentationPreference,
    SetTopicUnixOffsetRequest,
)
from .read_plan import ReadPlan, ReadPlanObjectRef

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep
    import pyarrow  # pants: no-infer-dep

FieldAddressLike = typing.Union[FieldAddress, collections.abc.Sequence[str]]
"""Address of a field subtree: a ``FieldAddress``, or the field's path components as a sequence of strings.

Give ``("pose", "position")`` for a nested field and ``("angular_velocity",)`` for a top-level one. Each component is
one element of the field's ``path_in_schema``, so a component may itself contain a ``.``. A bare string raises
``TypeError``: it is a sequence of strings too, but splitting it on ``.`` would guess where components begin and end,
and iterating it would address one field per character."""

TOPIC_DATA_CACHE_SUBDIR = "topic-data"
"""Name of the subdirectory of the local cache directory that holds the topic data files reads download."""

_MAX_SIGNED_URL_WORKERS = 32
"""Maximum number of threads that fetch signed URLs for a read's files at once.

Fetching a URL is a wait on the network, so the limit is 32, the most worker threads
``concurrent.futures.ThreadPoolExecutor`` starts by default, rather than a number that grows with the CPU count."""


class SessionContext(pydantic.BaseModel):
    """Scope of a ``Topic`` to one session: its data in the session's files, each over the part the session holds.

    A read that omits ``start_time`` or ``end_time`` takes this context's bound on that side, or has no limit there
    when the context sets none. The ``Topic`` that :py:meth:`~roboto.experimental.sessions.Session.get_topic` or
    :py:meth:`~roboto.experimental.sessions.Session.list_topics` returns carries one that sets neither bound."""

    model_config = pydantic.ConfigDict(frozen=True)

    session_id: str
    """ID of the session, beginning with ``se_``."""

    start_time: typing.Optional[int] = None
    """Inclusive start of the time range a read takes when it gives no ``start_time``.

    The value is in nanoseconds since the Unix epoch; ``None`` puts no lower limit on the range."""

    end_time: typing.Optional[int] = None
    """Inclusive end of the time range a read takes when it gives no ``end_time``.

    The value is in nanoseconds since the Unix epoch; ``None`` puts no upper limit on the range."""


class EventContext(pydantic.BaseModel):
    """Scope of a ``Topic`` to one session event: the data of the event's session, by default over the event's span.

    A read is limited to the topic's data in the event's session, as in a ``SessionContext``, and a read that omits
    ``start_time`` or ``end_time`` takes the event's start or end. The ``Topic`` that
    ``roboto.experimental.events.Event.get_topic`` or ``Event.get_topics`` returns carries one."""

    model_config = pydantic.ConfigDict(frozen=True)

    event_id: str
    """ID of the event, beginning with ``evt_``."""

    session_id: str
    """ID of the session the event belongs to."""

    start_time: int
    """Inclusive start of the event's time span, in nanoseconds since the Unix epoch."""

    end_time: int
    """Inclusive end of the event's time span, in nanoseconds since the Unix epoch."""


class FileContext(pydantic.BaseModel):
    """Scope of a ``Topic`` to one file: the topic's data in that file.

    A read that omits ``start_time`` or ``end_time`` has no limit on that side."""

    model_config = pydantic.ConfigDict(frozen=True)

    file_id: str


class DatasetContext(pydantic.BaseModel):
    """Scope of a ``Topic`` to one dataset: the topic's data in the dataset's files.

    A read that omits ``start_time`` or ``end_time`` has no limit on that side."""

    model_config = pydantic.ConfigDict(frozen=True)

    dataset_id: str


class DeviceContext(pydantic.BaseModel):
    """Scope of a ``Topic`` to one device: the topic's data in the device's files.

    A file belongs to the device it names, or, when it names none, to the device its dataset names. A read that omits
    ``start_time`` or ``end_time`` has no limit on that side."""

    model_config = pydantic.ConfigDict(frozen=True)

    device_id: str


TopicContext = typing.Union[SessionContext, EventContext, FileContext, DatasetContext, DeviceContext]
"""Scope of any kind that a ``Topic`` reads within.

One of ``SessionContext``, ``EventContext``, ``FileContext``, ``DatasetContext`` or ``DeviceContext``."""


class Topic:
    """A topic: a sequence of structured time-series data, called messages, identified by name across files.

    Topic names are unique within an organization, so data that different files log under one topic name belongs to
    one topic, with one ID. Without a context, a ``Topic`` reads across the organization, and ``get_data``,
    ``get_data_as_df`` and ``get_data_as_record_batches`` require both ``start_time`` and ``end_time``.

    A ``Topic`` built with a ``TopicContext`` limits those methods to the topic's data in that context, and never reads
    the topic's data elsewhere:

    - A ``SessionContext``, as on the ``Topic`` that :py:meth:`~roboto.experimental.sessions.Session.get_topic` or
      :py:meth:`~roboto.experimental.sessions.Session.list_topics` returns, limits them to the session's files, each
      over the part of its time span the session holds.
    - An ``EventContext``, as on the ``Topic`` that ``roboto.experimental.events.Event.get_topic`` or
      ``Event.get_topics`` returns, limits them in the same way to the event's session.
    - A ``FileContext``, ``DatasetContext`` or ``DeviceContext`` limits them to that file, or to that dataset's or
      device's files.

    A read in a context needs no time range. A bound the read omits puts no limit on that side, unless the context
    sets a bound there: a ``SessionContext`` may set either bound, and an ``EventContext`` sets both, to the event's
    span. ``set_unix_offset`` and ``clear_unix_offset`` require a ``SessionContext``. A ``Topic``'s context is fixed
    when it is built.

    Args:
        record: Record of the topic.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        context: Scope to limit the topic's reads to. ``None`` reads across the organization.
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
        """Fetch a topic by its ID.

        Args:
            topic_id: Unique ID of the topic, beginning with ``ti_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            context: Scope to limit the topic's reads to: its data in one session, session event, file, dataset or
                device, as the class docstring describes. A read in a context needs no time range. ``None`` reads
                across the organization.

        Raises:
            RobotoNotFoundException: No topic has this ID.

        Examples:
            Fetch a topic and print its name:

            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> print(topic.name)

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
        """Build a ``Topic`` from a record of the topic already fetched from Roboto, without making a request.

        Args:
            record: Record of the topic.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            context: Scope to limit the topic's reads to, as in ``from_id``. ``None`` reads across the organization.

        Examples:
            >>> from roboto.experimental.topics import FileContext, Topic
            >>> topic = Topic.from_record(record, context=FileContext(file_id="fl_abc123"))  # doctest: +SKIP
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
        """Name of the topic, such as ``"/camera/image_raw"``, unique within an organization."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the topic."""
        return self.__record.org_id

    @property
    def record(self) -> TopicIdentityRecord:
        """Record of the topic that this instance holds."""
        return self.__record

    @property
    def topic_id(self) -> str:
        """Unique ID of the topic identity.

        It begins with ``ti_``, and is the same in every file that logs the topic."""
        return self.__record.topic_id

    def clear_unix_offset(self) -> list[TimelineExtentRecord]:
        """Reset the offset of this topic's data in its session to 0.

        The data's stored timestamps are then read as nanoseconds since the Unix epoch with nothing added. This call
        reaches the same data as ``set_unix_offset``, and a file's declared time range in the session moves back under
        the same condition: only when everything that range covers moved by the same distance.

        Returns:
            One :py:class:`~roboto.domain.topics.TimelineExtentRecord` per timeline extent whose offset
            changed. An extent already at an offset of 0 is left untouched and absent from the list, so
            an empty list means there was no anchor to clear.

        Raises:
            ValueError: This topic carries no ``SessionContext``, as for ``set_unix_offset``. Raised before any
                request is made.
            RobotoInvalidRequestException: Some of this topic's stored timestamps are negative, so an offset of 0
                would place that data before the Unix epoch; or a time range declared over the data would start
                before the epoch once moved back with it.
            RobotoConflictException: Files were added to the session while the offset was being cleared; retry the
                call.
            RobotoNotFoundException: The session does not exist, or holds no data for this topic.

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
        """Yield this topic's data within a time range, as ``(timestamp, record)`` pairs.

        Reads through ``get_data_as_record_batches`` and unpacks each Arrow record batch into one pair per row:

        - ``timestamp`` is the row's time, an ``int`` of nanoseconds since the Unix epoch.
        - ``record`` is a dictionary of the projected fields, with struct fields as nested dictionaries and list
          fields as lists. An array whose elements are named is a ``NamedArray``, which also returns an element by
          its name. A field the data omits for a row is absent from that row's dictionary, or ``None`` in it.

        The time range, the fields read, the choice of stored representation, the order of rows, and the exceptions
        raised are as ``get_data_as_record_batches`` describes.

        Args:
            start_time: See ``get_data_as_record_batches``.
            end_time: See ``get_data_as_record_batches``.
            fields_include: See ``get_data_as_record_batches``.
            fields_exclude: See ``get_data_as_record_batches``.
            prefer: See ``get_data_as_record_batches``.
            schema_id: See ``get_data_as_record_batches``.
            schema_checksum: See ``get_data_as_record_batches``.
            timeline_source_id: See ``get_data_as_record_batches``.
            timeline_source_name: See ``get_data_as_record_batches``.
            cache_policy: See ``get_data_as_record_batches``.
            cache_dir: See ``get_data_as_record_batches``.

        Yields:
            ``(timestamp, record)`` pairs for the rows in the time range, with the fields the arguments select.

        Examples:
            >>> from roboto.experimental.topics import Topic
            >>> topic = Topic.from_id("ti_abc123")
            >>> for timestamp, record in topic.get_data(start_time=t0, end_time=t1):
            ...     print(timestamp, record)

            Read one element of a named array by its name:

            >>> for timestamp, record in topic.get_data(
            ...     start_time=t0, end_time=t1, fields_include=[("action", "main_gripper")]
            ... ):
            ...     print(record["action"].main_gripper)
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
            for field in batch.schema:
                element_names = batch_transforms.element_names(field)
                if element_names is None:
                    continue
                named_array = named_array_type(tuple(element_names))
                for row in rows:
                    if row[field.name] is not None:
                        row[field.name] = named_array._make(row[field.name])
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
        """Return this topic's data within a time range as a pandas DataFrame.

        Reads every batch ``get_data_as_record_batches`` yields into one DataFrame. Rows are ordered by partition,
        each file's data in the order it begins, and within a partition keep their stored order; call
        ``df.sort_index()`` to order them by time. The arguments it shares with ``get_data_as_record_batches``, and the
        exceptions that method raises, are as it describes.

        Args:
            start_time: See ``get_data_as_record_batches``.
            end_time: See ``get_data_as_record_batches``.
            fields_include: See ``get_data_as_record_batches``.
            fields_exclude: See ``get_data_as_record_batches``.
            prefer: See ``get_data_as_record_batches``.
            schema_id: See ``get_data_as_record_batches``.
            schema_checksum: See ``get_data_as_record_batches``.
            timeline_source_id: See ``get_data_as_record_batches``.
            timeline_source_name: See ``get_data_as_record_batches``.
            flatten: Whether to expand every level of each struct field into dot-delimited leaf columns, such as
                ``pose.position.x``. List fields stay whole, and an array whose elements are named also gets one
                ``<array>.<element name>`` column per element after it. ``False`` keeps each struct field as one
                column of dictionaries.
            cache_policy: See ``get_data_as_record_batches``.
            cache_dir: See ``get_data_as_record_batches``.

        Returns:
            DataFrame of the rows in the time range, indexed by a ``DatetimeIndex`` in UTC named ``_index``. With no
            rows, it has no columns.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            RobotoInvalidRequestException: ``flatten`` is ``True`` and two columns flatten to the same name, such as
                a top-level field named ``pose.x`` and the child ``x`` of a struct ``pose``.

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
            # With no batches there is no schema to build columns from, so the DataFrame has only an empty index.
            df = pd.DataFrame()
            df = df.set_index(pd.to_datetime([], unit="ns", utc=True))
            df.index.name = "_index"
            return df

        # The batches' schemas can differ, between partitions or between batches of one partition;
        # permissive promotion merges them into one schema.
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
        """Yield this topic's data within a time range, as Arrow record batches (``pyarrow.RecordBatch``).

        Each batch has one column per projected top-level field, whose struct and list types follow the topic's schema,
        pruned to the fields read, and one ``int64`` column of timestamps in nanoseconds since the Unix epoch, which
        ``timestamp_column_index`` finds. An array whose elements are named lists their names as JSON in its field's
        metadata, under the key ``ELEMENT_NAMES_FIELD_METADATA_KEY``. A field the data omits for a row is null at the
        level where the data omits it, so a whole missing subtree is a single null.

        Batch sizes and boundaries carry no meaning. A time range with no rows yields no batches, and so does a context
        that holds no data for the topic.

        A topic's data is stored in partitions: a partition is the part of the data stored in one file, or in one slice
        of a file several sessions share. Batches arrive partition by partition, ordered by where each partition's data
        begins. A batch never mixes rows of two partitions, and within a partition rows keep their stored order, so
        rows are in time order only within a partition; sort them yourself to order the whole read by time. When some
        partitions have no stored representation this read can use, the read skips them, and one
        ``UnreadableTopicPartitionsWarning`` names them before any batch is yielded.

        Nothing is requested or raised until iteration begins. The exceptions below surface on the first iteration,
        except that ``RobotoReadPlanExecutionException`` and ``RobotoInternalException`` can also surface during
        iteration, when a file is read.

        Args:
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts. Required when this topic has no context. In a
                context, ``None`` takes the event's start in an ``EventContext``, or the ``start_time`` of a
                ``SessionContext`` that sets one, and otherwise puts no lower limit on the read.
                A bound given in a context narrows the read and never widens it. An ``EventContext`` limits the read
                to the event's session rather than the event's span, so a bound may reach past the event, to read
                around it, but not past the session's data.
            end_time: Inclusive end of the time range, in the same form. ``None`` takes the context's end on the same
                terms as ``start_time``, and otherwise puts no upper limit on the read.
            fields_include: Field subtrees to read. ``None`` reads every field. An address may also name one
                element of a named array, as the array's path plus the element's name; the array then holds only
                the elements named, in element order and numbered from 0, unless the array itself is also included.
            fields_exclude: Field subtrees to leave out. ``None`` leaves out none. An address of one element of a
                named array leaves that element out of its array.
            prefer: Which stored representation of each field subtree to read, as ``RepresentationPreference``
                describes. ``None`` admits every representation.
            schema_id: ID of the topic schema to read under, beginning with ``ts_``. ``None``, with no
                ``schema_checksum``, uses the one schema of the topic's data in the time range; name one when that
                data has more than one.
            schema_checksum: Checksum of the topic schema to read under, in place of ``schema_id``.
            timeline_source_id: ID of the timeline source that places each partition's data in time. ``None``, with
                no ``timeline_source_name``, uses the timeline source the schema marks as its default.
            timeline_source_name: Name of the timeline source, in place of ``timeline_source_id``.
            cache_policy: Whether each Parquet file is downloaded to the local cache before it is read, as
                :py:class:`~roboto.storage.CachePolicy` describes. MCAP files are always read over HTTP.
            cache_dir: Directory to cache downloaded files in. ``None`` uses the ``topic-data`` subdirectory of the
                directory ``ROBOTO_CACHE_DIR`` names, or of the operating system's per-user cache directory for
                ``roboto`` when ``ROBOTO_CACHE_DIR`` is unset.

        Yields:
            Record batches of the rows in the time range, with the fields the arguments select.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            TypeError: An address in ``fields_include`` or ``fields_exclude`` is a string, which
                ``FieldAddressLike`` explains, or ``start_time`` or ``end_time`` is not a :py:const:`~roboto.time.Time`.
            ValueError: This topic has no context and ``start_time`` or ``end_time`` is omitted, or
                :py:func:`~roboto.time.to_epoch_nanoseconds` rejects a bound. Building the request also raises
                ``pydantic.ValidationError``, a subclass of ``ValueError``, when a bound is outside the range of
                timestamps Roboto stores, when ``end_time`` is before ``start_time``, when both ``schema_id`` and
                ``schema_checksum`` or both ``timeline_source_id`` and ``timeline_source_name`` are set, or when
                ``fields_include`` or ``fields_exclude`` is empty.
            RobotoNotFoundException: The session, file or dataset this topic's context names does not exist.
            RobotoInvalidRequestException: The time range spans data with more than one schema and
                none was chosen with ``schema_id`` or ``schema_checksum``, a named
                schema or timeline source does not match the data in the time range, no
                stored representation satisfies a representation preference, or
                ``fields_include`` and ``fields_exclude`` together select no field.
            RobotoReadPlanExecutionException: The topic's data cannot be read as its read plan, Roboto's description
                of which files hold the data and how to decode them, describes it. It is a
                ``RobotoInternalException`` whose ``kind`` says why:

                * ``unsupported-format``: a scan task, the plan's instruction to read one stored file, names a
                  format other than MCAP or Parquet.
                * ``field-not-in-file``: a file backing this topic lacks a field the read takes from it, such as a
                  projected field or the field holding each row's timestamp. ``field_path`` runs from that field's
                  top-level field down to the first component the file lacks.
                * ``unsupported-timestamp``: the read cannot take timestamps from where the data keeps them, such as
                  a message time on a Parquet file, or a Parquet timestamp field that is not a number.
                * ``invalid-timestamp``: a stored timestamp is NaN or infinite, is a DECIMAL holding a fraction of a
                  nanosecond, or leaves the signed 64-bit range once shifted to time since the Unix epoch.
                  ``row_number`` names the row by its 0-based position among the topic's rows in its file.
                * ``scan-task-row-mismatch``: files that store different fields of the same rows hold different rows
                  in the time range.
                * ``field-split-inside-non-struct``: files that store different fields of the same rows split a field
                  that one of them stores as other than a struct, such as a list or a map.
                * ``projected-field-in-no-scan-task``: a partition has scan tasks, but none reads the whole schema or
                  a subtree containing one of the projected fields that has no other projected field beneath it.
                * ``inconsistent-scan-tasks-on-file``: the plan reads one file two ways, with a different format,
                  transformations or topic name.
                * ``partition-schema-mismatch``: a partition's files give the read a different schema than the first
                  partition's files. It is raised when that partition's files open, before any of its rows, so even
                  when it has no rows in the time range.
                * ``plan-without-schema``: the plan reads every field of its schema and has a partition with a scan
                  task, but names no schema.
                * ``data-range-not-in-file``: a partition's declared slice of its file (``data_range``) ends past the
                  file's stored row count, so the slice does not match the file.
                * ``element-count-mismatch``: a named array holds a different number of elements than it has
                  names. Stored as a fixed-size list, it is refused before any row is read; stored as a list of
                  varying length, it is refused at the first such row, which ``row_number`` names.
            RobotoInternalException: An MCAP file backing this topic cannot be decoded, such as one with no chunk or
                message index, or one whose messages are ``protobuf``-encoded.

        Examples:
            Print each batch's row count and columns for a time range:

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
            # A RobotoEnv built here reads ROBOTO_CACHE_DIR as it is at this call, falling back to the operating
            # system's per-user cache directory, which ensure_exists=False leaves uncreated.
            else resolve_cache_dir(RobotoEnv(), ensure_exists=False) / TOPIC_DATA_CACHE_SUBDIR
        )

        # Fetch the signed URLs of the files this read downloads all at once; each decoder waits only for its own
        # file's URL.
        url_executor, url_futures = self.__prefetch_signed_urls(plan, cache_policy, resolved_cache_dir)
        try:

            def signed_url_resolver(file: ReadPlanObjectRef) -> str:
                future = url_futures.get(file)
                return future.result() if future is not None else self.__signed_url_for_file(file)

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
            # Also runs when the caller stops iterating early or the read fails: URL fetches not yet started are
            # cancelled, and the call does not wait for those in flight.
            if url_executor is not None:
                url_executor.shutdown(wait=False, cancel_futures=True)

    def set_unix_offset(self, anchor: Time) -> list[TimelineExtentRecord]:
        """Anchor this topic's data in its session to wall-clock time.

        ``anchor`` is the wall-clock instant at which stored time 0 of that data occurred. Converted to
        nanoseconds since the Unix epoch, it is added to the stored timestamps of every part of this topic
        the session holds, so each timestamp reads as wall-clock time. Use this call
        for a session whose data all starts from one time 0 but is stored apart: a topic chunked across
        several files, or several sessions packed into slices of one shared file where this session
        holds one of the slices. Every part moves in one transaction, so a failure leaves every one
        of them at the offset it already had.

        This call covers one topic within one session. To anchor everything in a session, use
        :py:meth:`~roboto.experimental.sessions.Session.set_unix_offset`; to anchor a whole file
        regardless of session, use :py:meth:`~roboto.domain.files.File.set_timeline_offset`; to
        anchor exactly the slice a declaration names, set the declaration's
        :py:attr:`~roboto.experimental.sessions.FileDeclaration.anchor_ns` when the file is added.

        Two consequences:

        1. The data written is shared, not copied. Any other session holding the same data reads
           the same anchor.
        2. A file's declared time range in the session moves only when everything that range covers
           moved by the same distance. A file whose range also covers another topic's data, which
           this call leaves alone, keeps the range it has.

        Args:
            anchor: Wall-clock instant of stored time 0: an ``int`` of nanoseconds since the Unix epoch,
                or any other :py:const:`~roboto.time.Time`, read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime`` or ISO 8601 string
                is that instant; a ``float``, ``Decimal``, or numeric string is seconds since the epoch).
                Must fall after the Unix epoch: zero is not an anchor (use ``clear_unix_offset`` to
                return this topic's data in the session to an offset of 0), and earlier instants are
                rejected.

        Returns:
            One :py:class:`~roboto.domain.topics.TimelineExtentRecord` per timeline extent whose offset
            changed. An extent already anchored at ``anchor`` is left untouched and absent from the list,
            so an empty list means the anchor was already in place.

        Raises:
            TypeError: ``anchor`` is not one of the :py:const:`~roboto.time.Time` types.
            ValueError: One of these, each raised before any request is made:

                - This topic carries no ``SessionContext``, so there is no way to tell which of its data is meant;
                  reach it through :py:meth:`~roboto.experimental.sessions.Session.get_topic` or
                  :py:meth:`~roboto.experimental.sessions.Session.list_topics`.
                - ``anchor`` is a boolean, a string that is neither seconds nor ISO 8601, zero, before the Unix
                  epoch, or too large for a signed 64-bit integer of nanoseconds. A range refusal is raised as
                  ``pydantic.ValidationError``, a subclass of ``ValueError``.
            RobotoInvalidRequestException: The anchor would move this topic's data, or a time range declared over
                it, before the Unix epoch or past the largest storable Unix-epoch nanosecond value; anchor the data
                at the instant it was recorded.
            RobotoConflictException: Files were added to the session while the anchor was being applied; retry the
                call.
            RobotoNotFoundException: The session does not exist, or holds no data for this topic.

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
    ) -> tuple[
        typing.Optional[concurrent.futures.ThreadPoolExecutor],
        dict[ReadPlanObjectRef, concurrent.futures.Future[str]],
    ]:
        """Start fetching, at once, the signed URL of every file version the plan's scan tasks read.

        Returns the executor that fetches them (``None`` when no file needs a URL) and one future per file version
        that needs one. The caller waits on each future as decoding reaches its file, and owns shutting the executor
        down.

        Decoding reads a Parquet file from disk, without a URL, when the local cache holds a copy under the file's
        ``cached_parquet_name`` at the plan's size, or at any size when the plan reports none, so such a file gets no
        URL here. A cached copy of another size is stale and is downloaded again, so that file's URL is fetched with
        the rest. Under ``CachePolicy.NEVER`` decoding never reads the cache, so every Parquet file gets a URL. Every
        MCAP file gets one, because MCAP files are always read over HTTP. The resolver decoding uses fetches a URL
        itself for any file missing from the returned map, so a skipped file that is read over HTTP after all still
        gets one.
        """
        files: set[ReadPlanObjectRef] = set()
        for partition in plan.partitions:
            for scan_task in partition.scan_tasks:
                if scan_task.format == RepresentationStorageFormat.PARQUET:
                    cached_outfile = cache_dir / cached_parquet_name(scan_task.object)
                    if cache_policy is not CachePolicy.NEVER and cached_file_is_current(
                        cached_outfile, scan_task.object.size_bytes
                    ):
                        continue
                files.add(scan_task.object)

        if not files:
            return None, {}

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_SIGNED_URL_WORKERS, len(files)))
        return executor, {file: executor.submit(self.__signed_url_for_file, file) for file in files}

    def __require_session_id(self, operation: str) -> str:
        """Return the ID of the session this topic is scoped to.

        Raise ``ValueError``, with an error message that opens with ``operation``, the calling method's name, when this
        topic carries no ``SessionContext``. ``set_unix_offset`` and ``clear_unix_offset`` act on the data one session
        holds. Without a session they would have nothing to act on but the topic's data across the organization, in
        every file that ever logged the topic name.
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
        if isinstance(context, (SessionContext, EventContext)):
            session_id = context.session_id
            start_ns = start_ns if start_ns is not None else context.start_time
            end_ns = end_ns if end_ns is not None else context.end_time

        # A read in a context may omit a bound, and Roboto then puts no limit on that side of the read. Checking here,
        # ahead of ReadPlanRequest's own check, gives an error in terms of the topic's contexts rather than the
        # request's fields.
        if (start_ns is None or end_ns is None) and context is None:
            raise ValueError(
                "start_time and end_time are required unless the topic is read in a session, session event, file, "
                "dataset or device context"
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
            accepts_element_selection=True,
        )
        return self.__roboto_client.post(
            f"v2/topics/id/{self.topic_id}/read-plan",
            data=request,
        ).to_record(ReadPlan)

    def __schema_field_paths(self, schema_id: str) -> list[FieldPath]:
        """Fetch the path of every field the schema ``schema_id`` declares."""
        records = self.__roboto_client.get(f"v2/topics/schema/id/{schema_id}/fields").to_record_list(SchemaFieldRecord)
        return [record.path_in_schema for record in records]

    def __signed_url_for_file(self, file: ReadPlanObjectRef) -> str:
        response = self.__roboto_client.get(
            f"v1/files/{file.fs_node_id}/signed-url",
            query={"version_id": file.version} if file.version is not None else None,
        )
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
            # A str is a Sequence[str] too, so without this branch it would become one field per character; the
            # FieldAddressLike docstring gives the reason it is rejected rather than split.
            raise TypeError(
                "field address must be given as its path components, not a string; "
                f"pass a tuple such as {tuple(address.split('.'))!r} (or a FieldAddress) instead of {address!r}"
            )
        else:
            coerced.append(FieldAddress(path=tuple(address)))
    return tuple(coerced)
