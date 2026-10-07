# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

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
from ..ingest import TopicDeclaration
from ..topics import SessionContext, Topic
from .operations import (
    AddFilesRequest,
    AttachToDeviceRequest,
    CreateSessionRequest,
    DetachFromDeviceRequest,
    RemoveFilesRequest,
    SessionFile,
    SessionUpdate,
    SetUnixOffsetRequest,
)
from .record import SessionFileView, SessionRecord

if typing.TYPE_CHECKING:
    from ...domain.files import File


class Session:
    """An operational time window of a Device.

    A Session is a drone flight, a vehicle drive, a robot arm test run: some contiguous activity
    in the real world. It groups the recordings, logs, and other data produced during that window.
    Because a Session is bounded by the activity rather than by the recordings, it can span many
    files or cover just a slice of one. Each file it includes can be narrowed to a sub-window of
    that file.

    The Session's aggregate bounds, ``min_timestamp_ns`` and ``max_timestamp_ns`` in Unix-epoch
    nanoseconds, span every file the Session includes. Roboto recomputes them whenever the Session's
    files or the anchors of their data change, and each method of this class that makes such a change
    returns with the updated bounds.

    A Session can reference one or many devices: a single drone for a solo mission, or all of the
    drones in a formation flight. Use :py:meth:`attach_to_device` and :py:meth:`detach_from_device`
    to change which devices it references.

    How to create a Session:

    * :py:meth:`Session.create` accepts zero, one, or many devices, and does not require a name.
    * :py:meth:`~roboto.domain.devices.Device.create_session` creates one named Session on a
      device, optionally declaring its files and topics in the same call.
    * :py:meth:`~roboto.domain.devices.Device.create_sessions` creates many such Sessions on a
      device in one call.
    * :py:meth:`~roboto.domain.datasets.Dataset.create_session` creates a Session for an existing
      Dataset, inferring the devices involved and pre-populating files from the Dataset.

    Once created, include files with :py:meth:`add_file` or :py:meth:`add_files`.

    Examples:
        Create a Session for a drone flight, include a recording, and list its topics:

        >>> from roboto.experimental.sessions import Session
        >>> session = Session.create(name="flight-2026-04-23-001", device_ids=["robot-abc"])
        >>> session.add_file("fl_0123456789abcdef")
        >>> for topic in session.list_topics():
        ...     print(topic.name)
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
    ) -> "Session":
        """Create a new Session, optionally associating it with one or more devices.

        Every call creates a new Session. For the common single-device case, prefer
        :py:meth:`~roboto.domain.devices.Device.create_session`, which identifies the Session by
        name so a resend converges on the Session it already created. To add devices to an existing
        Session later, see :py:meth:`attach_to_device`.

        Args:
            name: Optional short name for the Session (max 120 characters).
            device_ids: Devices to associate with the Session at creation.
                Empty (the default) creates a Session with no associated devices.
            description: Optional description of the Session.
            metadata: Optional initial metadata.
                Sessions are not filterable or sortable by ``metadata`` keys;
                for queryable structured attributes, define a custom field on the ``Session`` entity type.
            tags: Optional initial tags.
                Sessions can be filtered by tag membership but are not sortable by tag.
            custom_fields: Optional initial values for Ready custom fields defined on
                Sessions in the caller's org. Keys must match Ready field names; values
                must satisfy each field's declared type.
            caller_org_id: Caller's org scope. Required when the caller belongs to multiple orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Returns:
            The created Session.

        Raises:
            RobotoNotFoundException: A device in ``device_ids`` does not exist in the caller's org. No Session is
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
        request = CreateSessionRequest(
            name=name,
            device_ids=list(device_ids),
            description=description,
            metadata=metadata or {},
            tags=list(tags) if tags else [],
            custom_fields=custom_fields,
        )
        record = roboto_client.post(
            "v1/sessions",
            data=request,
            caller_org_id=caller_org_id,
        ).to_record(SessionRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_dataset(
        cls,
        dataset_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Session", None, None]:
        """Iterate Sessions whose composition includes any file in the given dataset.

        Args:
            dataset_id: Dataset whose sessions to list.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Yields:
            Sessions, one at a time, following pagination automatically.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> for session in Session.for_dataset("ds_abc"):
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
        """Iterate all Sessions visible to the caller's org.

        Args:
            org_id: Caller's org scope. Required when the caller belongs to multiple orgs.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Yields:
            Sessions, one at a time, following pagination automatically.
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
    def from_id(
        cls,
        session_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Session":
        """Load a Session by ID.

        Args:
            session_id: Session primary key.
            roboto_client: Optional RobotoClient; defaults to the ambient one.

        Returns:
            The Session.

        Raises:
            RobotoNotFoundException: No session with this ID exists.
            RobotoUnauthorizedException: The caller lacks view access to the org that owns the session.

        Examples:
            >>> from roboto.experimental.sessions import Session
            >>> session = Session.from_id("se_abc123")
            >>> session.name
            'flight-2026-04-23-001'
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
        """UTC timestamp when this Session was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Identifier of the user or service which created this Session."""
        return self.__record.created_by

    @property
    def custom_fields(self) -> dict[str, typing.Any]:
        """Custom-field values defined on Sessions in this org.

        Every ``Ready`` :py:class:`~roboto.domain.custom_fields.CustomField` for the org
        appears as a key. Values that have not been set on this session surface as ``None``
        rather than being absent. Empty when no custom fields are defined for the org.

        A :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is returned
        as an ISO 8601 string.
        """
        return self.__record.custom_fields

    @property
    def description(self) -> typing.Optional[str]:
        """Optional description of this Session."""
        return self.__record.description

    @property
    def max_timestamp_ns(self) -> typing.Optional[int]:
        """Latest time covered by this Session, in Unix-epoch nanoseconds.

        ``None`` while the Session includes no files, or only files added without a time window whose topic
        data has no time span registered yet.
        """
        return self.__record.max_timestamp_ns

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """User-supplied metadata attached to this Session.

        Sessions are not filterable or sortable by ``metadata`` keys.
        For queryable structured attributes on a Session, define a custom field on the ``Session`` entity type.
        """
        return self.__record.metadata.copy()

    @property
    def min_timestamp_ns(self) -> typing.Optional[int]:
        """Earliest time covered by this Session, in Unix-epoch nanoseconds.

        ``None`` while the Session includes no files, or only files added without a time window whose topic
        data has no time span registered yet.
        """
        return self.__record.min_timestamp_ns

    @property
    def modified(self) -> typing.Optional[datetime.datetime]:
        """UTC timestamp when this Session was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Identifier of the user or service which last modified this Session."""
        return self.__record.modified_by

    @property
    def name(self) -> typing.Optional[str]:
        """Optional short name of this Session."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """Identifier of the organization that owns this Session."""
        return self.__record.org_id

    @property
    def record(self) -> SessionRecord:
        """Underlying data record for this Session."""
        return self.__record

    @property
    def session_id(self) -> str:
        """Globally unique identifier assigned to this Session on creation."""
        return self.__record.session_id

    @property
    def tags(self) -> list[str]:
        """User-supplied tags on this Session."""
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
        """Include a single file in this Session, with whatever topic data it carries.

        The singular form of :py:meth:`add_files`, taking the fields of one
        :py:class:`~roboto.experimental.sessions.SessionFile` as separate arguments. That class documents
        what each field means; :py:meth:`add_files` documents what the platform does with them.

        Args:
            file: A :py:class:`~roboto.domain.files.File` or a file ID.
            data_range: Slice of the file this Session holds, or ``None`` for the whole file.
            min_file_timestamp_ns: Optional lower bound of the part of the file to include, in the file's
                own timestamps. Must be paired with ``max_file_timestamp_ns``.
            max_file_timestamp_ns: Optional upper bound paired with ``min_file_timestamp_ns``.
            anchor: Optional wall-clock instant at which time 0 of the data added here occurred: an ``int``
                of nanoseconds since the Unix epoch, or any other :py:data:`~roboto.time.Time`, read as
                :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a ``datetime`` or ISO 8601 string is
                that instant; a ``float``, ``Decimal``, or numeric string is seconds since the epoch). Must fall
                after the Unix epoch.
            topics: Topics this file contributes data to, over the part of the file that carries them. Each
                lists the files a read of its data opens in
                :py:attr:`~roboto.experimental.ingest.TopicDeclaration.representations`.

        Returns:
            The file's place in this Session, as :py:meth:`list_files` reports it.

        Raises:
            TypeError: ``anchor`` is not one of the :py:data:`~roboto.time.Time` types.
            ValueError: ``anchor`` is a boolean, a string that is neither seconds nor ISO 8601, or a negative
                number (an ``int``, ``float``, ``Decimal``, or numeric string); rejected client-side, before any
                request is made.
            OverflowError: ``anchor`` is infinite, such as ``float("inf")``; rejected client-side, before any
                request is made.
            pydantic.ValidationError: The arguments break a rule
                :py:class:`~roboto.experimental.sessions.SessionFile` enforces, such as an ``anchor`` at or
                before the Unix epoch or a time window with only one of its two bounds, or the representations
                listed in ``topics`` name one file in two storage formats; rejected client-side, before any request
                is made. The rules for one topic's own representations are enforced earlier, when the caller builds
                its :py:class:`~roboto.experimental.ingest.TopicDeclaration`.
            :py:exc:`~roboto.exceptions.RobotoInvalidRequestException`: With the anchor covering it added, the
                file's data or the window stated here would fall before the Unix epoch or past the largest
                storable Unix-epoch nanosecond value, or the anchor would move a window another Session declared
                over the same data there. Anchor the data at the instant it was recorded.
            :py:exc:`~roboto.exceptions.RobotoDomainException`: Whatever else the platform refused this file
                with.

        Examples:
            Include a whole file:

            >>> session.add_file("fl_0123456789abcdef")

            Include only a sub-window of a file:

            >>> session.add_file(
            ...     "fl_0123456789abcdef",
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
        """Include the given files in this Session, with whatever topic data they carry.

        Each entry states one file's place in this Session, in the same terms a
        :py:class:`~roboto.experimental.sessions.SessionDeclaration` states the files of a Session declared
        whole, so a Session composed file by file can say everything a declared one says.

        The platform decides every refusal before adding anything, so an entry it refuses leaves the others
        added, while a failure it did not anticipate, such as a timeout, adds none of them. Resending converges on
        the same composition rather than duplicating it. The platform then recomputes this Session's aggregate
        bounds across every file it includes, and this instance reflects the new ``min_timestamp_ns`` /
        ``max_timestamp_ns`` on return.

        Args:
            files: Files to include in the Session, each appearing exactly once and listing all of its
                topics; :py:class:`~roboto.experimental.sessions.SessionFile` documents what one entry
                states, including how the window it names survives re-anchoring the file. An empty
                sequence returns an empty response without contacting the platform.

        Returns:
            One element per entry, in request order, holding either the file's place in this Session or
            why the platform refused it.

        Raises:
            pydantic.ValidationError: The sequence names a file more than once, declares more than
                :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST` files and topics
                between them, or lists representations naming one file in two storage formats; rejected
                client-side, before any request is made.
            :py:exc:`~roboto.exceptions.RobotoNotFoundException`: A file an entry names, or a file one of its
                topics' representations names, does not exist in this Session's org or has a status other than
                :py:attr:`~roboto.domain.files.FileStatus.Available`. Nothing is added.
            :py:exc:`~roboto.exceptions.RobotoUnauthorizedException`: The caller lacks permission to manage
                Sessions in the org that owns this Session, cannot edit a file an entry declares topics on,
                a file it anchors, or a file a listed representation names, or lacks topic edit access in that org
                while an entry states ``is_default_for_reads`` on a timeline source. Nothing is added.

        Examples:
            >>> from roboto.experimental.sessions import SessionFile
            >>> added = session.add_files(
            ...     [
            ...         SessionFile(file_id="fl_aaa"),
            ...         SessionFile(
            ...             file_id="fl_bbb",
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
        """Attach a Device to this Session as a subject.

        A Session may have many device attachments.
        For example, a formation flight where multiple drones operate within a single activity window.

        Args:
            device_id: ID of the Device to add as a subject of this Session.

        Raises:
            RobotoNotFoundException: The Device does not exist in this Session's org, or the Session no longer
                exists.

        Examples:
            >>> session.attach_to_device("wingman")
            >>> list(session.list_devices())
            ['lead', 'wingman']
        """
        self.__roboto_client.post(
            f"v1/sessions/id/{self.session_id}/devices",
            data=AttachToDeviceRequest(device_id=device_id),
        )

    def clear_custom_field(self, name: str) -> "Session":
        """Clear a single custom-field value on this session to ``None``."""
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> "Session":
        """Clear multiple custom-field values on this session to ``None``."""
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))

    def clear_unix_offset(self) -> "Session":
        """Return this Session's data to an offset of 0.

        Removes the wall-clock anchor from all of this Session's topic data, so the Session's bounds return to
        their stored values, read as nanoseconds since the Unix epoch with nothing added.

        Clearing reaches this Session's data and no more, exactly the data :py:meth:`set_unix_offset` writes.

        Any anchoring state can be cleared, and repeating the call changes nothing: clearing a Session that carries
        no anchor, or has no topic data at all, is a successful no-op, and a Session made of slices anchored at
        several different instants is still cleared, each slice moving back by its own offset.

        Returns:
            This Session, refreshed with recomputed aggregate bounds.

        Raises:
            RobotoInvalidRequestException: Returning the data to an offset of 0 would start it, or a time range
                declared over it, before the Unix epoch. Data starts there when its own timestamps are negative;
                a range starts there when it begins earlier than its data's anchor.
            RobotoConflictException: A concurrent writer added files to the Session while the clear was being
                applied; retry the call.
            RobotoNotFoundException: The Session no longer exists.
            RobotoUnauthorizedException: The caller lacks permission to manage Sessions in the org that owns this
                Session.

        Examples:
            The recomputed bounds return to the Session's stored values:

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

    def delete(self) -> None:
        """Delete this Session. The files it included and the devices attached to it are not deleted."""
        self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}",
        )

    def detach_from_device(self, device_id: str) -> None:
        """Remove a Device from this Session's subjects.

        Args:
            device_id: ID of the Device to remove as a subject of this Session.
        """
        self.__roboto_client.delete(
            f"v1/sessions/id/{self.session_id}/devices",
            data=DetachFromDeviceRequest(device_id=device_id),
        )

    def get_topic(self, topic_name: str) -> Topic:
        """Return the named Topic, scoped to this Session.

        The returned Topic is scoped to this Session's associated files and defaults its
        read window to this Session's aggregate bounds, so ``get_data*`` reads just this
        Session's data without an explicit window.

        Args:
            topic_name: Exact name of the topic to retrieve (e.g. ``"/camera/image"``).

        Returns:
            The matching :py:class:`~roboto.experimental.topics.Topic`.

        Raises:
            RobotoNotFoundException: No topic with ``topic_name`` is reachable from this Session
                (the topic is absent from the org, or this Session holds none of its data).
            RobotoUnauthorizedException: The caller lacks permission to view Sessions in the org
                that owns this Session.

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
            context=SessionContext(
                session_id=self.session_id,
                start_time=self.min_timestamp_ns,
                end_time=self.max_timestamp_ns,
            ),
        )

    def list_devices(self) -> collections.abc.Generator[str, None, None]:
        """Iterate the device IDs attached as subjects of this Session, paginated."""
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

    def list_files(self) -> collections.abc.Generator[SessionFileView, None, None]:
        """Iterate the files this Session includes, following pagination automatically.

        Yields:
            :py:class:`SessionFileView` entries, each carrying the part of the file this Session holds (the
            optional ``data_range`` slice and ``min_wall_clock_timestamp_ns`` / ``max_wall_clock_timestamp_ns``
            window), the ``unix_epoch_offset_ns`` the platform added to reach that window, and display fields of
            the file itself (name, dataset, tags, size, ...).
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

    def list_metrics(self) -> list[Metric]:
        """Return all metrics published to this Session.

        Returns:
            List of :py:class:`~roboto.domain.metrics.Metric` instances for this Session.

        Examples:
            >>> metrics = session.list_metrics()
            >>> for m in metrics:
            ...     print(m.name, m.value)
        """
        return Metric.get_by_session(
            session_id=self.session_id,
            roboto_client=self.__roboto_client,
        )

    def list_topics(self) -> collections.abc.Generator[Topic, None, None]:
        """Iterate the topics reachable from this Session, following pagination.

        A topic is yielded only when this Session holds some of its data: a time span of the topic
        (:py:class:`~roboto.domain.topics.TimelineExtentRecord`) on one of the Session's files, inside the slice
        the Session holds of that file and overlapping the time window it holds. Each topic is yielded once however
        many files and partitions carry it, ordered by ``name`` with ``topic_id`` as a deterministic tiebreaker.

        A yielded Topic is scoped to this Session's files and defaults its read window to this
        Session's aggregate bounds, so :py:meth:`~roboto.experimental.topics.Topic.get_data`
        (and the other ``get_data*`` methods) read just this Session's data without an explicit window.

        Yields:
            :py:class:`~roboto.experimental.topics.Topic` instances.

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
            ).to_paginated_list(TopicIdentityRecord)

            for item in page.items:
                yield Topic.from_record(
                    item,
                    roboto_client=self.__roboto_client,
                    context=SessionContext(
                        session_id=self.session_id,
                        start_time=self.min_timestamp_ns,
                        end_time=self.max_timestamp_ns,
                    ),
                )

            next_token = page.next_token
            if not next_token:
                break

    def publish_metrics(
        self,
        metrics: list[MetricEntry],
        device_id: typing.Union[NotSetType, typing.Optional[str]] = NotSet,
    ) -> BatchResponse[Metric]:
        """Record metric values for this Session in a single network call.

        Convenience wrapper around :py:meth:`~roboto.domain.metrics.Metric.publish`
        that supplies this Session's ``session_id`` and ``org_id``. Republishing a
        metric under the same name replaces its previous value for this Session.

        If a metric definition does not already exist for a given name it is
        created automatically.

        Args:
            metrics: Metric names and numeric values to record.
            device_id: Device to associate with each published value, or
                :py:data:`None` to opt out. When omitted, the server infers a
                device from this Session's attached devices: the call succeeds
                only if exactly one device is associated and is rejected when
                zero or more than one are.

        Returns:
            One element per metric entry, in request order, holding either the
            recorded :py:class:`~roboto.domain.metrics.Metric` or why the platform
            refused it.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoInvalidRequestException`:
                ``device_id`` was omitted and this Session has zero or more
                than one attached devices.

        Examples:
            Let the server infer the device from this Session's single attached device:

            >>> from roboto.domain.metrics import MetricEntry
            >>> published = session.publish_metrics(
            ...     [
            ...         MetricEntry(name="cpu.usage_max", value=87.2),
            ...         MetricEntry(name="memory.peak_mb", value=2048.0),
            ...     ]
            ... )
            >>> len(published.succeeded)
            2

            Attach to an explicit device, overriding inference:

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
        """Add or update metadata fields on this Session.

        Args:
            metadata: Field-to-value map. Existing fields are overwritten;
                fields not in this map are left unchanged.

        Returns:
            This Session, refreshed from the server response.

        Examples:
            >>> session.put_metadata({"weather": "clear", "pilot": "alice"})
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: StrSequence) -> "Session":
        """Add tags to this Session.

        Tags already present on the Session are not duplicated.

        Args:
            tags: Tags to add.

        Returns:
            This Session, refreshed from the server response.

        Examples:
            >>> session.put_tags(["pre-flight-check", "training"])
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> "Session":
        """Re-read this Session from the platform, replacing every property backed by its record.

        Call it when something other than this instance changed the Session: the aggregate bounds
        ``min_timestamp_ns`` and ``max_timestamp_ns`` are recomputed whenever a Session's composition or
        anchoring changes, including by another caller.

        Returns:
            This Session.
        """
        self.__record = self.__roboto_client.get(
            f"v1/sessions/id/{self.session_id}",
        ).to_record(SessionRecord)
        return self

    def remove_file(self, file: typing.Union["File", str]) -> str:
        """Remove a single file from this Session.

        The singular form of :py:meth:`remove_files`.

        Args:
            file: A :py:class:`~roboto.domain.files.File` or a file ID.

        Returns:
            The ID of the removed file.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoNotFoundException`: This Session does not hold the file.
        """
        file_id = file if isinstance(file, str) else file.file_id
        return self.remove_files([file_id]).single()

    def remove_files(self, files: collections.abc.Sequence[typing.Union["File", str]]) -> BatchResponse[str]:
        """Remove the given files from this Session.

        A file this Session does not hold is reported as its own element rather than failing the call, while
        a failure the platform did not anticipate, such as a timeout, removes none of the files. The platform
        then recomputes this Session's aggregate bounds across the files that remain, and this instance
        reflects the new ``min_timestamp_ns`` / ``max_timestamp_ns`` on return.

        Args:
            files: Files to remove, each a :py:class:`~roboto.domain.files.File` or a file ID. An empty
                sequence returns an empty response without contacting the platform.

        Returns:
            One element per named file, in request order, holding either its ID or why the platform
            refused to remove it.

        Raises:
            pydantic.ValidationError: The sequence names a file more than once, or names more than
                :py:data:`~roboto.experimental.ingest.MAX_FILES_AND_TOPICS_PER_REQUEST` files; rejected
                client-side, before any request is made.
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
        """Remove metadata keys from this Session.

        Args:
            metadata: Metadata keys to remove. Dot notation addresses nested keys (``"weather.condition"``).

        Returns:
            This Session, refreshed from the server response.

        Examples:
            >>> session.remove_metadata(["pilot", "weather.condition"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(self, tags: StrSequence) -> "Session":
        """Remove the given tags from this Session.

        Args:
            tags: Tags to remove. Tags not present on the Session are
                silently ignored.

        Returns:
            This Session, refreshed from the server response.

        Examples:
            >>> session.remove_tags(["training"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    def set_custom_field(self, name: str, value: typing.Any) -> "Session":
        """Set a single custom-field value on this session.

        ``name`` must be the name of a
        :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` custom
        field for this session's org and the
        :py:class:`~roboto.domain.custom_fields.TargetEntityType.Session`
        entity type; ``value`` must satisfy the field's declared type.
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    def set_custom_fields(self, fields: dict[str, typing.Any]) -> "Session":
        """Set or overwrite multiple custom-field values on this session.

        Each key must name a Ready custom field for this session's org and the
        :py:class:`~roboto.domain.custom_fields.TargetEntityType.Session`
        entity type; each value must satisfy the field's declared type.
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=fields))

    def set_unix_offset(self, anchor: Time) -> "Session":
        """Anchor this Session's data to wall-clock time.

        ``anchor`` becomes the wall-clock instant of stored time 0 for all of this Session's topic data, and the
        Session's aggregate bounds are recomputed to reflect it.

        This write reaches this Session's data and no more. Where several Sessions share one file, each owning a
        slice of it, it anchors the slices this Session holds and leaves the file's other slices at whatever instant
        they were given. Data another Session also holds is shared, not copied, so that Session reads the same anchor.

        An anchor exists only when a caller supplies one, either as the data is added (the ``anchor`` argument of
        :py:meth:`add_file`, or ``anchor_ns`` on a :py:class:`~roboto.experimental.sessions.SessionFile`) or through
        this method. Until then, the data carries an offset of 0 and its stored timestamps are read as nanoseconds
        since the Unix epoch. Applying an anchor overwrites whatever anchor the data carried before; applying the
        one it already carries changes nothing, so repeating the call succeeds. An anchor survives re-ingest:
        redeclaring a slice without supplying an anchor preserves the one it already had.

        Args:
            anchor: Wall-clock instant of stored time 0: an ``int`` of nanoseconds since the Unix epoch, or any other
                :py:data:`~roboto.time.Time`, read as :py:func:`~roboto.time.to_epoch_nanoseconds` reads it (a
                ``datetime`` or ISO 8601 string is that instant; a ``float``, ``Decimal``, or numeric string is seconds
                since the epoch). Must fall after the Unix epoch: zero is not an anchor (use
                :py:meth:`clear_unix_offset` to return the Session to an offset of 0), and earlier instants are
                rejected.

        Returns:
            This Session, refreshed with recomputed aggregate bounds.

        Raises:
            TypeError: ``anchor`` is not one of the :py:data:`~roboto.time.Time` types.
            ValueError: ``anchor`` is a boolean, a string that is neither seconds nor ISO 8601, zero, before the Unix
                epoch, or too large for a signed 64-bit integer of nanoseconds; rejected client-side, before any request
                is made. A range refusal is raised as :py:exc:`pydantic.ValidationError`, a subclass of ``ValueError``.
            OverflowError: ``anchor`` is infinite, such as ``float("inf")``; rejected client-side, before any
                request is made.
            RobotoInvalidRequestException: Any of three cases: the Session has no topic data to anchor; the
                Session's own data already carries several distinct anchors, and the server will not pick one of
                them to move everything from (anchor less than a whole Session at a time instead, either one topic
                with :py:meth:`~roboto.experimental.topics.Topic.set_unix_offset` on a Topic from
                :py:meth:`get_topic` or :py:meth:`list_topics`, or one whole file with
                :py:meth:`~roboto.domain.files.File.set_timeline_offset`); or the anchor would move the Session's
                data, or a time range declared over it, before the Unix epoch or past the largest storable
                Unix-epoch nanosecond value; anchor the data at the instant it was recorded.
            RobotoConflictException: A concurrent writer added files to the Session while the anchor was being
                applied; retry the call.
            RobotoNotFoundException: The Session no longer exists.
            RobotoUnauthorizedException: The caller lacks permission to manage Sessions in the org that owns this
                Session.

        Examples:
            The recomputed bounds are the offset plus the Session's stored values:

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
    ) -> "Session":
        """Update mutable Session fields.

        Fields left at the ``NotSet`` default are preserved;
        for nullable string fields (``description``, ``name``), pass ``None`` to clear.

        Args:
            description: New description for the Session. Set to ``None`` to clear the description.
                Leave at the default to leave the description unchanged.
            metadata_changeset: Tag and metadata changes to apply (put/remove tags and fields).
                See :py:meth:`put_tags`, :py:meth:`remove_tags`, :py:meth:`put_metadata`,
                and :py:meth:`remove_metadata` for shorthand helpers.
            name: New name for the Session. Set to ``None`` to clear the name.
                Leave at the default to leave the name unchanged.
            custom_fields_changeset: Changes to apply to Ready custom-field values
                on this session. Field names not referenced by the changeset are
                left unchanged.

        Returns:
            This Session, refreshed from the server response.

        Examples:
            >>> session.update(description="formation flight #4", name="flight-2026-04-23-001")
        """
        request = remove_not_set(
            SessionUpdate(
                description=description,
                metadata_changeset=metadata_changeset,
                name=name,
                custom_fields_changeset=custom_fields_changeset,
            )
        )
        record = self.__roboto_client.put(
            f"v1/sessions/id/{self.session_id}",
            data=request,
        ).to_record(SessionRecord)
        self.__record = record
        return self
