# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

from ...ai.record import SetSummaryRequest
from ...ai.summary import (
    AISummary,
    PollingStreamingAISummary,
    StreamingAISummary,
)
from ...domain.metrics.metric import Metric
from ...domain.metrics.record import MetricEntry
from ...domain.topics.record import (
    DataRange,
    TopicIdentityRecord,
)
from ...http import BatchResponse, RobotoClient
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...time import Time, to_epoch_nanoseconds
from ...updates import CustomFieldChangeset, MetadataChangeset, StrSequence
from ...waiters import TimeoutError as WaitTimeoutError
from ...waiters import wait_for
from ..events import MAX_EVENTS_PER_PAGE, Event, EventRecord, EventTopicRequest
from ..ingest import TopicDeclaration
from ..topics import SessionContext, Topic
from .operations import (
    MAX_INGESTION_SUMMARIES,
    AddFilesRequest,
    AttachToDeviceRequest,
    CreateSessionIfNotExistsRequest,
    CreateSessionRequest,
    DetachFromDeviceRequest,
    RemoveFilesRequest,
    SessionFile,
    SessionIngestionSummariesRequest,
    SessionIngestionSummariesResponse,
    SessionUpdate,
    SetUnixOffsetRequest,
    SkipWaitingRequest,
)
from .record import (
    CompletionPolicy,
    SessionFileView,
    SessionIngestionState,
    SessionIngestionStatus,
    SessionIngestionSummary,
    SessionRecord,
    SessionStatus,
    SessionTopicRecord,
    SessionTopicStats,
    SessionTopicStatsRun,
    SkipWaitingResponse,
)

_MAX_PENDING_PATHS_IN_MESSAGE = 10

if typing.TYPE_CHECKING:
    from ...domain.files import File


