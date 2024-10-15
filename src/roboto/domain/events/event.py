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
from ...sentinels import NotSet, NotSetType
from ...time import to_epoch_nanoseconds
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
    QueryEventsForAssociationsRequest,
    UpdateEventRequest,
)
from .record import EventRecord

if typing.TYPE_CHECKING:
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
        start_time: typing.Union[int, datetime.datetime],
        name: str = "Custom Event",
        associations: typing.Optional[collections.abc.Collection[Association]] = None,
        file_ids: typing.Optional[collections.abc.Collection[str]] = None,
        topic_ids: typing.Optional[collections.abc.Collection[str]] = None,
        dataset_ids: typing.Optional[collections.abc.Collection[str]] = None,
        message_path_ids: typing.Optional[collections.abc.Collection[str]] = None,
        end_time: typing.Optional[typing.Union[int, datetime.datetime]] = None,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Event":
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
        transitive: bool = False,
    ) -> collections.abc.Generator["Event", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        # This will return only events that explicitly have an association with this dataset
        if transitive is False:
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
    def dataset_ids(self) -> list[str]:
        return [
            association.association_id
            for association in self.__record.associations
            if association.is_dataset
        ]

    @property
    def end_time(self) -> int:
        """Epoch nanoseconds"""
        return self.__record.end_time

    @property
    def event_id(self) -> str:
        return self.__record.event_id

    @property
    def file_ids(self) -> list[str]:
        return [
            association.association_id
            for association in self.__record.associations
            if association.is_file
        ]

    @property
    def message_path_ids(self) -> list[str]:
        return [
            association.association_id
            for association in self.__record.associations
            if association.is_msgpath
        ]

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
    def topic_ids(self) -> list[str]:
        return [
            association.association_id
            for association in self.__record.associations
            if association.is_topic
        ]

    def delete(self) -> None:
        self.__roboto_client.delete(f"v1/events/id/{self.event_id}")

    def get_data(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        topic_name: typing.Optional[str] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
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
        if len(self.message_path_ids) > 0:
            message_paths = [
                MessagePath.from_id(
                    message_path_id=message_path_id,
                    roboto_client=self.__roboto_client,
                    topic_data_service=topic_data_service,
                )
                for message_path_id in self.message_path_ids
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
        if len(self.topic_ids) > 0:
            unique_topics = set(self.topic_ids)
            if len(unique_topics) > 1:
                raise RobotoInvalidRequestException(
                    "Unable to load event data for events associated with more than one topic"
                )

            topic_id = self.topic_ids[0]
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
        if len(self.file_ids) != 0:
            if len(self.file_ids) > 1:
                raise RobotoInvalidRequestException(
                    "Unable to load event data for events associated with more than one file"
                )

            if topic_name is None:
                raise RobotoInvalidRequestException(
                    "Must provide 'topic_name' when attempting to load data for an event associated with a file"
                )

            file = File.from_id(
                file_id=self.file_ids[0], roboto_client=self.__roboto_client
            )
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

        if TopicDataService.LOG_TIME_ATTR_NAME not in df.columns:
            # Expected only in edge case:
            #   if this event's time bounds are outside the range of
            #   log times actually found in the underlying topic data.
            # In this case, the dataframe is expected to be entirely empty.
            return df

        return df.set_index(TopicDataService.LOG_TIME_ATTR_NAME)

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

    def set_description(self, description: typing.Optional[str]) -> "Event":
        return self.update(description=description)

    def set_name(self, name: str) -> "Event":
        return self.update(name=name)

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Optional[MetadataChangeset] = None,
        name: typing.Optional[str] = None,
    ) -> "Event":
        request = UpdateEventRequest(
            description=description, metadata_changeset=metadata_changeset, name=name
        )

        self.__record = self.__roboto_client.put(
            f"/v1/events/id/{self.event_id}", data=request
        ).to_record(EventRecord)

        return self
