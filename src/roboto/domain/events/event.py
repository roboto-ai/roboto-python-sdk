# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...association import Association
from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType
from ...time import to_epoch_nanoseconds
from ...updates import (
    MetadataChangeset,
    StrSequence,
)
from .operations import (
    CreateEventRequest,
    QueryEventsForAssociationsRequest,
    UpdateEventRequest,
)
from .record import EventRecord


class Event:
    """
    An event is a "time anchor" which allows you to relate first class Roboto entities (datasets, files, and topics),
    as well as a timespan in which they occurred.
    """

    __roboto_client: RobotoClient
    __record: EventRecord

    @classmethod
    def create(
        cls,
        associations: collections.abc.Sequence[Association],
        start_time: typing.Union[int, datetime.datetime],
        end_time: typing.Optional[typing.Union[int, datetime.datetime]] = None,
        description: typing.Optional[str] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        tags: typing.Optional[list[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Event":
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateEventRequest(
            associations=list(associations),
            start_time=to_epoch_nanoseconds(start_time),
            end_time=to_epoch_nanoseconds(end_time or start_time),
            description=description,
            metadata=metadata or {},
            tags=tags or [],
        )
        record = roboto_client.post(
            "v1/events/create", caller_org_id=caller_org_id, data=request
        ).to_record(EventRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_association(
        cls,
        association: Association,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Event", None, None]:
        """
        Returns all events associated with the provided association. Any events which you don't have access to will be
        filtered out of the response rather than throwing an exception.
        """
        return Event.for_associations([association], roboto_client=roboto_client)

    @classmethod
    def for_associations(
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

    def __init__(
        self, record: EventRecord, roboto_client: typing.Optional[RobotoClient] = None
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def event_id(self) -> str:
        return self.__record.event_id

    @property
    def record(self) -> EventRecord:
        return self.__record

    def delete(self) -> None:
        self.__roboto_client.delete(f"v1/events/id/{self.event_id}")

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "Event":
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "Event":
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

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

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Optional[MetadataChangeset] = None,
    ) -> "Event":
        request = UpdateEventRequest(
            description=description, metadata_changeset=metadata_changeset
        )

        self.__record = self.__roboto_client.put(
            f"/v1/events/id/{self.event_id}", data=request
        ).to_record(EventRecord)

        return self