class Session:
    """A session: an operational time window of a device, such as a drone flight, a vehicle drive, or a robot run.

    A session groups the recordings and other data produced during that window, and can span many files or hold only
    part of one. Because the activity bounds it rather than the recordings, each file it holds can be narrowed to a
    time window or a range of the file.

    The session's time bounds, ``min_timestamp_ns`` and ``max_timestamp_ns``, span every file it holds. Roboto
    recomputes them whenever the session's files or the wall-clock anchors of their data change, and each method of
    this class that makes such a change updates this instance with the new bounds before it returns.

    A session can have one device attached or several: a single drone for a solo mission, or every drone of a
    formation flight. ``attach_to_device`` and ``detach_from_device`` change which devices are attached. Roboto also
    attaches, on its own, each device that one of the session's files, or the dataset holding the file, names.

    To create a session:

    * ``create`` attaches zero or more devices, and does not require a name.
    * :py:meth:`~roboto.domain.devices.Device.create_session` creates one named session on a device, optionally
      declaring its files and topics in the same call.
    * :py:meth:`~roboto.domain.devices.Device.create_sessions` creates many such sessions on a device in one call.
    * :py:meth:`~roboto.domain.datasets.Dataset.create_session` creates a session that holds a dataset's files.

    Add files to a session with ``add_file`` or ``add_files``. Get a ``Session`` from one of those methods,
    ``create_if_not_exists``, or ``from_id``. To wrap a :py:class:`~roboto.experimental.sessions.SessionRecord`
    already fetched from Roboto, build a ``Session`` from it directly. Each instance holds a copy of the session's
    record: methods that change the session's properties update that copy from Roboto's response, and ``refresh``
    fetches changes made elsewhere.

    Args:
        record: Record of the session.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.

    Who may use a Session also depends on the datasets its files sit in. Besides the access a method needs in the
    Session's org, a method that reads one Session needs the right to read every such dataset, and a method that
    changes one Session (including adding files to it and deleting it) needs the right to change every such dataset.
    Otherwise the method raises :py:exc:`~roboto.exceptions.RobotoUnauthorizedException`. A dataset restricted to
    the people it is shared with can be read only with a share on it, and changed only with a share that has the
    editor role, unless you are an admin or owner of its org.

    Examples:
        Create a session for a drone flight, add a recording, and list its topics:

        >>> from roboto.experimental.sessions import Session
        >>> session = Session.create(name="flight-2026-04-23-001", device_ids=["robot-abc"])
        >>> session.add_file("fl_12345")
        >>> for topic in session.list_topics():
        ...     print(topic.name)

        Read one topic's data in a session as a DataFrame, then print the maximum of each field of every topic the
        session holds data of. Both read only the session's files, and only the part of each file that the session
        holds:

        >>> session = Session.from_id("se_12345")
        >>> df = session.get_topic("/imu").get_data_as_df(fields_include=[("accel", "x")])
        >>> for topic in session.list_topics():
        ...     stats = session.get_topic_stats(topic.topic_id)
        ...     for field in stats.fields:
        ...         print(topic.name, ".".join(field.path), field.stats.get("max"))
    """

    __roboto_client: RobotoClient
    __record: SessionRecord

    @classmethod
    def create(
        cls,
        name: typing.Optional[str] = None,
        device_ids: collections.abc.Sequence[str] = (),
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[collections.abc.Sequence[str]] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        completion_policy: typing.Union[CompletionPolicy, None, NotSetType] = NotSet,
    ) -> "Session":
        """Create a session, with zero or more devices attached.

        Every call creates a new session. To create a session on one device that a resent call reuses instead of
        duplicating, use :py:meth:`~roboto.domain.devices.Device.create_session`, which identifies the session by its
        name within the device. ``attach_to_device`` attaches more devices later.

        Args:
            name: Human-readable name of the session, at most 120 characters. ``None`` leaves the session unnamed.
                Roboto does not require names to be unique.
            device_ids: IDs of the devices to attach to the session. Defaults to none.
            description: Human-readable description of the session.
            metadata: Key-value metadata to set on the session. Sessions cannot be filtered or sorted by metadata
                keys; for an attribute to query by, define a custom field for sessions.
            tags: Tags to set on the session. Sessions can be filtered by tag but not sorted by tag.
            custom_fields: Initial values for the session's custom fields, keyed by field name. Each name must be a
                custom field defined for sessions in the organization the session is created in, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type.
            caller_org_id: Organization to create the session in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            completion_policy: When Roboto marks the session complete on its own. Left unset (``NotSet``), the session
                takes its organization's default completion policy, if an organization administrator has set one, and
                the returned session's ``completion_policy`` shows the policy it took. ``None`` means the session is
                marked complete only by ``complete``, whatever the organization's default. ``update`` changes it
                later.

        Returns:
            The new session.

        Raises:
            pydantic.ValidationError: ``name`` is longer than 120 characters. Raised before anything is sent to
                Roboto.
            RobotoIllegalArgumentException: A key of ``custom_fields`` is not a ``Ready`` custom field defined for
                sessions, or its value does not match the field's type.
            RobotoNotFoundException: A device in ``device_ids`` does not exist in the organization. No session is
                created.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> session = Session.create(
            ...     name="flight-2026-04-23-001",
            ...     device_ids=["robot-a", "robot-b"],
            ...     description="formation flight #4",
            ...     metadata={"pilot": "alice"},
            ...     tags=["pre-flight-check"],
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = cls.__create_request(
            name=name,
            device_ids=device_ids,
            description=description,
            metadata=metadata,
            tags=tags,
            custom_fields=custom_fields,
            completion_policy=completion_policy,
        )
        record = roboto_client.post(
            "v1/sessions",
            data=request,
            caller_org_id=caller_org_id,
        ).to_record(SessionRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def create_if_not_exists(
        cls,
        match_roboql_query: str,
        name: typing.Optional[str] = None,
        device_ids: collections.abc.Sequence[str] = (),
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[collections.abc.Sequence[str]] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        completion_policy: typing.Union[CompletionPolicy, None, NotSetType] = NotSet,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Session":
        """Fetch the first session that matches a RoboQL query, creating one when none matches.

        Concurrent calls with the same query create one session between them, so a process that handles one file at
        a time, such as a handler of S3 upload events, can use it to put each file into the session it belongs to.

        The session created must match ``match_roboql_query``. If ``name``, ``tags`` and the other arguments describe
        a session the query does not match, every later call creates another one.

        When several sessions match, which one is returned is not defined unless the query ends with a ``SORT BY``
        clause, such as ``name = 'flight-0042' SORT BY session_id``.

        A matching session is returned as it is: the other arguments apply only to a session this call creates, so a
        match ignores ``completion_policy`` and the rest. ``update`` changes a matched session. The session returned
        may be complete; adding a file to it puts it back in progress. To match only sessions in progress, add
        ``AND status = 'in_progress'`` to the query.

        Args:
            match_roboql_query: RoboQL query over the organization's sessions, such as ``name = 'flight-0042'``.
            name: Human-readable name of the session to create when none matches, at most 120 characters.
            device_ids: IDs of the devices to attach to a created session. Defaults to none.
            description: Human-readable description of a created session.
            metadata: Key-value metadata to set on a created session.
            tags: Tags to set on a created session.
            custom_fields: Initial values for a created session's custom fields, as in ``create``.
            completion_policy: Completion policy of a created session, as in ``create``.
            caller_org_id: Organization to search, and to create the session in. Required when the caller belongs to
                more than one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The matching or new session.

        Raises:
            pydantic.ValidationError: ``name`` is longer than 120 characters. Raised before anything is sent to
                Roboto.
            RobotoServiceUnavailableException: Other calls with the same query kept this one waiting for more than
                10 seconds, after the SDK's own retries. Calling again is safe.

        Examples:
            >>> from roboto.experimental.sessions import CompletionPolicy, Session
            >>> session = Session.create_if_not_exists(
            ...     "name = 'flight-0042'",
            ...     name="flight-0042",
            ...     completion_policy=CompletionPolicy(inactivity_minutes=15),
            ... )
            >>> session.add_file("fl_0123456789abcdef")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateSessionIfNotExistsRequest(
            match_roboql_query=match_roboql_query,
            create_request=cls.__create_request(
                name=name,
                device_ids=device_ids,
                description=description,
                metadata=metadata,
                tags=tags,
                custom_fields=custom_fields,
                completion_policy=completion_policy,
            ),
        )
        record = roboto_client.post(
            "v1/sessions/create_if_not_exists",
            data=request,
            caller_org_id=caller_org_id,
        ).to_record(SessionRecord)
        return cls(record=record, roboto_client=roboto_client)

    @staticmethod
    def __create_request(
        name: typing.Optional[str],
        device_ids: collections.abc.Sequence[str],
        description: typing.Optional[str],
        metadata: typing.Optional[dict[str, typing.Any]],
        tags: typing.Optional[collections.abc.Sequence[str]],
        custom_fields: typing.Optional[dict[str, typing.Any]],
        completion_policy: typing.Union[CompletionPolicy, None, NotSetType],
    ) -> CreateSessionRequest:
        return remove_not_set(
            CreateSessionRequest(
                name=name,
                device_ids=list(device_ids),
                description=description,
                metadata=metadata or {},
                tags=list(tags) if tags else [],
                custom_fields=custom_fields,
                completion_policy=completion_policy,
            )
        )

    @classmethod
    def for_dataset(
        cls,
        dataset_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Session", None, None]:
        """List the sessions that include at least one of a dataset's files.

        Only the current version of each file counts. Sessions come in the order ``for_org`` lists them.

        Args:
            dataset_id: ID of the dataset whose sessions to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each session that includes a file of the dataset, fetched a page at a time as the generator advances.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> for session in Session.for_dataset("ds_12345"):
            ...     print(session.session_id, session.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            results = roboto_client.get(
                f"v1/datasets/{dataset_id}/sessions",
                query=query,
            ).to_paginated_list(SessionRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def for_org(
        cls,
        org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Session", None, None]:
        """List the sessions in an organization.

        Sessions with time bounds come first, latest ``min_timestamp_ns`` first. Sessions without time bounds, such
        as those with no files yet, follow, most recently created first.

        Args:
            org_id: Organization whose sessions to list. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each session in the organization, fetched a page at a time as the generator advances.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> for session in Session.for_org("og_12345"):
            ...     print(session.session_id, session.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            results = roboto_client.get(
                "v1/sessions",
                caller_org_id=org_id,
                query=query,
            ).to_paginated_list(SessionRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def ingestion_summaries(
        cls,
        session_ids: collections.abc.Sequence[str],
        org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> list[SessionIngestionSummary]:
        """Fetch the ingestion state of each of several sessions, in counts.

        A summary lists no files, only counts, so to find which of many sessions are stuck it costs less than
        ``ingestion_status`` on each. The SDK sends one request per 100 sessions
        (:py:const:`~roboto.experimental.sessions.MAX_INGESTION_SUMMARIES`), and summarizes a session named more than
        once only once.

        Args:
            session_ids: IDs of the sessions to summarize.
            org_id: Organization to act in. Required when the caller belongs to more than one organization; otherwise
                the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            One summary per session the organization owns, in the order of ``session_ids``. Sessions outside the
            organization are left out.

        Examples:
            List the sessions with a file whose latest ingestion run failed:

            >>> summaries = Session.ingestion_summaries(["se_12345", "se_67890"])
            >>> print([summary.session_id for summary in summaries if summary.failed_file_count])
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        ids = list(dict.fromkeys(session_ids))
        summaries: list[SessionIngestionSummary] = []
        for start in range(0, len(ids), MAX_INGESTION_SUMMARIES):
            response = roboto_client.post(
                "v1/sessions/ingestion/summaries",
                caller_org_id=org_id,
                data=SessionIngestionSummariesRequest(session_ids=ids[start : start + MAX_INGESTION_SUMMARIES]),
            ).to_record(SessionIngestionSummariesResponse)
            summaries.extend(response.summaries)
        return summaries

    @classmethod
    def from_id(
        cls,
        session_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Session":
        """Fetch a session by its ID.

        Args:
            session_id: Unique ID of the session, beginning with ``se_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No session has this ID.
            RobotoUnauthorizedException: The caller may not read a dataset that holds one of the session's files.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> session = Session.from_id("se_12345")
            >>> print(session.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/sessions/id/{session_id}",
        ).to_record(SessionRecord)
        return cls(record=record, roboto_client=roboto_client)

    def __init__(
        self,
        record: SessionRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> typing.Optional[datetime.datetime]:
        """Time the session was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the session, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields the organization defines for sessions, keyed by field name.

        :py:attr:`~roboto.experimental.sessions.SessionRecord.custom_fields` says which fields appear as keys. A
        :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is an ISO 8601 string.
        """
        return self.__record.custom_fields

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the session, or ``None`` if it has none."""
        return self.__record.description

    @property
    def ingestion_count(self) -> int:
        """Number of times Roboto has announced the session ingested.

        :py:attr:`~roboto.experimental.sessions.SessionRecord.ingestion_count` says when Roboto announces it again.
        """
        return self.__record.ingestion_count

    @property
    def status(self) -> SessionStatus:
        """Status of the session: whether more of its files are expected.

        Adding a file to a complete session puts it back in progress.
        """
        return self.__record.status

    @property
    def completes_at(self) -> typing.Optional[datetime.datetime]:
        """Time Roboto will mark the session complete unless another file is added first.

        ``None`` while the session is complete, has no completion policy, or has no files.
        """
        return self.__record.completes_at

    @property
    def completion_policy(self) -> typing.Optional[CompletionPolicy]:
        """Rule by which Roboto marks the session complete on its own.

        ``None`` if the session is marked complete only by request, with ``complete``.
        """
        return self.__record.completion_policy

    @property
    def max_timestamp_ns(self) -> typing.Optional[int]:
        """Latest time covered by the session, in nanoseconds since the Unix epoch.

        ``None`` while none of its files supplies a time: the session holds no files, or only files added without a
        time window whose topic data has no time span registered yet.
        """
        return self.__record.max_timestamp_ns

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Copy of the key-value metadata on the session.

        Sessions cannot be filtered or sorted by metadata keys. To query a structured attribute of sessions, define a
        custom field for sessions instead.
        """
        return self.__record.metadata.copy()

    @property
    def min_timestamp_ns(self) -> typing.Optional[int]:
        """Earliest time covered by the session, in nanoseconds since the Unix epoch.

        ``None`` while none of its files supplies a time: the session holds no files, or only files added without a
        time window whose topic data has no time span registered yet.
        """
        return self.__record.min_timestamp_ns

    @property
    def modified(self) -> typing.Optional[datetime.datetime]:
        """Time the session was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the session, in the same ``<type>:<id>`` form as ``created_by``.

        Roboto's own system user when Roboto made the change.
        """
        return self.__record.modified_by

    @property
    def name(self) -> typing.Optional[str]:
        """Human-readable name of the session, at most 120 characters, or ``None`` if it has none.

        Roboto does not require names to be unique.
        """
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the session."""
        return self.__record.org_id

    @property
    def record(self) -> SessionRecord:
        """Record of the session that this instance holds.

        ``refresh`` replaces it with the current one.
        """
        return self.__record

    @property
    def session_id(self) -> str:
        """Unique ID of the session, beginning with ``se_``."""
        return self.__record.session_id

    @property
    def tags(self) -> list[str]:
        """Copy of the tags on the session."""
        return self.__record.tags.copy()

    def add_file(
        self,
        file: typing.Union["File", str],
        data_range: typing.Optional[DataRange] = None,
        min_file_timestamp_ns: typing.Optional[int] = None,
        max_file_timestamp_ns: typing.Optional[int] = None,
        anchor: typing.Optional[Time] = None,
        topics: typing.Optional[collections.abc.Sequence[TopicDeclaration]] = None,
    ) -> SessionFileView:
        """Add one file to the session, with the topic data it carries.

        Builds one :py:class:`~roboto.experimental.sessions.SessionFile` from the arguments, which that class
        describes, and sends it with ``add_files``, whose failures also apply. Where ``add_files`` reports a refused
        entry in its response, this method raises the exception Roboto refused the file with.

        Args:
            file: File to add, as a :py:class:`~roboto.domain.files.File` or its ID.
            data_range: Part of the file the session holds, as ``(start, end)``. ``None`` holds the whole file.
            min_file_timestamp_ns: Inclusive start of the time window, in nanoseconds of the file's own timestamps.
                Set both bounds or neither. ``None`` for both spans the entry's topic data, or the whole file when
                ``topics`` declares none.
            max_file_timestamp_ns: Inclusive end of the time window, in the same form.
            anchor: Wall-clock time at which time 0 of the data this entry names occurred, in nanoseconds since the
                Unix epoch or any value :py:func:`~roboto.time.to_epoch_nanoseconds` accepts. It must fall after
                the Unix epoch. ``None`` takes an anchor as
                :py:attr:`~roboto.experimental.sessions.FileDeclaration.anchor_ns` describes.
            topics: Topics the file carries data for, each over the part of the file that holds it. ``None``
                declares none.

        Returns:
            The file as the session holds it, in the form ``list_files`` yields.

        Raises:
            TypeError: ``anchor`` is not a :py:const:`~roboto.time.Time`.
            ValueError: ``anchor`` is a boolean, a negative number, or a string that is neither a number nor an
                ISO 8601 timestamp.
            OverflowError: ``anchor`` is infinite, such as ``float("inf")``.
            pydantic.ValidationError: The arguments break a rule ``SessionFile`` enforces, such as an ``anchor`` at
                the Unix epoch or a time window with only one of its two bounds, or the representations listed in
                ``topics`` name one file in two storage formats.
            RobotoInvalidRequestException: With the anchor covering it added, the file's data or the window stated
                here would fall before the Unix epoch or after ``2**63 - 1`` nanoseconds past it, or the anchor would
                move another session's window over the same data outside that span.
            RobotoDomainException: Roboto refused the file for another reason. The exception raised is the one
                Roboto reported.

        Examples:
            Add a whole file:

            >>> session.add_file("fl_12345")

            Add only the part of a file from 0 to 60 seconds of its own timestamps:

            >>> session.add_file(
            ...     "fl_12345",
            ...     min_file_timestamp_ns=0,
            ...     max_file_timestamp_ns=60_000_000_000,
            ... )
        """
        file_id = file if isinstance(file, str) else file.file_id
        entry = SessionFile(
            file_id=file_id,
            data_range=data_range,
            min_file_timestamp_ns=min_file_timestamp_ns,
            max_file_timestamp_ns=max_file_timestamp_ns,
            anchor_ns=None if anchor is None else to_epoch_nanoseconds(anchor),
            topics=list(topics) if topics is not None else [],
        )
        return self.add_files([entry]).single()

    def add_files(self, files: collections.abc.Sequence[SessionFile]) -> BatchResponse[SessionFileView]:
        """Add files to the session, with the topic data they carry.

        Each entry states one file's place in the session in the same terms a
        :py:class:`~roboto.experimental.sessions.SessionDeclaration` uses, so a session built file by file can state
        everything a declared one does. :py:class:`~roboto.experimental.sessions.SessionFile` describes what an entry
        states, including how its time window moves when the file is anchored again.

        Roboto decides every refusal before it adds anything, so an entry it refuses leaves the others added, while a
        failure it did not anticipate, such as a timeout, adds none of them. Sending the same entries again leaves the
        session holding the same files, not each file twice. Roboto then recomputes the session's
        ``min_timestamp_ns`` and ``max_timestamp_ns`` over every file it holds, and this instance holds the new
        values when the call returns.

        Args:
            files: Files to add, each appearing once and listing all of its topics. An empty sequence returns an
                empty response without sending a request.

        Returns:
            One element per entry, in request order, holding either the file as the session holds it or the
            exception Roboto refused the entry with.

        Raises:
            pydantic.ValidationError: The entries name a file more than once, declare more than 500 files and
                topics together (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`), or
                list representations that name one file in two storage formats.
            RobotoNotFoundException: A file an entry names, or a file one of its topics' representations names,
                does not exist in the session's organization or has a status other than
                :py:attr:`~roboto.domain.files.FileStatus.Available`. Nothing is added.
            RobotoUnauthorizedException: The caller cannot add files to sessions in an organization that owns one of
                the files, cannot change a dataset that already holds one of the session's files, cannot read a file
                an entry names, cannot edit a file an entry declares topics on, anchors, or names in a representation,
                or cannot edit topics in the organization while an entry sets ``is_default_for_reads`` on a timeline
                source. Nothing is added.

        Examples:
            >>> from roboto.experimental.sessions import SessionFile
            >>> added = session.add_files(
            ...     [
            ...         SessionFile(file_id="fl_12345"),
            ...         SessionFile(
            ...             file_id="fl_67890",
            ...             min_file_timestamp_ns=0,
            ...             max_file_timestamp_ns=60_000_000_000,
            ...         ),
            ...     ]
            ... )
            >>> print([view.file_id for view in added.succeeded])
        """
        if not files:
            return BatchResponse[SessionFileView](responses=[])

        added = self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/files",
            data=AddFilesRequest(files=list(files)),
        ).to_record(BatchResponse[SessionFileView])
        self.refresh()
        return added

    def attach_to_device(self, device_id: str) -> None:
        """Attach a device to the session.

        A session can have several devices attached, such as every drone of a formation flight. Attaching a device
        that is already attached changes nothing, except that a device Roboto attached because the session's files
        name it stays attached once those files no longer do.

        Args:
            device_id: ID of the device to attach.

        Raises:
            RobotoNotFoundException: No device has this ID in the session's organization, or the session no longer
                exists.

        Examples:
            >>> session.attach_to_device("wingman")
            >>> print(list(session.list_devices()))
        """
        self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/devices",
            data=AttachToDeviceRequest(device_id=device_id),
        )

    def clear_custom_field(self, name: str) -> "Session":
        """Clear one custom-field value on the session, so the field reads back as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a ready custom field defined for sessions in the session's organization.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> session.clear_custom_field("flight_count").custom_fields["flight_count"] is None
            True
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> "Session":
        """Clear several custom-field values on the session, so each field reads back as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            names: Names of ready custom fields defined for sessions in the session's organization.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> session.clear_custom_fields(["pilot", "flight_count"])
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))

    def clear_unix_offset(self) -> "Session":
        """Return the session's data to an offset of 0, removing its wall-clock anchor.

        The session's topic data then reads in its stored timestamps, as nanoseconds since the Unix epoch with
        nothing added, and Roboto recomputes the session's time bounds. The call reaches the same data
        ``set_unix_offset`` writes, and no more, and moves the time windows stated over that data back by the rule
        ``set_unix_offset`` moves them by.

        It succeeds whatever anchors the data carries. A session whose parts are anchored at different instants is
        cleared too, each part moving back by its own offset. Clearing a session that carries no anchor, or has no
        topic data, changes nothing, so repeating the call is safe.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: Returning the data to an offset of 0 would place it, or a time window
                stated over it, before the Unix epoch. Data lands there when its own timestamps are negative, and a
                window does when it starts earlier than its data's anchor.
            RobotoConflictException: Another request added files to the session while the anchor was being cleared.
                Calling again is safe.
            RobotoNotFoundException: The session no longer exists.

        Examples:
            The session's bounds return to its stored timestamps:

            >>> session.min_timestamp_ns
            1700000000250000000
            >>> session = session.clear_unix_offset()
            >>> session.min_timestamp_ns
            250000000
        """
        record = self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}/unix-offset",
        ).to_record(SessionRecord)
        self.__record = record
        return self

    def complete(self) -> "Session":
        """Mark the session complete: declare that all of its files have been added.

        Once the session is complete, Roboto announces it ingested, with a ``session.ingested`` platform event that
        triggers can subscribe to, as soon as every :py:attr:`~roboto.domain.files.FileRecord.ingestable` file it
        waits for is ingested. Files that are not ingestable never delay the announcement.

        Adding a file to a complete session puts it back in progress; mark it complete again once the new files are
        added. When its ingestable files change while it stays complete, such as a file uploaded again, removed, or
        deleted, Roboto announces it again once they are all ingested. Marking a complete session complete changes
        nothing.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> from roboto.experimental.sessions import SessionStatus
            >>> session.add_file("fl_12345")
            >>> session = session.complete()
            >>> session.status is SessionStatus.Complete
            True
        """
        self.__record = self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/complete",
        ).to_record(SessionRecord)
        return self

    def create_event(
        self,
        name: str,
        start_time: Time,
        end_time: typing.Optional[Time] = None,
        topics: collections.abc.Sequence[EventTopicRequest] = (),
        description: typing.Optional[str] = None,
        tags: typing.Optional[StrSequence] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        color: typing.Optional[str] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
    ) -> Event:
        """Create an event on the session.

        Args:
            name: Human-readable name of the event, such as ``"Hard landing"``. Many events can share a name.
            start_time: Inclusive start of the event, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Inclusive end of the event, in the same form. ``None`` makes an instantaneous event.
            topics: Topics, or fields of topics, the event is about, each as a
                ``roboto.experimental.events.EventTopicRequest``. Empty means all of the session's data.
            description: Human-readable description of the event.
            tags: Tags to set on the event.
            metadata: Key-value metadata to set on the event.
            color: CSS color the Roboto web app displays the event in.
            custom_fields: Initial values for the event's custom fields, keyed by field name. Each name must be a
                custom field defined for events in the session's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type.

        Returns:
            The new event, as a ``roboto.experimental.events.Event``.

        Raises:
            RobotoFeatureNotAvailableException: The session's organization does not support events on sessions.
            RobotoIllegalArgumentException: A ``custom_fields`` name is not a ready custom field for events, or its
                value does not match the field's type.
            RobotoInvalidRequestException: ``name`` is blank, the start is negative or after the end, or ``topics``
                names a topic twice, names a topic that does not exist, gives a topic an empty ``field_ids``, or names
                a field that is in none of the schemas of that topic's data in the session.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> event = session.create_event(
            ...     "Hard landing",
            ...     start_time=1_722_870_127_000_000_000,
            ...     end_time=1_722_870_128_500_000_000,
            ...     tags=["landing"],
            ... )
        """
        return Event.create(
            name=name,
            session_id=self.session_id,
            start_time=start_time,
            end_time=end_time,
            topics=topics,
            description=description,
            tags=tags,
            metadata=metadata,
            color=color,
            custom_fields=custom_fields,
            caller_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def delete(self) -> None:
        """Delete the session, with its events, custom-field values and AI summary. This cannot be undone.

        The session's files and the devices attached to it are not deleted.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> session.delete()
        """
        self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}",
        )

    def detach_from_device(self, device_id: str) -> None:
        """Detach a device from the session.

        Detaching a device that is not attached changes nothing. When one of the session's files, or the dataset
        holding the file, names the device, Roboto attaches it again the next time the session's files, or the
        devices they name, change.

        Args:
            device_id: ID of the device to detach.

        Examples:
            >>> session.detach_from_device("wingman")
        """
        self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}/devices",
            data=DetachFromDeviceRequest(device_id=device_id),
        )

    def generate_summary(self) -> StreamingAISummary:
        """Start generating a new AI summary of the session.

        Roboto's AI reads the session's topics, metrics, files and devices and writes the summary in the background.
        This method returns once generation has started; the returned object fetches the rest of the summary from
        Roboto when you wait for it or stream its text. Each generation is charged against the organization's AI
        credits.

        A session has one summary, which every generation and every ``set_summary`` call overwrites:

        - Starting a generation clears the current summary text at once.
        - If the generation fails, the summary is left :py:attr:`~roboto.ai.summary.AISummaryStatus.Failed`.
        - Text written with ``set_summary`` is replaced when a later generation completes.

        Returns:
            The summary being generated, which starts in the
            :py:attr:`~roboto.ai.summary.AISummaryStatus.Pending` state.

        Raises:
            RobotoLimitExceededException: The organization is out of AI credits. Nothing is generated, and the
                current summary is unchanged.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> summary = session.generate_summary()
            >>> print(summary.complete_text)
        """
        initial_summary = self.__roboto_client.post(f"v1/sessions/id/{self.session_id}/summary").to_record(AISummary)
        return PollingStreamingAISummary(
            poll_fn=self.__get_latest_summary,
            poll_on_init=False,
            initial_summary=initial_summary,
        )

    def get_summary(self) -> StreamingAISummary:
        """Fetch the session's AI summary, without generating one.

        Returns:
            The session's summary. If its generation is still running, the summary is
            :py:attr:`~roboto.ai.summary.AISummaryStatus.Pending`; its ``await_completion`` and ``text_stream``
            methods wait for the rest.

        Raises:
            RobotoNotFoundException: The session has no AI summary. Call ``generate_summary`` to create one.

        Examples:
            Get the existing summary, generating one first if there is none:

            >>> from roboto.exceptions import RobotoNotFoundException
            >>> session = Session.from_id("se_12345")
            >>> try:
            ...     summary = session.get_summary()
            ... except RobotoNotFoundException:
            ...     summary = session.generate_summary()
            >>> print(summary.complete_text)
        """
        return PollingStreamingAISummary(poll_fn=self.__get_latest_summary, poll_on_init=True)

    def get_topic(self, topic_name: str) -> Topic:
        """Fetch the topic of this name whose data the session holds, limited to that data.

        The returned topic's ``get_data*`` methods read only the data the session holds, and need neither
        ``start_time`` nor ``end_time``.

        Args:
            topic_name: Exact name of the topic, such as ``"/camera/image"``.

        Returns:
            The topic, as a ``roboto.experimental.topics.Topic``.

        Raises:
            RobotoNotFoundException: The session holds no data of a topic with this name, including when the
                organization has no such topic.

        Examples:
            >>> topic = session.get_topic("/camera/image")
            >>> for timestamp, record in topic.get_data():
            ...     print(timestamp, record)
        """
        quoted_topic_name = urllib.parse.quote_plus(topic_name)
        record = self.__roboto_client.get(
            f"v1/sessions/id/{self.session_id}/topics/name/{quoted_topic_name}",
        ).to_record(TopicIdentityRecord)
        return Topic.from_record(
            record,
            roboto_client=self.__roboto_client,
            context=SessionContext(session_id=self.session_id),
        )

    def ingestion_status(self) -> SessionIngestionStatus:
        """Fetch the session's ingestion state, with the files it still waits for.

        This instance's record is unchanged; call ``refresh`` to update it.

        Examples:
            >>> status = session.ingestion_status()
            >>> print(status.state)
            >>> print([file.relative_path for file in status.pending_files])
        """
        return self.__roboto_client.get(
            f"v1/sessions/id/{self.session_id}/ingestion",
        ).to_record(SessionIngestionStatus)

    def skip_waiting_for(self, file_ids: collections.abc.Sequence[str]) -> SkipWaitingResponse:
        """Stop the session waiting for files to be ingested, such as files whose ingestion failed.

        A complete session is then announced ingested once its other ingestable files are. The skip covers the
        version of each file that is current when it is made: editing the file's tags, metadata, or description keeps
        it, and uploading the file again ends it, so the session waits for the new version. Skipped files stay in the
        session, and :py:attr:`~roboto.experimental.sessions.SessionIngestionStatus.skipped_files` lists them.

        Args:
            file_ids: IDs of the session's files to stop waiting for. A file not in the session is skipped over and
                listed in the response.

        Returns:
            The session's ingestion state after the skip, and the requested files that are not in the session.

        Raises:
            pydantic.ValidationError: ``file_ids`` is empty or names more than 1,000 files.

        Examples:
            >>> response = session.skip_waiting_for(["fl_12345"])
            >>> print(response.ingestion.state, response.not_in_session)
        """
        return self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/ingestion/skip",
            data=SkipWaitingRequest(file_ids=list(file_ids)),
        ).to_record(SkipWaitingResponse)

    def list_devices(self) -> collections.abc.Generator[str, None, None]:
        """List the IDs of the devices attached to the session, in order of device ID.

        The list includes the devices Roboto attached because one of the session's files, or the dataset holding
        the file, names them.

        Yields:
            The ID of each attached device, fetched a page at a time as the generator advances.

        Examples:
            >>> for device_id in session.list_devices():
            ...     print(device_id)
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/sessions/id/{self.session_id}/devices",
                query=query,
            ).to_dict(json_path=["data"])

            for item in page["items"]:
                yield str(item)

            next_token = page["next_token"]
            if not next_token:
                break

    def list_events(
        self,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
    ) -> collections.abc.Generator[Event, None, None]:
        """List the events on the session, in order of start time.

        Args:
            start_time: Time at or after which an event must end to be listed, in nanoseconds since the Unix epoch or
                any value :py:func:`~roboto.time.to_epoch_nanoseconds` accepts. ``None`` sets no such limit.
            end_time: Time at or before which an event must start to be listed, in the same form. ``None`` sets no
                such limit.

        Yields:
            Each matching event, as a ``roboto.experimental.events.Event``, fetched a page at a time as the generator
            advances.

        Raises:
            RobotoFeatureNotAvailableException: The session's organization does not support events on sessions. It
                surfaces on the first iteration.

        Examples:
            >>> for event in Session.from_id("se_12345").list_events():
            ...     print(event.name, event.start_time)
        """
        params: dict[str, typing.Any] = {"limit": MAX_EVENTS_PER_PAGE}
        if start_time is not None:
            params["start_time"] = to_epoch_nanoseconds(start_time)
        if end_time is not None:
            params["end_time"] = to_epoch_nanoseconds(end_time)
        while True:
            page = self.__roboto_client.get(f"v1/sessions/id/{self.session_id}/events", query=params).to_paginated_list(
                EventRecord
            )
            for record in page.items:
                yield Event(record=record, roboto_client=self.__roboto_client)
            if page.next_token is None:
                return
            params["page_token"] = page.next_token

    def list_files(self) -> collections.abc.Generator[SessionFileView, None, None]:
        """List the files the session holds, with the part of each file it holds.

        Yields:
            Each file as a :py:class:`~roboto.experimental.sessions.SessionFileView`, fetched a page at a time as the
            generator advances. ``SessionFileView`` says which of its fields describe the part of the file the
            session holds and which describe the file itself.

        Examples:
            >>> for file in session.list_files():
            ...     print(file.relative_path, file.data_range)
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/sessions/id/{self.session_id}/files",
                query=query,
            ).to_paginated_list(SessionFileView)

            yield from page.items

            next_token = page.next_token
            if not next_token:
                break

    def list_metrics(
        self,
        name_prefix: typing.Optional[str] = None,
        exclude_name_prefix: typing.Optional[str] = None,
    ) -> list[Metric]:
        """List the metrics published to the session, at most 10,000 of them.

        The limit is ``roboto.domain.metrics.MAX_METRIC_LIST_RESULTS``. For a session with more metrics than that,
        the list holds that many and gives no sign that it left any out; which ones it leaves out is not defined.
        Narrow the list with ``name_prefix`` or ``exclude_name_prefix`` to read such a session's metrics in parts.
        The statistics Roboto computes for the session's topics are metrics whose names start with ``topic_stats.``.

        Args:
            name_prefix: Text a metric's name must start with to be listed. ``None`` sets no such limit.
            exclude_name_prefix: Text a metric's name must not start with to be listed. ``None`` leaves out none.

        Returns:
            The session's metrics, each a ``roboto.domain.metrics.Metric``, in no defined order.

        Examples:
            >>> metrics = session.list_metrics()
            >>> for m in metrics:
            ...     print(m.name, m.value)
            >>> own_metrics = session.list_metrics(exclude_name_prefix="topic_stats.")
        """
        return Metric.get_by_session(
            session_id=self.session_id,
            roboto_client=self.__roboto_client,
            name_prefix=name_prefix,
            exclude_name_prefix=exclude_name_prefix,
        )

    def list_topics(self) -> collections.abc.Generator[Topic, None, None]:
        """List the topics whose data the session holds, each limited to that data.

        A topic is listed when the session holds some of its data: a time span of the topic
        (:py:class:`~roboto.domain.topics.TimelineExtentRecord`) on one of the session's files, inside the part of
        that file the session holds and overlapping the time window it holds. Each topic is listed once, however many
        files carry it, ordered by name and then by topic ID.

        Each topic's ``get_data*`` methods read only the data the session holds, and need neither ``start_time`` nor
        ``end_time``. Its ``record`` is a :py:class:`~roboto.experimental.sessions.SessionTopicRecord`, which also
        carries the topic's schemas, time span, file count and message count in the session. The property is typed
        :py:class:`~roboto.domain.topics.TopicIdentityRecord`, so narrow it with ``isinstance`` before reading those
        fields.

        Yields:
            Each topic, as a ``roboto.experimental.topics.Topic``, fetched a page at a time as the generator
            advances.

        Examples:
            >>> for topic in session.list_topics():
            ...     for timestamp, record in topic.get_data():
            ...         print(topic.name, timestamp, record)
        """
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            page = self.__roboto_client.get(
                f"v1/sessions/id/{self.session_id}/topics",
                query=query,
            ).to_paginated_list(SessionTopicRecord)

            for item in page.items:
                yield Topic.from_record(
                    item,
                    roboto_client=self.__roboto_client,
                    context=SessionContext(session_id=self.session_id),
                )

            next_token = page.next_token
            if not next_token:
                break

    def get_topic_stats(self, topic_id: str) -> SessionTopicStats:
        """Fetch the statistics of one topic over the session's data, grouped by field.

        The statistics are the session's ``topic_stats.`` metrics, which Roboto computes after the session is
        announced ingested. A field with no statistics, such as a string or an array, is absent.

        Args:
            topic_id: ID of a topic ``list_topics`` lists.

        Returns:
            The topic's statistics. Its ``fields`` is empty and its ``message_count`` is ``None`` while no statistics
            have been computed for the topic.

        Raises:
            RobotoFeatureNotAvailableException: Topic statistics are not available in the session's organization.
            RobotoNotFoundException: The session holds no data of the topic.

        Examples:
            >>> for topic in session.list_topics():
            ...     stats = session.get_topic_stats(topic.topic_id)
            ...     for field in stats.fields:
            ...         print(topic.name, ".".join(field.path), field.stats.get("max"))
        """
        return self.__roboto_client.get(
            f"v1/sessions/id/{self.session_id}/topics/id/{topic_id}/stats",
        ).to_record(SessionTopicStats)

    def get_topic_stats_run(self) -> SessionTopicStatsRun:
        """Fetch the status of the latest run Roboto triggered to compute the session's topic statistics.

        Roboto runs the ``session_metrics`` action on a session each time the session is announced ingested, but
        only while the organization's session-metrics trigger is installed and enabled. When no run was triggered on
        the latest announcement and none is scheduled, the status may describe the run on an earlier one. While a run
        is :py:attr:`~roboto.experimental.sessions.SessionTopicStatsRunStatus.Running`, ``get_topic_stats`` may return
        statistics from an earlier run, or none.

        Raises:
            RobotoFeatureNotAvailableException: Topic statistics are not available in the session's organization.

        Examples:
            >>> from roboto.experimental.sessions import SessionTopicStatsRunStatus
            >>> run = session.get_topic_stats_run()
            >>> if run.status == SessionTopicStatsRunStatus.Running:
            ...     print("Topic statistics are still being computed")
        """
        return self.__roboto_client.get(f"v1/sessions/id/{self.session_id}/topic-stats/run").to_record(
            SessionTopicStatsRun
        )

    def publish_metrics(
        self,
        metrics: list[MetricEntry],
        device_id: typing.Union[NotSetType, typing.Optional[str]] = NotSet,
    ) -> BatchResponse[Metric]:
        """Publish metric values for the session in one request.

        It calls ``roboto.domain.metrics.Metric.publish`` with the session's ID and organization, so that method's
        failures also apply. Publishing a metric under a name the session already has a value for replaces that
        value. Roboto creates a metric definition for any name the organization does not have one for.

        Args:
            metrics: Metric names and numeric values to publish.
            device_id: ID of the device to associate with each published value. ``None`` associates none. Left unset
                (``NotSet``), Roboto uses the session's attached device, which succeeds only when exactly one device
                is attached.

        Returns:
            One element per entry, in request order, holding either the published metric, as a
            ``roboto.domain.metrics.Metric``, or the exception Roboto refused the entry with.

        Raises:
            RobotoInvalidRequestException: ``device_id`` is left unset and the session has no attached device, or
                more than one.

        Examples:
            Let Roboto take the device from the session's one attached device:

            >>> from roboto.domain.metrics import MetricEntry
            >>> published = session.publish_metrics(
            ...     [
            ...         MetricEntry(name="cpu.usage_max", value=87.2),
            ...         MetricEntry(name="memory.peak_mb", value=2048.0),
            ...     ]
            ... )
            >>> len(published.succeeded)
            2

            Associate the values with a named device:

            >>> session.publish_metrics(
            ...     [MetricEntry(name="cpu.usage_max", value=87.2)],
            ...     device_id="robot01",
            ... )
        """
        return Metric.publish(
            session_id=self.session_id,
            device_id=device_id,
            metrics=metrics,
            caller_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "Session":
        """Set metadata keys on the session, adding new keys and overwriting existing ones.

        Keys the dict does not name keep their values. A dotted key such as ``"weather.condition"`` sets
        ``condition`` inside the nested ``weather`` object. It calls ``update``, whose failures also apply.

        Args:
            metadata: Key-value metadata to set on the session.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session.put_metadata({"weather": "clear", "pilot": "alice"})
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: StrSequence) -> "Session":
        """Add tags to the session, keeping its existing tags.

        A tag the session already has is not added again. It calls ``update``, whose failures also apply.

        Args:
            tags: Tags to add to the session.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session.put_tags(["pre-flight-check", "training"])
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> "Session":
        """Replace this instance's record with the session's current record from Roboto.

        Use it to see changes made after this instance was loaded, by other users or processes or by Roboto itself,
        which recomputes ``min_timestamp_ns`` and ``max_timestamp_ns`` whenever the session's files or their
        anchors change.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The session no longer exists.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> print(session.refresh().status)
        """
        self.__record = self.__roboto_client.get(
            f"v1/sessions/id/{self.session_id}",
        ).to_record(SessionRecord)
        return self

    def remove_file(self, file: typing.Union["File", str]) -> str:
        """Remove one file from the session.

        It calls ``remove_files``, whose failures also apply.

        Args:
            file: File to remove, as a :py:class:`~roboto.domain.files.File` or its ID.

        Returns:
            ID of the removed file.

        Raises:
            RobotoNotFoundException: The session does not hold the file.

        Examples:
            >>> session.remove_file("fl_12345")
        """
        file_id = file if isinstance(file, str) else file.file_id
        return self.remove_files([file_id]).single()

    def remove_files(self, files: collections.abc.Sequence[typing.Union["File", str]]) -> BatchResponse[str]:
        """Remove files from the session.

        Roboto removes every named file the session holds, and reports each file it does not hold as a
        ``RobotoNotFoundException`` in that file's element of the response. A failure Roboto did not anticipate, such
        as a timeout, removes none of the files. Roboto then recomputes the session's ``min_timestamp_ns`` and
        ``max_timestamp_ns`` over the files that remain, and this instance holds the new values when the call returns.

        Args:
            files: Files to remove, each a :py:class:`~roboto.domain.files.File` or its ID. An empty sequence returns
                an empty response without sending a request.

        Returns:
            One element per named file, in request order, holding either its ID or the exception Roboto refused to
            remove it with.

        Raises:
            pydantic.ValidationError: ``files`` names a file more than once, or names more than 500 files
                (:py:const:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST`).

        Examples:
            >>> removed = session.remove_files(["fl_12345", "fl_67890"])
            >>> print(removed.succeeded)
        """
        if not files:
            return BatchResponse[str](responses=[])

        file_ids = [file if isinstance(file, str) else file.file_id for file in files]
        removed = self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}/files",
            data=RemoveFilesRequest(file_ids=file_ids),
        ).to_record(BatchResponse[str])
        self.refresh()
        return removed

    def remove_metadata(self, metadata: StrSequence) -> "Session":
        """Remove metadata keys from the session. Keys the session does not have are ignored.

        A dotted key such as ``"weather.condition"`` removes ``condition`` from inside the nested ``weather`` object.
        It calls ``update``, whose failures also apply.

        Args:
            metadata: Metadata keys to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session.remove_metadata(["pilot", "weather.condition"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(self, tags: StrSequence) -> "Session":
        """Remove tags from the session. Tags the session does not have are ignored.

        It calls ``update``, whose failures also apply.

        Args:
            tags: Tags to remove from the session.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session.remove_tags(["training"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    def set_custom_field(self, name: str, value: typing.Any) -> "Session":
        """Set one custom-field value on the session.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for sessions in the session's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            value: Value to set, which must match the field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> session.set_custom_field("flight_count", 12)
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    def set_custom_fields(self, fields: dict[str, typing.Any]) -> "Session":
        """Set several custom-field values on the session. Fields not named keep their values.

        It calls ``update``, whose failures also apply.

        Args:
            fields: New values keyed by field name. Each name must be a custom field defined for sessions in the
                session's organization, with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`,
                and each value must match that field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> session = Session.from_id("se_12345")
            >>> session.set_custom_fields({"pilot": "alice", "flight_count": 12})
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=fields))

    def set_summary(self, summary: str) -> "Session":
        """Set the text of the session's AI summary.

        Use it when an action or another program writes a more specialized summary than ``generate_summary`` would.
        The text stays until the next generation starts or this method is called again.

        Args:
            summary: Text of the summary, rendered as Markdown. It may include ``roboto://`` links to resources.

        Returns:
            This instance. Its record is unchanged.

        Examples:
            >>> session.set_summary("Flight ended early: the battery voltage dropped below 3.3 V per cell.")
        """
        self.__roboto_client.put(
            f"v1/sessions/id/{self.session_id}/summary",
            data=SetSummaryRequest(summary=summary),
        )
        return self

    def set_unix_offset(self, anchor: Time) -> "Session":
        """Anchor the session's data to wall-clock time.

        ``anchor`` becomes the wall-clock time of stored time 0 for all of the session's topic data, and Roboto
        recomputes the session's time bounds from it.

        The anchor reaches the session's data and no more. Where several sessions share one file, each holding part
        of it, it anchors the parts this session holds and leaves the file's other parts at the anchors they have.
        Data another session also holds is shared, not copied, so that session reads the same anchor. A time window
        stated over a file moves with its data only when all the data the window covers carries one anchor before the
        call and one after.

        Data carries an anchor only when one is given: as the data is added, with the ``anchor`` argument of
        ``add_file`` or :py:attr:`~roboto.experimental.sessions.FileDeclaration.anchor_ns`, or with this method.
        Until then, its offset is 0 and its stored timestamps read as nanoseconds since the Unix epoch. A new anchor
        replaces the one the data carried; giving the one it already carries changes nothing, so repeating the call is
        safe. Declaring a file's data again without an anchor keeps the anchor it has.

        Args:
            anchor: Wall-clock time of stored time 0, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts. It must fall after the Unix epoch; to return the
                session to an offset of 0, use ``clear_unix_offset``.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            TypeError: ``anchor`` is not a :py:const:`~roboto.time.Time`.
            ValueError: ``anchor`` is a boolean, a string that is neither a number nor an ISO 8601 timestamp, the Unix
                epoch or earlier, or at least ``2**63`` nanoseconds after it. The epoch itself and a value that large
                raise ``pydantic.ValidationError``, a subclass of ``ValueError``.
            OverflowError: ``anchor`` is infinite, such as ``float("inf")``.
            RobotoInvalidRequestException: The session has no topic data to anchor; its data already carries several
                different anchors, so Roboto cannot tell which to move from; or the anchor would move the session's
                data, or a time window stated over it, before the Unix epoch or past ``2**63 - 1`` nanoseconds after
                it. To anchor data that carries several anchors, anchor one topic at a time with
                ``roboto.experimental.topics.Topic.set_unix_offset`` on a topic from ``get_topic`` or ``list_topics``,
                or one whole file with :py:meth:`~roboto.domain.files.File.set_timeline_offset`.
            RobotoConflictException: Another request added files to the session while the anchor was being set.
                Calling again is safe.
            RobotoNotFoundException: The session no longer exists.

        Examples:
            The session's bounds become the anchor plus its stored timestamps:

            >>> session.min_timestamp_ns
            250000000
            >>> session = session.set_unix_offset(1_700_000_000_000_000_000)
            >>> session.min_timestamp_ns
            1700000000250000000

            The same anchor given as a ``datetime``:

            >>> import datetime
            >>> session = session.set_unix_offset(
            ...     datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.timezone.utc)
            ... )
            >>> session.min_timestamp_ns
            1700000000250000000
        """
        record = self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/unix-offset",
            data=SetUnixOffsetRequest(unix_epoch_offset_ns=to_epoch_nanoseconds(anchor)),
        ).to_record(SessionRecord)
        self.__record = record
        return self

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        name: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None,
        completion_policy: typing.Union[CompletionPolicy, None, NotSetType] = NotSet,
    ) -> "Session":
        """Update the session's description, name, tags, metadata, custom fields or completion policy.

        An argument left at its default (``NotSet`` or ``None``) leaves that property unchanged.

        Args:
            description: Human-readable description of the session. ``None`` clears it.
            metadata_changeset: Changes to the session's tags and metadata. ``put_tags``, ``remove_tags``,
                ``put_metadata`` and ``remove_metadata`` each make one kind of change.
            name: Human-readable name of the session, at most 120 characters. ``None`` clears it.
            custom_fields_changeset: Changes to the session's custom-field values. Each field name it references must
                be a ready custom field defined for sessions in the session's organization. Fields it does not name
                are unchanged.
            completion_policy: When Roboto marks the session complete on its own. ``None`` removes the policy, so the
                session is marked complete only by ``complete``. On a session in progress that has files, a new
                policy counts its inactivity from now. A complete session stays complete, and the policy applies once
                a file is added to it.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            pydantic.ValidationError: ``name`` is longer than 120 characters.
            RobotoIllegalArgumentException: A ``custom_fields_changeset`` name is not a ready custom field for
                sessions, or a value it sets does not match the field's type.

        Examples:
            >>> session.update(description="formation flight #4", name="flight-2026-04-23-001")

            Let Roboto mark the session complete 30 minutes after its last file is added:

            >>> from roboto.experimental.sessions import CompletionPolicy
            >>> session.update(completion_policy=CompletionPolicy(inactivity_minutes=30))
        """
        request = remove_not_set(
            SessionUpdate(
                description=description,
                metadata_changeset=metadata_changeset,
                name=name,
                custom_fields_changeset=custom_fields_changeset,
                completion_policy=completion_policy,
            )
        )
        record = self.__roboto_client.put(
            f"v1/sessions/id/{self.session_id}",
            data=request,
        ).to_record(SessionRecord)
        self.__record = record
        return self

    def wait_until_ingested(self, timeout: float = 600, poll_interval: int = 15) -> "Session":
        """Wait until every ingestable file the session waits for is ingested and Roboto has announced it ingested.

        The wait ends once Roboto records the announcement, the ``session.ingested`` platform event, which raises
        ``ingestion_count``. A session already announced ingested since it was last marked complete returns at once.

        A session in progress is waited for when it will complete on its own: it has a ``completion_policy`` and
        files, so ``completes_at`` is set, and the wait then includes the policy's inactivity. A session in progress
        that will not complete on its own raises, since only ``complete`` would complete it.

        The default ``timeout`` of 10 minutes may be too short for a session of large recordings. Pass a longer one,
        such as ``timeout=2 * 60 * 60`` for two hours.

        Args:
            timeout: Maximum time to wait, in seconds.
            poll_interval: Time between checks of the session's ingestion state, in seconds.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RuntimeError: The session is in progress and will not complete on its own: it has no completion policy,
                or it has one but no files.
            roboto.waiters.TimeoutError: ``timeout`` passed first. The message says where the session stands and
                lists up to 10 of the files it still waits for. It subclasses the built-in ``TimeoutError``.

        Examples:
            >>> session = session.complete().wait_until_ingested(timeout=2 * 60 * 60)
        """
        last_status: typing.Optional[SessionIngestionStatus] = None
        starting_count: typing.Optional[int] = None
        saw_files_pending = False

        def is_announced() -> bool:
            nonlocal last_status, starting_count, saw_files_pending
            last_status = self.ingestion_status()
            if starting_count is None:
                starting_count = last_status.ingestion_count
            if last_status.state is not SessionIngestionState.Ingested:
                saw_files_pending = True
                if last_status.state is SessionIngestionState.InProgress:
                    self.refresh()
                    self.__refuse_if_it_will_not_complete()
                return False
            if last_status.ingestion_count > starting_count:
                return True
            if saw_files_pending:
                return False
            # Ingested at the first check, with no rise in the count yet: the session was announced before the wait
            # began, or its announcement is not recorded yet. It was announced if Roboto announced it at or after the
            # time it was last marked complete.
            self.refresh()
            completed_at, ingested_at = self.__record.completed_at, self.__record.ingested_at
            return completed_at is not None and ingested_at is not None and ingested_at >= completed_at

        try:
            wait_for(is_announced, timeout=timeout, interval=poll_interval)
        except WaitTimeoutError:
            raise WaitTimeoutError(self.__wait_timeout_message(timeout, last_status)) from None
        return self.refresh()

    def __get_latest_summary(self) -> AISummary:
        return self.__roboto_client.get(f"v1/sessions/id/{self.session_id}/summary").to_record(AISummary)

    def __refuse_if_it_will_not_complete(self) -> None:
        if self.completes_at is not None:
            return
        if self.completion_policy is None:
            raise RuntimeError(
                f"Session '{self.session_id}' is in progress and has no completion policy, so it will not complete "
                "on its own. Call complete() after every file is added, or set a completion policy."
            )
        raise RuntimeError(
            f"Session '{self.session_id}' is in progress and has no files, so it will not complete on its own: its "
            "completion policy counts inactivity from the last file added. Add its files, or call complete()."
        )

    def __wait_timeout_message(self, timeout: float, status: typing.Optional[SessionIngestionStatus]) -> str:
        message = f"Timed out after {timeout:g}s waiting for session '{self.session_id}' to be ingested."
        if status is None:
            return message
        if status.state is SessionIngestionState.InProgress:
            message += " It is still in progress"
            message += (
                f"; Roboto marks it complete at {self.completes_at.isoformat()} unless another file is added first."
                if self.completes_at is not None
                else "."
            )
        else:
            message += " It is complete."
        pending_count = max(status.pending_file_count, len(status.pending_files))
        if pending_count:
            shown = [f.relative_path for f in status.pending_files[:_MAX_PENDING_PATHS_IN_MESSAGE]]
            more = pending_count - len(shown)
            message += f" {pending_count} file(s) are not ingested yet: {', '.join(shown)}"
            message += f", and {more} more." if more > 0 else "."
            message += " ingestion_status() shows each file's latest ingestion run."
        return message
