# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import pathlib
import typing

from ...association import Association
from ...compat import import_optional_dependency
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


class Event:
    """
    An event is a "time anchor" which allows you to relate first class Roboto entities
    (datasets, files, topics and message paths), as well as a timespan in which they occurred.
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
        """
        Creates a new event associated with at least one dataset, file, topic, or message path.

        For instantaneous events (a point in time), only ``start_time`` is required. Otherwise,
        both ``start_time`` and ``end_time`` should be provided. These fields accept nanoseconds
        since the UNIX epoch, or any other compatible representations supported by
        :py:func:`~roboto.time.to_epoch_nanoseconds`.

        Events can be associated to one or more message paths, topics, etc. While ``associations``,
        ``file_ids``, ``topic_ids``, ``dataset_ids`` and ``message_path_ids`` are all optional, at
        least one of them has to contain a valid association for the event.

        Args:
            name: Event name. Required.
            start_time: Start timestamp of the event.
            end_time: End timestamp of the event.
            description: Human-readable description of the event.
            associations: One or more associations for the event.
            dataset_ids: Datasets to associate the event with.
            file_ids: Files to associate the event with.
            topic_ids: Topics to associate the event with.
            message_path_ids: Message paths to associate the event with.
            metadata: Key-value metadata for this event.
            tags: Tags used to categorize the event.
            display_options: Display options for the event.
            caller_org_id: Organization ID of the SDK caller.
            roboto_client: ``RobotoClient`` instance for making network requests.

        Returns:
            An ``Event`` instance with the provided attributes and associations.

        Raises:
            RobotoInvalidRequestException:
              Raised when request parameters violate natural constraints (e.g. ``start_time``
              should precede ``end_time``), or when associations point to resources that
              don't exist, or aren't owned by the user's org.
            RobotoUnauthorizedException:
              If the SDK user is not a member of the org which owns the associated topics,
              files, etc.
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
        """Returns all events with a direct association to the provided file."""
        return Event.get_by_associations([Association.file(file_id)], roboto_client)

    @classmethod
    def get_by_message_path(
        cls,
        message_path_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """Returns all events with a direct association to the provided message path."""
        return Event.get_by_associations(
            [Association.msgpath(message_path_id)], roboto_client
        )

    @classmethod
    def get_by_topic(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """Returns all events with a direct association to the provided topic."""
        return Event.get_by_associations([Association.topic(topic_id)], roboto_client)

    @classmethod
    def get_by_associations(
        cls,
        associations: collections.abc.Collection[Association],
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """
        Returns all events associated with the provided association. Any events which you don't have access to will be
        filtered out of the response rather than throwing an exception.
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
    ):
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
        return self.display_options.color if self.display_options else None

    @property
    def created(self) -> datetime.datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        return self.__record.description

    @property
    def display_options(self) -> typing.Optional[EventDisplayOptions]:
        return self.__record.display_options

    @property
    def end_time(self) -> int:
        """Epoch nanoseconds"""
        return self.__record.end_time

    @property
    def event_id(self) -> str:
        return self.__record.event_id

    @property
    def metadata(self) -> dict[str, typing.Any]:
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        return self.__record.modified_by

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def record(self) -> EventRecord:
        return self.__record

    @property
    def start_time(self) -> int:
        """Epoch nanoseconds"""
        return self.__record.start_time

    @property
    def tags(self) -> list[str]:
        return self.__record.tags

    def dataset_ids(self, strict_associations: bool = False) -> list[str]:
        return list(
            {
                association.dataset_id
                for association in self.__record.associations
                if (strict_associations is False or association.is_dataset)
                and association.dataset_id is not None
            }
        )

    def delete(self) -> None:
        self.__roboto_client.delete(f"v1/events/id/{self.event_id}")

    def file_ids(self, strict_associations: bool = False) -> list[str]:
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
            yield from topic.get_data(
                message_paths_include=[
                    message_path.path for message_path in message_paths
                ],
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )
            return

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
            yield from topic.get_data(
                message_paths_include=message_paths_include,
                message_paths_exclude=message_paths_exclude,
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )
            return

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
            yield from topic.get_data(
                message_paths_include=message_paths_include,
                message_paths_exclude=message_paths_exclude,
                start_time=self.start_time,
                end_time=self.end_time,
                cache_dir=cache_dir,
            )
            return

        raise RobotoInvalidRequestException(
            "Can only load event data for events ultimately sourced from a single topic. "
            "That means it must be associated with either a single file, "
            "a single topic extracted from a file, or one or many specific message paths within a single topic."
        )

    def get_data_as_df(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> pandas.DataFrame:
        """
        Return the underlying topic data this event annotates as a pandas DataFrame.

        Requires installing this package using the ``roboto[analytics]`` extra.

        See :py:meth:`~roboto.domain.events.event.Event.get_data` for more information on the parameters.
        """
        pandas = import_optional_dependency("pandas", "analytics")

        df = pandas.json_normalize(
            data=list(
                self.get_data(
                    message_paths_include=message_paths_include,
                    message_paths_exclude=message_paths_exclude,
                    topic_name=topic_name,
                    topic_data_service=topic_data_service,
                    cache_dir=cache_dir,
                )
            )
        )

        if TopicDataService.LOG_TIME_ATTR_NAME in df.columns:
            return df.set_index(TopicDataService.LOG_TIME_ATTR_NAME)

        return df

    def message_path_ids(self) -> list[str]:
        return list(
            {
                association.message_path_id
                for association in self.__record.associations
                if association.is_msgpath and association.message_path_id is not None
            }
        )

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "Event":
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "Event":
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> "Event":
        self.__record = self.__roboto_client.get(
            f"v1/events/id/{self.event_id}"
        ).to_record(EventRecord)
        return self

    def remove_metadata(
        self,
        metadata: StrSequence,
    ) -> "Event":
        return self.update(metadata_changeset=MetadataChangeset(remove_fields=metadata))

    def remove_tags(
        self,
        tags: StrSequence,
    ) -> "Event":
        return self.update(metadata_changeset=MetadataChangeset(remove_tags=tags))

    def set_color(self, color: typing.Optional[str]) -> "Event":
        return self.update(
            display_options_changeset=EventDisplayOptionsChangeset(color=color)
        )

    def set_description(self, description: typing.Optional[str]) -> "Event":
        return self.update(description=description)

    def set_name(self, name: str) -> "Event":
        return self.update(name=name)

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def topic_ids(self, strict_associations: bool = False) -> list[str]:
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
        """
        Updates an event's attributes.

        When provided, ``start_time`` and ``end_time`` should be integers representing nanoseconds
        since the UNIX epoch, or convertible to such integers by :py:func:`~roboto.time.to_epoch_nanoseconds`.

        Args:
            name: The event's human-readable name.
            start_time: Timestamp of the beginning of the event.
            end_time: Timestamp of the end of the event.
            description: An optional description of the event. Set to ``None`` to clear any existing description.
            metadata_changeset: A set of changes to the event's metadata or tags.
            display_options_changeset: A set of changes to the event's display options.

        Returns:
            This ``Event`` with attributes updated accordingly.

        Raises:
            ValueError: If ``start_time`` or ``end_time`` are negative.
            RobotoIllegalArgumentException:
              If ``start_time`` is, or would end up being, greater than ``end_time``.
            RobotoUnauthorizedException:
              If the user is not authorized to view/edit this event.
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
