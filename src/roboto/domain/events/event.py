# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import datetime
import pathlib
import typing

from ...association import Association
from ...exceptions import (
    RobotoInvalidRequestException,
)
from ...http import RobotoClient
from ...logging import default_logger
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from ...time import Time, to_epoch_nanoseconds
from ...updates import (
    CustomFieldChangeset,
    MetadataChangeset,
    StrSequence,
)
from ...warnings import experimental
from ..files import File
from ..topics import (
    MessagePath,
    Timestamp,
    Topic,
    TopicDataService,
)
from .operations import (
    MAX_EVENTS_PER_DELETE_BATCH,
    CreateEventRequest,
    DeleteEventsRequest,
    EventDisplayOptions,
    EventDisplayOptionsChangeset,
    QueryEventsForAssociationsRequest,
    UpdateEventRequest,
)
from .record import EventRecord

if typing.TYPE_CHECKING:  # pragma: no cover
    import pandas  # pants: no-infer-dep

logger = default_logger()


@dataclasses.dataclass
class GetDataArgs:
    """Topic to read and arguments to read it with, chosen from an event's associations.

    ``Event.get_data`` and ``Event.get_data_as_df`` build one to read an event's data, so most code never builds it.
    """

    topic: Topic
    """Topic to read."""

    message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None
    """Message paths to include. ``None`` includes every message path."""

    message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None
    """Message paths to leave out. ``None`` leaves out none."""

    start_time: typing.Optional[Time] = None
    """Inclusive start of the time range to read.

    In nanoseconds since the Unix epoch, or any value :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
    """

    end_time: typing.Optional[Time] = None
    """Exclusive end of the time range to read, in the same form as ``start_time``."""

    cache_dir: typing.Union[str, pathlib.Path, None] = None
    """Directory to download the topic's data to.

    ``None`` uses :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.
    """


