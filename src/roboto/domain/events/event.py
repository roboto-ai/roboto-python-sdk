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
    MetadataChangeset,
    StrSequence,
)
from ..files import File
from ..topics import (
    MessagePath,
    Topic,
    TopicDataService,
)
from .operations import (
    CreateEventRequest,
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
    """
    Internal interface used to collect arguments passed to ``get_data`` and ``get_data_as_df``.
    """

    topic: Topic
    message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None
    message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None
    start_time: typing.Optional[Time] = None
    end_time: typing.Optional[Time] = None
    cache_dir: typing.Union[str, pathlib.Path, None] = None


class Event:
    """Represents an event within the Roboto platform.

    An event is a time-anchored annotation that relates Roboto entities (datasets, files,
    topics, and message paths) to specific time periods. Events enable temporal analysis,
    data correlation, and annotation of activities across different data sources.

    Events serve as temporal markers that can:

    - Annotate specific time periods in your data
    - Associate multiple entities (datasets, files, topics, message paths) with time ranges
    - Enable time-based data retrieval and analysis
    - Support metadata and tagging for organization and search
    - Provide visual markers in timeline views and analysis tools

    Events can represent instantaneous moments (point in time) or time ranges. They are
    particularly useful for marking significant occurrences like sensor anomalies, system
    events, behavioral patterns, or any other time-based phenomena in your data.

    Events cannot be instantiated directly through the constructor. Use the class methods
    :py:meth:`Event.create` to create new events or :py:meth:`Event.from_id` to load
    existing events.
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
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Event":
        """Create a new event associated with at least one dataset, file, topic, or message path.

        Creates a time-anchored event that can be associated with various Roboto entities.
        For instantaneous events (a point in time), only ``start_time`` is required. Otherwise,
        both ``start_time`` and ``end_time`` should be provided. These fields accept nanoseconds
        since the UNIX epoch, or any other compatible representations supported by
        :py:func:`~roboto.time.to_epoch_nanoseconds`.

        Events must be associated with at least one entity. While ``associations``,
        ``file_ids``, ``topic_ids``, ``dataset_ids`` and ``message_path_ids`` are all optional,
        at least one of them must contain a valid association for the event.

        Args:
            name: Human-readable name for the event. Required.
            start_time: Start timestamp of the event as nanoseconds since UNIX epoch,
                or any value convertible by :py:func:`~roboto.time.to_epoch_nanoseconds`.
            end_time: End timestamp of the event. If not provided, defaults to start_time
                for instantaneous events.
            associations: Collection of :py:class:`~roboto.association.Association` objects
                linking the event to specific entities.
            dataset_ids: Dataset IDs to associate the event with.
            file_ids: File IDs to associate the event with.
            topic_ids: Topic IDs to associate the event with.
            message_path_ids: Message path IDs to associate the event with.
            description: Optional human-readable description of the event.
            metadata: Key-value metadata for discovery and search.
            tags: Tags for categorizing and searching the event.
            display_options: Visual display options such as color.
            caller_org_id: Organization ID of the SDK caller. If not provided,
                uses the caller's organization.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Event instance with the provided attributes and associations.

        Raises:
            RobotoInvalidRequestException: Invalid parameters (e.g., start_time > end_time),
                or associations point to non-existent resources.
            RobotoUnauthorizedException: Caller lacks permission to access associated entities.

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
            ...     metadata={"severity": "high", "sensor_id": "temp_01"}
            ... )

            Create an instantaneous event on a file:

            >>> event = Event.create(
            ...     name="System Boot",
            ...     start_time="1722870127.699468923",  # String format also supported
            ...     file_ids=["fl_xyz789"],
            ...     tags=["system", "boot"]
            ... )

            Create an event with display options:

            >>> from roboto.domain.events import EventDisplayOptions
            >>> event = Event.create(
            ...     name="Critical Alert",
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923,
            ...     dataset_ids=["ds_abc123"],
            ...     display_options=EventDisplayOptions(color="red"),
            ...     metadata={"alert_type": "critical", "component": "engine"}
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
        )
        record = roboto_client.post(
            "v1/events/create", caller_org_id=caller_org_id, data=request
        ).to_record(EventRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def get_by_dataset(
        cls,
        dataset_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        strict_associations: bool = False,
    ) -> collections.abc.Generator["Event", None, None]:
        """Retrieve all events associated with a specific dataset.

        Returns events that are associated with the given dataset. By default, this includes
        events associated with the dataset itself, as well as events associated with any
        files or topics within that dataset. Use ``strict_associations=True`` to only return
        events with direct dataset associations.

        Args:
            dataset_id: ID of the dataset to query events for.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            strict_associations: If True, only return events with direct dataset associations.
                If False (default), also return events associated with files or topics
                within the dataset.

        Yields:
            Event instances associated with the specified dataset.

        Examples:
            Get all events for a dataset (including file and topic events):

            >>> events = list(Event.get_by_dataset("ds_abc123"))
            >>> for event in events:
            ...     print(f"Event: {event.name} at {event.start_time}")

            Get only events directly associated with the dataset:

            >>> strict_events = list(Event.get_by_dataset("ds_abc123", strict_associations=True))
            >>> print(f"Found {len(strict_events)} dataset-level events")

            Process events in batches:

            >>> for event in Event.get_by_dataset("ds_abc123"):
            ...     if "anomaly" in event.tags:
            ...         print(f"Anomaly event: {event.name}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        # This will return only events that explicitly have an association with this dataset
        if strict_associations is True:
            for event in Event.get_by_associations(
                [Association.dataset(dataset_id)], roboto_client
            ):
                yield event
            return

        # This will return all events that have an association with this dataset or any of its files or topics
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
        """Retrieve all events with a direct association to a specific file.

        Args:
            file_id: ID of the file to query events for.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Yields:
            Event instances directly associated with the specified file.

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
        """Retrieve all events with a direct association to a specific message path.

        Args:
            message_path_id: ID of the message path to query events for.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Yields:
            Event instances directly associated with the specified message path.

        Examples:
            Get all events for a specific message path:

            >>> events = list(Event.get_by_message_path("mp_abc123"))
            >>> for event in events:
            ...     print(f"Message path event: {event.name}")

            Find events within a time range for a message path:

            >>> events = Event.get_by_message_path("mp_abc123")
            >>> filtered_events = [
            ...     event for event in events
            ...     if event.start_time >= 1722870127699468923
            ... ]
        """
        return Event.get_by_associations(
            [Association.msgpath(message_path_id)], roboto_client
        )

    @classmethod
    def get_by_topic(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """Retrieve all events with a direct association to a specific topic.

        Args:
            topic_id: ID of the topic to query events for.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Yields:
            Event instances directly associated with the specified topic.

        Examples:
            Get all events for a specific topic:

            >>> events = list(Event.get_by_topic("tp_abc123"))
            >>> for event in events:
            ...     print(f"Topic event: {event.name}")

            Analyze event patterns for a topic:

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
        """Retrieve all events associated with the provided associations.

        Returns events that match any of the provided associations. Events that you don't
        have access to will be filtered out of the response rather than raising an exception.

        Args:
            associations: Collection of :py:class:`~roboto.association.Association` objects
                to query events for.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Yields:
            Event instances associated with any of the specified associations.

        Examples:
            Query events for multiple associations:

            >>> from roboto import Association
            >>> associations = [
            ...     Association.topic("tp_abc123"),
            ...     Association.file("fl_xyz789")
            ... ]
            >>> events = list(Event.get_by_associations(associations))
            >>> for event in events:
            ...     print(f"Event: {event.name}")

            Query events for a specific dataset and file combination:

            >>> associations = [
            ...     Association.dataset("ds_abc123"),
            ...     Association.file("fl_xyz789")
            ... ]
            >>> events = list(Event.get_by_associations(associations))
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            request = QueryEventsForAssociationsRequest(
                associations=list(associations), page_token=next_token
            )

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
    def from_id(
        cls, event_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ) -> "Event":
        """Load an existing event by its ID.

        Args:
            event_id: Unique identifier of the event to retrieve.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Event instance for the specified ID.

        Raises:
            RobotoNotFoundException: Event with the specified ID does not exist.
            RobotoUnauthorizedException: Caller lacks permission to access the event.

        Examples:
            Load an event by ID:

            >>> event = Event.from_id("ev_abc123")
            >>> print(f"Event: {event.name}")
            >>> print(f"Created: {event.created}")

            Load and update an event:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_description("Updated description")
            >>> print(f"New description: {updated_event.description}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/events/id/{event_id}").to_record(EventRecord)
        return cls(record, roboto_client)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented

        return self.__record == other.__record

    def __init__(
        self, record: EventRecord, roboto_client: typing.Optional[RobotoClient] = None
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def color(self) -> typing.Optional[str]:
        """Display color for the event, if set."""
        return self.display_options.color if self.display_options else None

    @property
    def created(self) -> datetime.datetime:
        """Date and time when this event was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """User who created this event."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Optional human-readable description of the event."""
        return self.__record.description

    @property
    def display_options(self) -> typing.Optional[EventDisplayOptions]:
        """Display options for the event, such as color."""
        return self.__record.display_options

    @property
    def end_time(self) -> int:
        """End time of the event in nanoseconds since UNIX epoch."""
        return self.__record.end_time

    @property
    def event_id(self) -> str:
        """Unique identifier for this event."""
        return self.__record.event_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata associated with this event."""
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        """Date and time when this event was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """User who last modified this event."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Human-readable name of the event."""
        return self.__record.name

    @property
    def record(self) -> EventRecord:
        """Underlying event record data."""
        return self.__record

    @property
    def start_time(self) -> int:
        """Start time of the event in nanoseconds since UNIX epoch."""
        return self.__record.start_time

    @property
    def tags(self) -> list[str]:
        """Tags associated with this event for categorization and search."""
        return self.__record.tags

    def dataset_ids(self, strict_associations: bool = False) -> list[str]:
        """Get dataset IDs associated with this event.

        Args:
            strict_associations: If True, only return datasets with direct associations.
                If False (default), also return datasets inferred from file and topic associations.

        Returns:
            List of unique dataset IDs associated with this event.

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
                if (strict_associations is False or association.is_dataset)
                and association.dataset_id is not None
            }
        )

    def delete(self) -> None:
        """Delete this event permanently.

        This operation cannot be undone. The event and all its associations will be
        permanently removed from the platform.

        Raises:
            RobotoUnauthorizedException: Caller lacks permission to delete this event.
            RobotoNotFoundException: Event has already been deleted or does not exist.

        Examples:
            Delete an event:

            >>> event = Event.from_id("ev_abc123")
            >>> event.delete()
            >>> # Event is now permanently deleted

            Conditional deletion:

            >>> event = Event.from_id("ev_abc123")
            >>> if "temporary" in event.tags:
            ...     event.delete()
            ...     print("Temporary event deleted")
        """
        self.__roboto_client.delete(f"v1/events/id/{self.event_id}")

    def file_ids(self, strict_associations: bool = False) -> list[str]:
        """Get file IDs associated with this event.

        Args:
            strict_associations: If True, only return files with direct associations.
                If False (default), also return files inferred from topic and message path associations.

        Returns:
            List of unique file IDs associated with this event.

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
                if (strict_associations is False or association.is_file)
                and association.file_id is not None
            }
        )

    def get_data(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        strict_associations: bool = False,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """
        Iteratively yield records of the underlying topic data this event annotates.

        An event can be associated with data at multiple resolutions:
            - as an event on its containing dataset, file, and/or topic,
            - but also directly with the message path ("signal data")
        A single event can also span signals that share a timeline,
        so it may annotate multiple topics in a file, or even multiple files in a dataset.

        For now, getting the underlying signal data associated with an event only works
        for events that can be sourced to a single topic (extracted from one file, uploaded to one dataset).
        This means that the event must have been made on either a single file, a single topic,
        or one or many message paths within that topic.

        If the event was made on a file, `topic_name` must be provided,
        and either or both of `message_paths_include` or `message_paths_exclude` may be provided,
        but are optional.

        If the event was made on a topic, either or both of `message_paths_include` or `message_paths_exclude`
        may be provided, but are optional.
        `topic_name`, if provided in this instance, is ignored.

        If the event was made on one or many message paths,
        each of those message paths must be found in the same topic.
        `topic_name`, `message_paths_include`, and `message_paths_exclude`, if provided in this instance,
        are ignored.

        If the event is associated with data at multiple resolutions (e.g., two message paths, one topic, one file),
        this method will consider the lowest resolution associations first (message path), then topic, then file.

        If ``message_paths_include`` or ``message_paths_exclude`` are defined,
        they should be dot notation paths that match attributes of individual data records.
        If a partial path is provided, it is treated as a wildcard, matching all subpaths.

        For example, given topic data with the following interface:

        ::

            {
                "velocity": {
                    "x": <uint32>,
                    "y": <uint32>,
                    "z": <uint32>
                }
            }

        Calling ``get_data`` on an Event associated with that topic like:

            >>> event.get_data(message_paths_include=["velocity.x", "velocity.y"])

        is expected to give the same output as:

            >>> event.get_data(message_paths_include=["velocity"], message_paths_exclude=["velocity.z"])
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
        yield from topic.get_data(
            message_paths_include=result.message_paths_include,
            message_paths_exclude=result.message_paths_exclude,
            start_time=result.start_time,
            end_time=result.end_time,
            cache_dir=result.cache_dir,
        )

    def get_data_as_df(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        strict_associations: bool = False,
    ) -> pandas.DataFrame:
        """Return the underlying topic data this event annotates as a pandas DataFrame.

        Collects all data from :py:meth:`get_data` and returns it as a pandas DataFrame
        with the log time as the index. Requires installing this package using the
        ``roboto[analytics]`` extra.

        Args:
            message_paths_include: Dot notation paths to include in the data.
            message_paths_exclude: Dot notation paths to exclude from the data.
            topic_name: Required when event is associated with a file.
            topic_data_service: Service for accessing topic data.
            cache_dir: Directory for caching downloaded data.

        Returns:
            DataFrame containing the event's underlying topic data, indexed by log time.

        Raises:
            ImportError: If pandas is not installed (install with ``roboto[analytics]``).
            RobotoInvalidRequestException: Invalid parameters or event associations.

        Examples:
            Get event data as a DataFrame:

            >>> event = Event.from_id("ev_abc123")
            >>> df = event.get_data_as_df()
            >>> print(f"Data shape: {df.shape}")
            >>> print(df.head())

            Get specific message paths as DataFrame:

            >>> df = event.get_data_as_df(
            ...     message_paths_include=["velocity.x", "velocity.y"]
            ... )
            >>> print(df.columns.tolist())

            Analyze event data:

            >>> df = event.get_data_as_df()
            >>> print(f"Event duration: {df.index.max() - df.index.min()} ns")
            >>> print(f"Data points: {len(df)}")
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
        """Get message path IDs directly associated with this event.

        Returns:
            List of unique message path IDs directly associated with this event.

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
        """Add or update metadata fields for this event.

        Args:
            metadata: Dictionary of key-value pairs to add or update.

        Returns:
            Updated Event instance.

        Examples:
            Add metadata to an event:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.put_metadata({
            ...     "severity": "high",
            ...     "component": "engine",
            ...     "alert_id": "alert_001"
            ... })
            >>> print(updated_event.metadata["severity"])
            'high'
        """
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "Event":
        """Replace all tags for this event.

        Args:
            tags: List of tags to set for this event.

        Returns:
            Updated Event instance.

        Examples:
            Set tags for an event:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.put_tags(["anomaly", "critical", "engine"])
            >>> print(updated_event.tags)
            ['anomaly', 'critical', 'engine']
        """
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> "Event":
        """Refresh this event's data from the server.

        Fetches the latest version of this event from the server, updating all
        properties to reflect any changes made by other processes.

        Returns:
            This Event instance with refreshed data.

        Examples:
            Refresh an event to get latest changes:

            >>> event = Event.from_id("ev_abc123")
            >>> # Event may have been updated by another process
            >>> refreshed_event = event.refresh()
            >>> print(f"Current description: {refreshed_event.description}")
        """
        self.__record = self.__roboto_client.get(
            f"v1/events/id/{self.event_id}"
        ).to_record(EventRecord)
        return self

    def remove_metadata(
        self,
        metadata: StrSequence,
    ) -> "Event":
        """Remove metadata fields from this event.

        Args:
            metadata: Sequence of metadata field names to remove. Supports dot notation
                for nested fields.

        Returns:
            Updated Event instance.

        Examples:
            Remove specific metadata fields:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.remove_metadata(["severity", "temp_data.max"])
            >>> # Fields 'severity' and nested 'temp_data.max' are now removed
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(
        self,
        tags: StrSequence,
    ) -> "Event":
        """Remove specific tags from this event.

        Args:
            tags: Sequence of tag names to remove from this event.

        Returns:
            Updated Event instance.

        Examples:
            Remove specific tags:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.remove_tags(["temporary", "draft"])
            >>> # Tags 'temporary' and 'draft' are now removed
        """
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    def set_color(self, color: typing.Optional[str]) -> "Event":
        """Set the display color for this event.

        Args:
            color: CSS-compatible color value (e.g., "red", "#ff0000", "rgb(255,0,0)").
                Use None to clear the color and use automatic coloring.

        Returns:
            Updated Event instance.

        Examples:
            Set event color to red:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_color("red")
            >>> print(updated_event.color)
            'red'

            Clear event color:

            >>> updated_event = event.set_color(None)
            >>> print(updated_event.color)
            None
        """
        return self.update(
            display_options_changeset=EventDisplayOptionsChangeset(color=color)
        )

    def set_description(self, description: typing.Optional[str]) -> "Event":
        """Set the description for this event.

        Args:
            description: New description for the event. Use None to clear the description.

        Returns:
            Updated Event instance.

        Examples:
            Set event description:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_description("Updated event description")
            >>> print(updated_event.description)
            'Updated event description'

            Clear event description:

            >>> updated_event = event.set_description(None)
            >>> print(updated_event.description)
            None
        """
        return self.update(description=description)

    def set_name(self, name: str) -> "Event":
        """Set the name for this event.

        Args:
            name: New name for the event.

        Returns:
            Updated Event instance.

        Examples:
            Update event name:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.set_name("Critical System Alert")
            >>> print(updated_event.name)
            'Critical System Alert'
        """
        return self.update(name=name)

    def to_dict(self) -> dict[str, typing.Any]:
        """Convert this event to a dictionary representation.

        Returns:
            Dictionary containing all event data in JSON-serializable format.

        Examples:
            Convert event to dictionary:

            >>> event = Event.from_id("ev_abc123")
            >>> event_dict = event.to_dict()
            >>> print(event_dict["name"])
            >>> print(event_dict["start_time"])
        """
        return self.__record.model_dump(mode="json")

    def topic_ids(self, strict_associations: bool = False) -> list[str]:
        """Get topic IDs associated with this event.

        Args:
            strict_associations: If True, only return topics with direct associations.
                If False (default), also return topics inferred from message path associations.

        Returns:
            List of unique topic IDs associated with this event.

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
                if (strict_associations is False or association.is_topic)
                and association.topic_id is not None
            }
        )

    def update(
        self,
        name: typing.Union[str, NotSetType] = NotSet,
        start_time: typing.Union[Time, NotSetType] = NotSet,
        end_time: typing.Union[Time, NotSetType] = NotSet,
        description: typing.Union[str, None, NotSetType] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        display_options_changeset: typing.Union[
            EventDisplayOptionsChangeset, NotSetType
        ] = NotSet,
    ) -> "Event":
        """Update this event's attributes.

        Updates various properties of the event including name, time range, description,
        metadata, and display options. Only specified parameters are updated; others
        remain unchanged.

        When provided, ``start_time`` and ``end_time`` should be integers representing nanoseconds
        since the UNIX epoch, or convertible to such integers by :py:func:`~roboto.time.to_epoch_nanoseconds`.

        Args:
            name: New human-readable name for the event.
            start_time: New start timestamp for the event.
            end_time: New end timestamp for the event.
            description: New description for the event. Set to None to clear existing description.
            metadata_changeset: Changes to apply to the event's metadata and tags.
            display_options_changeset: Changes to apply to the event's display options.

        Returns:
            This Event instance with attributes updated accordingly.

        Raises:
            ValueError: If start_time or end_time are negative.
            RobotoIllegalArgumentException: If start_time > end_time.
            RobotoUnauthorizedException: Caller lacks permission to edit this event.

        Examples:
            Update event name and description:

            >>> event = Event.from_id("ev_abc123")
            >>> updated_event = event.update(
            ...     name="Critical System Alert",
            ...     description="Updated description with more details"
            ... )

            Update event time range:

            >>> updated_event = event.update(
            ...     start_time=1722870127699468923,
            ...     end_time=1722870127799468923
            ... )

            Update metadata and display options:

            >>> from roboto.updates import MetadataChangeset
            >>> from roboto.domain.events import EventDisplayOptionsChangeset
            >>> updated_event = event.update(
            ...     metadata_changeset=MetadataChangeset(
            ...         put_fields={"severity": "high"},
            ...         put_tags=["critical", "urgent"]
            ...     ),
            ...     display_options_changeset=EventDisplayOptionsChangeset(color="red")
            ... )
        """

        # Normally would've used is_set(), but MyPy has issues with our TypeAlias 'Time'
        def maybe_get_epoch_nanos(
            time: typing.Union[Time, NotSetType]
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
                    remove_not_set(display_options_changeset)
                    if is_set(display_options_changeset)
                    else NotSet
                ),
            )
        )

        self.__record = self.__roboto_client.put(
            f"/v1/events/id/{self.event_id}", data=request
        ).to_record(EventRecord)

        return self

    def __get_data_args(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
        strict_associations: bool = False,
    ) -> GetDataArgs:
        """
        Deduplicate logic used to collect arguments passed to both ``get_data`` and ``get_data_as_df``.
        """
        # Event associated with message path(s)
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
            unique_topics = set(
                [message_path.topic_id for message_path in message_paths]
            )
            if len(unique_topics) > 1:
                raise RobotoInvalidRequestException(
                    "Unable to load event data for events associated with more than one topic"
                )

            # Request data using the message paths' containing topic,
            # which will better dedupe and make concurrent fetches for underlying data
            # across many message paths.
            topic_id = message_paths[0].topic_id
            topic = Topic.from_id(topic_id=topic_id, roboto_client=self.__roboto_client)
            return GetDataArgs(
                topic=topic,
                message_paths_include=[
                    message_path.path for message_path in message_paths
                ],
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )

        # Event associated with topic
        topic_ids = self.topic_ids(strict_associations=strict_associations)
        if len(topic_ids) > 0:
            unique_topics = set(topic_ids)
            if len(unique_topics) > 1:
                raise RobotoInvalidRequestException(
                    "Unable to load event data for events associated with more than one topic"
                )

            topic_id = unique_topics.pop()
            topic = Topic.from_id(topic_id=topic_id, roboto_client=self.__roboto_client)
            return GetDataArgs(
                topic=topic,
                message_paths_include=message_paths_include,
                message_paths_exclude=message_paths_exclude,
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )

        # Event associated with a file
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
            "Can only load event data for events ultimately sourced from a single topic. "
            "That means it must be associated with either a single file, "
            "a single topic extracted from a file, or one or many specific message paths within a single topic."
        )