class Event:
    """An event: an annotation that ties datasets, files, topics, or message paths to a span of time, such as a takeoff.

    An event covers either a single point in time or a range, and carries a name, tags, key-value metadata,
    custom-field values, and display options such as its color. Roboto shows events on the timeline and plots of the
    data they annotate, and ``get_data`` reads that data within the event's time span. An event is an annotation on
    data, not a platform event.

    Get an ``Event`` from ``create``, ``from_id``, or one of the ``get_by_*`` class methods. Each instance holds a copy
    of the event's record: methods that change the event update that copy from Roboto's response, and ``refresh``
    fetches changes made elsewhere.
    """

    __roboto_client: RobotoClient
    __record: EventRecord

    @classmethod
    def create(
        cls,
        name: str,
        start_time: Time,
        end_time: typing.Optional[Time] = None,
        associations: typing.Optional[collections.abc.Collection[Association]] = None,
        dataset_ids: typing.Optional[collections.abc.Collection[str]] = None,
        file_ids: typing.Optional[collections.abc.Collection[str]] = None,
        topic_ids: typing.Optional[collections.abc.Collection[str]] = None,
        message_path_ids: typing.Optional[collections.abc.Collection[str]] = None,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        display_options: typing.Optional[EventDisplayOptions] = None,
        custom_fields: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Event":
        """Create an event on at least one dataset, file, topic, or message path.

        The event is associated with everything named by ``associations``, ``dataset_ids``, ``file_ids``,
        ``topic_ids``, and ``message_path_ids`` together. Each of those arguments is optional, but between them they
        must name at least one item.

        Args:
            name: Human-readable name of the event, such as ``"Takeoff"``. Must not be blank. Roboto does not require
                names to be unique.
            start_time: Start of the event, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: End of the event, in the same form. ``None`` creates an event at the single point in time
                ``start_time``.
            associations: Datasets, files, topics, and message paths to associate the event with, as
                :py:class:`~roboto.association.Association` objects.
            dataset_ids: IDs of datasets to associate the event with.
            file_ids: IDs of files to associate the event with.
            topic_ids: IDs of topics to associate the event with.
            message_path_ids: IDs of message paths to associate the event with.
            description: Human-readable description of the event.
            metadata: Key-value metadata to set on the event. ``None`` sets none.
            tags: Tags to set on the event. ``None`` sets none.
            display_options: How Roboto displays the event, such as its color. ``None`` lets Roboto choose.
            custom_fields: Initial values for the event's custom fields, keyed by field name. Each name must be a
                custom field defined for events in the organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type. ``None`` sets none.
            caller_org_id: Organization to create the event in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new event.

        Raises:
            RobotoInvalidRequestException: The arguments name no dataset, file, topic, or message path; one of them
                does not exist or belongs to another organization; or ``start_time`` is after ``end_time``.
            RobotoIllegalArgumentException: ``name`` is blank, or a ``custom_fields`` name is not a ready custom field
                for events, or its value does not match the field's type.
            ValueError: ``start_time`` or ``end_time`` is negative, or is a string that is not a time.
            RobotoUnauthorizedException: The caller may not change one of the datasets or files the event would be
                attached to.

        Examples:
            Create an event for a sensor anomaly on a specific topic:

            >>> from roboto.domain.events import Event
            >>> event = Event.create(
            ...     name="Temperature Spike",
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ...     description="Unusual temperature readings detected",
            ...     topic_ids=["tp_abc123"],
            ...     tags=["anomaly", "temperature"],
            ...     metadata={"severity": "high", "sensor_id": "temp_01"},
            ... )

            Create an event at a single point in time on a file, giving the time as a string of seconds:

            >>> event = Event.create(
            ...     name="System Boot",
            ...     start_time="1722870127.699468923",
            ...     file_ids=["fl_xyz789"],
            ...     tags=["system", "boot"],
            ... )

            Create an event with display options:

            >>> from roboto.domain.events import EventDisplayOptions
            >>> event = Event.create(
            ...     name="Critical Alert",
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ...     dataset_ids=["ds_abc123"],
            ...     display_options=EventDisplayOptions(color="red"),
            ...     metadata={"alert_type": "critical", "component": "engine"},
            ... )
        """

        roboto_client = RobotoClient.defaulted(roboto_client)

        coalesced_associations = Association.coalesce(
            associations=associations,
            dataset_ids=dataset_ids,
            file_ids=file_ids,
            topic_ids=topic_ids,
            message_path_ids=message_path_ids,
            throw_on_empty=True,
        )

        request = CreateEventRequest(
            associations=coalesced_associations,
            start_time=to_epoch_nanoseconds(start_time),
            end_time=to_epoch_nanoseconds(end_time or start_time),
            description=description,
            metadata=metadata or {},
            tags=tags or [],
            name=name,
            display_options=display_options,
            custom_fields=custom_fields,
        )
        record = roboto_client.post("v1/events/create", caller_org_id=caller_org_id, data=request).to_record(
            EventRecord
        )
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def get_by_dataset(
        cls,
        dataset_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        strict_associations: bool = False,
    ) -> collections.abc.Generator["Event", None, None]:
        """Yield the events on a dataset and, by default, on its files, topics, and message paths.

        Fetches the events a page at a time, as the iteration reaches each page.

        Args:
            dataset_id: ID of the dataset to find events for.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            strict_associations: Whether to yield only events associated with the dataset itself. When ``False``,
                also yields events on the dataset's files, topics, and message paths.

        Yields:
            The matching events.

        Raises:
            RobotoNotFoundException: No dataset has this ID, and ``strict_associations`` is ``False``; with ``True``,
                an unknown ID yields no events. It surfaces on the first iteration.

        Examples:
            Get all events for a dataset (including file and topic events):

            >>> events = list(Event.get_by_dataset("ds_abc123"))
            >>> for event in events:
            ...     print(f"Event: {event.name} at {event.start_time}")

            Get only events directly associated with the dataset:

            >>> strict_events = list(Event.get_by_dataset("ds_abc123", strict_associations=True))
            >>> print(f"Found {len(strict_events)} dataset-level events")

            Process events as they arrive, without collecting them into a list:

            >>> for event in Event.get_by_dataset("ds_abc123"):
            ...     if "anomaly" in event.tags:
            ...         print(f"Anomaly event: {event.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        if strict_associations is True:
            for event in Event.get_by_associations([Association.dataset(dataset_id)], roboto_client):
                yield event
            return

        next_token: typing.Optional[str] = None
        while True:
            results = roboto_client.get(
                f"v1/datasets/{dataset_id}/events",
                query={"page_token": next_token} if next_token is not None else None,
            ).to_paginated_list(EventRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def get_by_file(
        cls, file_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> collections.abc.Generator["Event", None, None]:
        """Yield the events associated with a file itself, leaving out events on only its topics or message paths.

        It calls ``get_by_associations``, whose failures also apply.

        Args:
            file_id: ID of the file to find events for.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            The matching events.

        Examples:
            Get all events for a specific file:

            >>> events = list(Event.get_by_file("fl_xyz789"))
            >>> for event in events:
            ...     print(f"File event: {event.name}")

            Check if a file has any events:

            >>> file_events = list(Event.get_by_file("fl_xyz789"))
            >>> if file_events:
            ...     print(f"File has {len(file_events)} events")
            ... else:
            ...     print("No events found for this file")
        """
        return Event.get_by_associations([Association.file(file_id)], roboto_client)

    @classmethod
    def get_by_message_path(
        cls,
        message_path_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """Yield the events associated with a message path.

        It calls ``get_by_associations``, whose failures also apply.

        Args:
            message_path_id: ID of the message path to find events for, beginning with ``mp_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            The matching events.

        Examples:
            Get all events for a specific message path:

            >>> events = list(Event.get_by_message_path("mp_abc123"))
            >>> for event in events:
            ...     print(f"Message path event: {event.name}")

            Keep the events that start at or after a given time:

            >>> events = Event.get_by_message_path("mp_abc123")
            >>> filtered_events = [event for event in events if event.start_time >= 1722870127699468923]
        """
        return Event.get_by_associations([Association.msgpath(message_path_id)], roboto_client)

    @classmethod
    def get_by_topic(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """Yield the events associated with a topic itself, leaving out events on only its message paths.

        It calls ``get_by_associations``, whose failures also apply.

        Args:
            topic_id: ID of the topic to find events for.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            The matching events.

        Examples:
            Get all events for a specific topic:

            >>> events = list(Event.get_by_topic("tp_abc123"))
            >>> for event in events:
            ...     print(f"Topic event: {event.name}")

            Count the topic's events tagged ``anomaly``:

            >>> events = list(Event.get_by_topic("tp_abc123"))
            >>> anomaly_events = [e for e in events if "anomaly" in e.tags]
            >>> print(f"Found {len(anomaly_events)} anomaly events")
        """
        return Event.get_by_associations([Association.topic(topic_id)], roboto_client)

    @classmethod
    def get_by_associations(
        cls,
        associations: collections.abc.Collection[Association],
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """Yield the events associated with any of the given datasets, files, topics, or message paths.

        An event matches only when it is associated with one of ``associations`` itself: an event on a file's topic
        does not match the file. Events the caller cannot see are left out, without an error. Events come in order
        of start time, fetched a page at a time as the iteration reaches each page.

        Args:
            associations: Datasets, files, topics, and message paths to find events for, as
                :py:class:`~roboto.association.Association` objects. Must contain at least one.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            The matching events.

        Raises:
            RobotoInvalidRequestException: ``associations`` is empty. It surfaces on the first iteration.

        Examples:
            Find the events on a topic or a file:

            >>> from roboto import Association
            >>> associations = [Association.topic("tp_abc123"), Association.file("fl_xyz789")]
            >>> events = list(Event.get_by_associations(associations))
            >>> for event in events:
            ...     print(f"Event: {event.name}")

            Find the events on a dataset or a file:

            >>> associations = [Association.dataset("ds_abc123"), Association.file("fl_xyz789")]
            >>> events = list(Event.get_by_associations(associations))
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            request = QueryEventsForAssociationsRequest(associations=list(associations), page_token=next_token)

            results = roboto_client.post(
                "v1/events/query/for_associations",
                data=request,
            ).to_paginated_list(EventRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def from_id(cls, event_id: str, roboto_client: typing.Optional[RobotoClient] = None) -> "Event":
        """Fetch an event by its ID.

        Args:
            event_id: ID of the event, beginning with ``ev_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No event has this ID.

        Examples:
            Load an event by ID:

            >>> event = Event.from_id("ev_abc123")
            >>> print(f"Event: {event.name}")
            >>> print(f"Created: {event.created}")

            Load an event and change its description:

            >>> event = Event.from_id("ev_abc123")
            >>> event = event.set_description("Updated description")
            >>> print(event.description)
            Updated description
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/events/id/{event_id}").to_record(EventRecord)
        return cls(record, roboto_client)

    @classmethod
    def delete_many(
        cls,
        event_ids: collections.abc.Collection[str],
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        """Delete several events. This cannot be undone.

        IDs that match no event are skipped, so a call can be retried with the same IDs. Sends the IDs in requests of
        at most 1,000 events each (:py:const:`~roboto.domain.events.MAX_EVENTS_PER_DELETE_BATCH`), in order. Each
        request deletes all of its events or none: when the caller cannot delete one of them, that request raises
        ``RobotoUnauthorizedException`` and deletes nothing. Events deleted by earlier requests stay deleted, and later
        requests are not sent. Deleting each event takes the permission ``delete`` takes.

        Args:
            event_ids: IDs of the events to delete, any number of them.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            Delete several events at once:

            >>> from roboto.domain.events import Event
            >>> Event.delete_many(["ev_abc123", "ev_def456", "ev_ghi789"])

            Delete the events surfaced by a query:

            >>> events = list(Event.get_by_dataset("ds_abc123"))
            >>> Event.delete_many([event.event_id for event in events])
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        event_ids = list(event_ids)
        for batch_start in range(0, len(event_ids), MAX_EVENTS_PER_DELETE_BATCH):
            batch = event_ids[batch_start : batch_start + MAX_EVENTS_PER_DELETE_BATCH]
            roboto_client.post(
                "v1/events/delete",
                data=DeleteEventsRequest(event_ids=batch),
            )

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented

        return self.__record == other.__record

    def __init__(self, record: EventRecord, roboto_client: typing.Optional[RobotoClient] = None) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def color(self) -> typing.Optional[str]:
        """Display color of the event, as any CSS color value, such as ``"red"``, ``"#ff0000"`` or ``"rgb(255 0 0)"``.

        ``None`` when no color is set, so Roboto chooses one. :py:attr:`~roboto.domain.events.EventDisplayOptions.color`
        says what the color is for.
        """
        return self.display_options.color if self.display_options else None

    @property
    def created(self) -> datetime.datetime:
        """Time the event was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """Principal that created the event, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the event, or ``None`` if it has none."""
        return self.__record.description

    @property
    def display_options(self) -> typing.Optional[EventDisplayOptions]:
        """How the Roboto web app displays the event, such as its color, or ``None`` if no display options are set."""
        return self.__record.display_options

    @property
    def end_time(self) -> int:
        """End of the event's time span, in nanoseconds since the Unix epoch.

        :py:attr:`~roboto.domain.events.EventRecord.end_time` says how it relates to ``start_time``. Reading an event
        at a single point in time with ``get_data`` returns no messages, because the read excludes ``end_time``.
        """
        return self.__record.end_time

    @property
    def event_id(self) -> str:
        """Unique ID of the event, beginning with ``ev_``."""
        return self.__record.event_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata on the event."""
        return self.__record.metadata

    @property
    @experimental
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields the organization defines for events, keyed by field name.

        :py:attr:`~roboto.domain.events.EventRecord.custom_fields` says which fields appear as keys. A
        :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is an ISO 8601 string.
        """
        return self.__record.custom_fields

    @property
    def modified(self) -> datetime.datetime:
        """Time the event was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """Principal that last modified the event, in the same ``<type>:<id>`` form as ``created_by``."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Human-readable name of the event, such as ``"Takeoff"`` or ``"CPU Spike"``.

        :py:attr:`~roboto.domain.events.EventRecord.name` says whether names must be unique.
        """
        return self.__record.name

    @property
    def record(self) -> EventRecord:
        """Record of the event that this instance holds.

        ``refresh`` replaces it with the current one.
        """
        return self.__record

    @property
    def start_time(self) -> int:
        """Start of the event's time span, in nanoseconds since the Unix epoch."""
        return self.__record.start_time

    @property
    def tags(self) -> list[str]:
        """Tags on the event."""
        return self.__record.tags

    def dataset_ids(self, strict_associations: bool = False) -> list[str]:
        """Return the IDs of the datasets the event is associated with, each once.

        Reads the event's record and makes no request.

        Args:
            strict_associations: Whether to return only datasets the event is associated with directly. When
                ``False``, also returns the datasets that contain the event's files, topics, and message paths.

        Examples:
            Get all associated dataset IDs:

            >>> event = Event.from_id("ev_abc123")
            >>> dataset_ids = event.dataset_ids()
            >>> print(f"Associated with {len(dataset_ids)} datasets")

            Get only directly associated datasets:

            >>> strict_dataset_ids = event.dataset_ids(strict_associations=True)
            >>> print(f"Directly associated with {len(strict_dataset_ids)} datasets")
        """
        return list(
            {
                association.dataset_id
                for association in self.__record.associations
                if (strict_associations is False or association.is_dataset) and association.dataset_id is not None
            }
        )

    def delete(self) -> None:
        """Delete the event. This cannot be undone.

        Deleting an event that no longer exists succeeds and changes nothing. Deleting takes permission to change a
        dataset or file the event is attached to; an event attached to none can be deleted by any member of its
        organization.

        Examples:
            Delete an event:

            >>> event = Event.from_id("ev_abc123")
            >>> event.delete()

            Delete an event only if it has a given tag:

            >>> event = Event.from_id("ev_abc123")
            >>> if "temporary" in event.tags:
            ...     event.delete()
            ...     print("Temporary event deleted")
        """
        self.__roboto_client.delete(f"v1/events/id/{self.event_id}")

    def file_ids(self, strict_associations: bool = False) -> list[str]:
        """Return the IDs of the files the event is associated with, each once.

        Reads the event's record and makes no request.

        Args:
            strict_associations: Whether to return only files the event is associated with directly. When ``False``,
                also returns the files that contain the event's topics and message paths.

        Examples:
            Get all associated file IDs:

            >>> event = Event.from_id("ev_abc123")
            >>> file_ids = event.file_ids()
            >>> print(f"Associated with {len(file_ids)} files")

            Get only directly associated files:

            >>> strict_file_ids = event.file_ids(strict_associations=True)
            >>> for file_id in strict_file_ids:
            ...     print(f"Directly associated file: {file_id}")
        """
        return list(
            {
                association.file_id
                for association in self.__record.associations
                if (strict_associations is False or association.is_file) and association.file_id is not None
            }
        )

    def get_data(
        self,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        strict_associations: bool = False,
    ) -> collections.abc.Generator[tuple[Timestamp, dict[str, typing.Any]], None, None]:
        """Yield the messages of a topic the event annotates, within the event's time span.

        Each call reads one topic. Which topic, and which of its message paths, depends on the event's associations.
        The most specific kind the event has decides, in this order:

        1. Message paths. The read includes only those message paths, and ignores ``message_paths_include`` and
           ``message_paths_exclude``. When they belong to more than one topic, ``topic_name`` must name one of those
           topics, and only its message paths are read.
        2. Topics. When the event is on more than one topic, ``topic_name`` must name one of them.
        3. A file. ``topic_name`` must name a topic in the file. An event on more than one file cannot be read.

        When the associations identify a single topic, ``topic_name`` is ignored. Nothing is fetched until the
        iteration starts.

        The read includes messages at ``start_time`` and excludes those at ``end_time``, so an event whose start equals
        its end yields no messages.

        Args:
            message_paths_include: Dot-delimited message paths to include, such as ``"velocity.x"``. A partial path
                such as ``"velocity"`` includes every path under it. ``None`` includes every message path.
            message_paths_exclude: Message paths to leave out, in the same form. ``None`` leaves out none.
            topic_name: Name of the topic to read, when the event's associations span more than one topic or the
                event is on a file.
            topic_data_service: Ignored. The data is read with a service that uses this event's ``roboto_client``.
            cache_dir: Directory to download the topic's data to. ``None`` uses
                :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.
            strict_associations: Has no effect. The event's message paths, topics, or file choose the topic as
                described above, whatever is passed.

        Yields:
            ``(timestamp, message)`` tuples, where ``message`` is a dictionary that follows the topic's schema.

        Raises:
            RobotoInvalidRequestException: The event is on no message path, topic, or file; it is on more than one
                file and on no topic or message path; or ``topic_name`` is needed but missing, or names other than
                exactly one of the event's topics. It surfaces on the first iteration.
            RobotoNotFoundException: The event is on a file that has no topic named ``topic_name``. It surfaces on the
                first iteration.

        Examples:
            For a topic whose messages look like ``{"velocity": {"x": ..., "y": ..., "z": ...}}``, these two calls
            yield the same data:

            >>> event.get_data(message_paths_include=["velocity.x", "velocity.y"])
            >>> event.get_data(message_paths_include=["velocity"], message_paths_exclude=["velocity.z"])

            Read many events' data in parallel with a thread pool:

            >>> from concurrent.futures import ThreadPoolExecutor
            >>> from itertools import chain
            >>> with ThreadPoolExecutor(max_workers=16) as ex:  # tune for your workload
            ...     results = list(ex.map(lambda e: list(e.get_data()), events))
            >>> merged = list(chain.from_iterable(results))
        """
        args = self.__get_data_args(
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            topic_name=topic_name,
            topic_data_service=topic_data_service,
            cache_dir=cache_dir,
            strict_associations=strict_associations,
        )
        topic = args.topic
        yield from topic.get_data(
            message_paths_include=args.message_paths_include,
            message_paths_exclude=args.message_paths_exclude,
            start_time=args.start_time,
            end_time=args.end_time,
            cache_dir=args.cache_dir,
        )

    def get_data_as_df(
        self,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        strict_associations: bool = False,
    ) -> pandas.DataFrame:
        """Fetch the data ``get_data`` would yield, as a ``pandas.DataFrame``.

        The DataFrame is indexed by log time. The topic and message paths read are chosen from the event's
        associations as ``get_data`` describes. Requires the ``roboto[analytics]`` extra.

        The read includes messages at ``start_time`` and excludes those at ``end_time``, so an event whose start equals
        its end returns no rows.

        Args:
            message_paths_include: Dot-delimited message paths to include, such as ``"velocity.x"``. A partial path
                such as ``"velocity"`` includes every path under it. ``None`` includes every message path. Ignored
                when the event is on message paths.
            message_paths_exclude: Message paths to leave out, in the same form. ``None`` leaves out none. Ignored
                when the event is on message paths.
            topic_name: Name of the topic to read, when the event's associations span more than one topic or the
                event is on a file.
            topic_data_service: Ignored. The data is read with a service that uses this event's ``roboto_client``.
            cache_dir: Directory to download the topic's data to. ``None`` uses
                :py:attr:`~roboto.domain.topics.TopicDataService.DEFAULT_CACHE_DIR`.
            strict_associations: Has no effect. The event's message paths, topics, or file choose the topic as
                described above, whatever is passed.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
            RobotoInvalidRequestException: The event's associations and ``topic_name`` do not identify one topic, as
                for ``get_data``.
            RobotoNotFoundException: The event is on a file that has no topic named ``topic_name``.

        Examples:
            Get event data as a DataFrame:

            >>> event = Event.from_id("ev_abc123")
            >>> df = event.get_data_as_df()
            >>> print(f"Data shape: {df.shape}")
            >>> print(df.head())

            Read only some message paths:

            >>> df = event.get_data_as_df(message_paths_include=["velocity.x", "velocity.y"])
            >>> print(df.columns.tolist())

            Print the time spanned by the data and the number of rows:

            >>> df = event.get_data_as_df()
            >>> print(f"Data span: {df.index.max() - df.index.min()} ns")
            >>> print(f"Data points: {len(df)}")

            Read many events' data in parallel with a thread pool, then combine it:

            >>> import pandas as pd
            >>> from concurrent.futures import ThreadPoolExecutor
            >>> with ThreadPoolExecutor(max_workers=16) as ex:  # tune for your workload
            ...     dfs = list(ex.map(lambda e: e.get_data_as_df(), events))
            >>> combined = pd.concat(dfs).sort_index()
        """
        result = self.__get_data_args(
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            topic_name=topic_name,
            topic_data_service=topic_data_service,
            cache_dir=cache_dir,
            strict_associations=strict_associations,
        )
        topic = result.topic
        return topic.get_data_as_df(
            message_paths_include=result.message_paths_include,
            message_paths_exclude=result.message_paths_exclude,
            start_time=result.start_time,
            end_time=result.end_time,
            cache_dir=result.cache_dir,
        )

    def message_path_ids(self) -> list[str]:
        """Return the IDs of the message paths the event is associated with, each once.

        Reads the event's record and makes no request.

        Examples:
            Get message path IDs:

            >>> event = Event.from_id("ev_abc123")
            >>> msgpath_ids = event.message_path_ids()
            >>> print(f"Associated with {len(msgpath_ids)} message paths")
        """
        return list(
            {
                association.message_path_id
                for association in self.__record.associations
                if association.is_msgpath and association.message_path_id is not None
            }
        )

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "Event":
        """Set metadata keys on the event, adding new keys and overwriting existing ones.

        Keys the dict does not name keep their values. A dotted key such as ``"weather.condition"`` sets
        ``condition`` inside the nested ``weather`` object. It calls ``update``, whose failures also apply.

        Args:
            metadata: Key-value metadata to set on the event.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            Add metadata to an event:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.put_metadata({"severity": "high", "component": "engine", "alert_id": "alert_001"})
            >>> print(updated_event.metadata["severity"])
            high
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "Event":
        """Add tags to the event, keeping its existing tags.

        A tag the event already has is not added again. It calls ``update``, whose failures also apply.

        Args:
            tags: Tags to add to the event.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            Add tags to an event:

            >>> event = Event.from_id("ev_abc123")
            >>> event = event.put_tags(["anomaly", "critical"])
            >>> event = event.put_tags(["engine"])
            >>> {"anomaly", "critical", "engine"} <= set(event.tags)
            True
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> "Event":
        """Replace this instance's record with the event's current record from Roboto.

        Use it to see changes that other users or processes made after this instance was loaded.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The event no longer exists.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> refreshed_event = event.refresh()
            >>> print(f"Current description: {refreshed_event.description}")
        """
        self.__record = self.__roboto_client.get(f"v1/events/id/{self.event_id}").to_record(EventRecord)
        return self

    def remove_metadata(
        self,
        metadata: StrSequence,
    ) -> "Event":
        """Remove metadata keys from the event. Keys the event does not have are ignored.

        A dotted key such as ``"temp_data.max"`` removes ``max`` from inside the nested ``temp_data`` object. It
        calls ``update``, whose failures also apply.

        Args:
            metadata: Metadata keys to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.remove_metadata(["severity", "temp_data.max"])
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(
        self,
        tags: StrSequence,
    ) -> "Event":
        """Remove tags from the event. Tags the event does not have are ignored.

        It calls ``update``, whose failures also apply.

        Args:
            tags: Tags to remove from the event.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.remove_tags(["temporary", "draft"])
            >>> "draft" in updated_event.tags
            False
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    @experimental
    def set_custom_field(self, name: str, value: typing.Any) -> "Event":
        """Set one custom-field value on the event.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for events in the event's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            value: Value to set, which must match the field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for events, or ``value`` does not
                match its type.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> event = event.set_custom_field("severity_score", 7)
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    @experimental
    def clear_custom_field(self, name: str) -> "Event":
        """Clear one custom-field value on the event, so the field reads back as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a ready custom field defined for events in the event's organization.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for events.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> event.clear_custom_field("severity_score").custom_fields["severity_score"] is None
            True
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    @experimental
    def set_custom_fields(self, fields: dict[str, typing.Any]) -> "Event":
        """Set several custom-field values on the event. Fields not named keep their values.

        It calls ``update``, whose failures also apply.

        Args:
            fields: New values keyed by field name. Each name must be a custom field defined for events in the
                event's organization, with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`,
                and each value must match that field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for events, or a value does not match
                its field's type.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> event = event.set_custom_fields({"severity_score": 7, "reviewer": "pilot"})
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=fields))

    @experimental
    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> "Event":
        """Clear several custom-field values on the event, so each field reads back as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            names: Names of ready custom fields defined for events in the event's organization.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for events.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> event = event.clear_custom_fields(["severity_score", "reviewer"])
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))

    def set_color(self, color: typing.Optional[str]) -> "Event":
        """Set the event's display color.

        It calls ``update``, whose failures also apply.

        Args:
            color: Display color, as any CSS color value, such as ``"red"``, ``"#ff0000"`` or ``"rgb(255 0 0)"``.
                ``None`` clears it, so Roboto chooses one.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            Set event color to red:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_color("red")
            >>> print(updated_event.color)
            red

            Clear event color:

            >>> updated_event = event.set_color(None)
            >>> print(updated_event.color)
            None
        """
        return self.update(display_options_changeset=EventDisplayOptionsChangeset(color=color))

    def set_description(self, description: typing.Optional[str]) -> "Event":
        """Set the event's description.

        It calls ``update``, whose failures also apply.

        Args:
            description: Human-readable description of the event. ``None`` clears it.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            Set event description:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_description("Updated event description")
            >>> print(updated_event.description)
            Updated event description

            Clear event description:

            >>> updated_event = event.set_description(None)
            >>> print(updated_event.description)
            None
        """
        return self.update(description=description)

    def set_name(self, name: str) -> "Event":
        """Set the event's name.

        It calls ``update``, whose failures also apply.

        Args:
            name: Human-readable name of the event. Roboto does not require names to be unique.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            Update event name:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_name("Critical System Alert")
            >>> print(updated_event.name)
            Critical System Alert
        """
        return self.update(name=name)

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the event's record as a JSON-compatible dictionary.

        Returns:
            :py:class:`~roboto.domain.events.EventRecord` of the event, as a JSON-compatible dictionary.

        Examples:
            >>> event = Event.from_id("ev_abc123")
            >>> event_dict = event.to_dict()
            >>> print(event_dict["name"])
            >>> print(event_dict["start_time"])
        """
        return self.__record.model_dump(mode="json")

    def topic_ids(self, strict_associations: bool = False) -> list[str]:
        """Return the IDs of the topics the event is associated with, each once.

        Reads the event's record and makes no request.

        Args:
            strict_associations: Whether to return only topics the event is associated with directly. When ``False``,
                also returns the topics that contain the event's message paths.

        Examples:
            Get all associated topic IDs:

            >>> event = Event.from_id("ev_abc123")
            >>> topic_ids = event.topic_ids()
            >>> print(f"Associated with {len(topic_ids)} topics")

            Get only directly associated topics:

            >>> strict_topic_ids = event.topic_ids(strict_associations=True)
            >>> for topic_id in strict_topic_ids:
            ...     print(f"Directly associated topic: {topic_id}")
        """
        return list(
            {
                association.topic_id
                for association in self.__record.associations
                if (strict_associations is False or association.is_topic) and association.topic_id is not None
            }
        )

    def update(
        self,
        name: typing.Union[str, NotSetType] = NotSet,
        start_time: typing.Union[Time, NotSetType] = NotSet,
        end_time: typing.Union[Time, NotSetType] = NotSet,
        description: typing.Union[str, None, NotSetType] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        display_options_changeset: typing.Union[EventDisplayOptionsChangeset, NotSetType] = NotSet,
        custom_fields_changeset: typing.Optional[CustomFieldChangeset] = None,
    ) -> "Event":
        """Update the event's properties. Arguments left unset leave their property unchanged.

        Args:
            name: Human-readable name of the event. Roboto does not require names to be unique.
            start_time: Start of the event, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: End of the event, in the same form.
            description: Human-readable description of the event. ``None`` clears it.
            metadata_changeset: Changes to the event's tags and metadata.
            display_options_changeset: Changes to the event's display options.
            custom_fields_changeset: Changes to the event's custom-field values. Fields the changeset does not name
                keep their values. ``None`` changes none.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: The update would leave the event starting after it ends; or the
                custom-field changeset names a field that is not a ready custom field for events, or sets a value
                that does not match its field's type.
            ValueError: ``start_time`` or ``end_time`` is negative, or is a string that is not a time.
            RobotoUnauthorizedException: The caller may not change any dataset or file the event is attached to, or,
                for an event attached to none, does not belong to its organization.

        Examples:
            Rename the event and change its description:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.update(
            ...     name="Critical System Alert", description="Updated description with more details"
            ... )

            Change the event's time span:

            >>> updated_event = event.update(start_time=1722870127699468923, end_time=1722870127799468923)

            Set a metadata key, add tags, and change the display color:

            >>> from roboto.updates import MetadataChangeset
            >>> from roboto.domain.events import EventDisplayOptionsChangeset
            >>> updated_event = event.update(
            ...     metadata_changeset=MetadataChangeset(
            ...         put_fields={"severity": "high"}, put_tags=["critical", "urgent"]
            ...     ),
            ...     display_options_changeset=EventDisplayOptionsChangeset(color="red"),
            ... )
        """

        # Checks with isinstance rather than is_set(), because is_set() does not narrow the Time union for mypy.
        def maybe_get_epoch_nanos(
            time: typing.Union[Time, NotSetType],
        ) -> typing.Union[int, NotSetType]:
            if isinstance(time, NotSetType):
                return NotSet
            else:
                return to_epoch_nanoseconds(time)

        request = remove_not_set(
            UpdateEventRequest(
                description=description,
                metadata_changeset=metadata_changeset,
                name=name,
                start_time=maybe_get_epoch_nanos(start_time),
                end_time=maybe_get_epoch_nanos(end_time),
                display_options_changeset=(
                    remove_not_set(display_options_changeset) if is_set(display_options_changeset) else NotSet
                ),
                custom_fields_changeset=custom_fields_changeset,
            )
        )

        self.__record = self.__roboto_client.put(f"/v1/events/id/{self.event_id}", data=request).to_record(EventRecord)

        return self

    def __get_data_args(
        self,
        message_paths_include: typing.Optional[collections.abc.Iterable[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Iterable[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        strict_associations: bool = False,
    ) -> GetDataArgs:
        """Choose the topic and read arguments for ``get_data`` and ``get_data_as_df`` from the event's associations.

        Uses the event's message paths if it has any, otherwise its topics, otherwise its file.
        """
        message_path_ids = self.message_path_ids()
        if len(message_path_ids) > 0:
            message_paths = [
                MessagePath.from_id(
                    message_path_id=message_path_id,
                    roboto_client=self.__roboto_client,
                    topic_data_service=topic_data_service,
                )
                for message_path_id in message_path_ids
            ]
            # Read all the message paths in one read of their topic, so data they share is fetched once.
            topic = self.__select_topic([message_path.topic_id for message_path in message_paths], topic_name)
            return GetDataArgs(
                topic=topic,
                message_paths_include=[
                    message_path.record.source_path
                    for message_path in message_paths
                    if message_path.topic_id == topic.topic_id
                ],
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )

        topic_ids = self.topic_ids(strict_associations=strict_associations)
        if len(topic_ids) > 0:
            topic = self.__select_topic(topic_ids, topic_name)
            return GetDataArgs(
                topic=topic,
                message_paths_include=message_paths_include,
                message_paths_exclude=message_paths_exclude,
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )

        file_ids = list(self.file_ids(strict_associations=strict_associations))
        if len(file_ids) != 0:
            if len(file_ids) > 1:
                raise RobotoInvalidRequestException(
                    "Unable to load event data for events associated with more than one file"
                )

            if topic_name is None:
                raise RobotoInvalidRequestException(
                    "Must provide 'topic_name' when attempting to load data for an event associated with a file"
                )

            file = File.from_id(file_id=file_ids[0], roboto_client=self.__roboto_client)
            topic = file.get_topic(topic_name)
            return GetDataArgs(
                topic=topic,
                message_paths_include=message_paths_include,
                message_paths_exclude=message_paths_exclude,
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )

        raise RobotoInvalidRequestException(
            "Can only load event data for events associated with topic data: "
            "a single file, one or more topics extracted from files, or specific message paths within those topics."
        )

    def __select_topic(self, topic_ids: collections.abc.Iterable[str], topic_name: typing.Optional[str]) -> Topic:
        """Return the topic to load data from: the only one in ``topic_ids``, or else the one named ``topic_name``."""
        unique_topic_ids = set(topic_ids)
        if len(unique_topic_ids) == 1:
            return Topic.from_id(topic_id=unique_topic_ids.pop(), roboto_client=self.__roboto_client)

        if topic_name is None:
            raise RobotoInvalidRequestException(
                "This event's data is in more than one topic. Pass 'topic_name' to choose the topic to load."
            )

        topics = [Topic.from_id(topic_id=topic_id, roboto_client=self.__roboto_client) for topic_id in unique_topic_ids]
        named_topics = [topic for topic in topics if topic.name == topic_name]
        if len(named_topics) != 1:
            topic_names = ", ".join(sorted(f"'{topic.name}'" for topic in topics))
            raise RobotoInvalidRequestException(
                f"This event's data is in the topics {topic_names}. "
                f"'topic_name' must name exactly one of them, but '{topic_name}' matches {len(named_topics)}."
            )

        return named_topics[0]
