# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing
import urllib.parse
import urllib.request

from ...association import Association
from ...http import RobotoClient
from ...logging import default_logger
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...time import Time
from ...updates import (
    MetadataChangeset,
    TaglessMetadataChangeset,
)
from .message_path import MessagePath
from .operations import (
    AddMessagePathRepresentationRequest,
    AddMessagePathRequest,
    CreateTopicRequest,
    SetDefaultRepresentationRequest,
    UpdateMessagePathRequest,
    UpdateTopicRequest,
)
from .record import (
    CanonicalDataType,
    MessagePathRecord,
    RepresentationRecord,
    RepresentationStorageFormat,
    TopicRecord,
)
from .topic_data_service import TopicDataService

logger = default_logger()


class Topic:
    __record: TopicRecord
    __roboto_client: RobotoClient
    __topic_data_service: TopicDataService

    @classmethod
    def create(
        cls,
        association: Association,
        topic_name: str,
        end_time: typing.Optional[int] = None,
        message_count: typing.Optional[int] = None,
        metadata: typing.Optional[collections.abc.Mapping[str, typing.Any]] = None,
        schema_checksum: typing.Optional[str] = None,
        schema_name: typing.Optional[str] = None,
        start_time: typing.Optional[int] = None,
        message_paths: typing.Optional[
            collections.abc.Sequence[AddMessagePathRequest]
        ] = (None),
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateTopicRequest(
            association=association,
            end_time=end_time,
            message_count=message_count,
            message_paths=message_paths,
            metadata=metadata,
            schema_checksum=schema_checksum,
            schema_name=schema_name,
            start_time=start_time,
            topic_name=topic_name,
        )
        response = roboto_client.post(
            "v1/topics",
            data=request,
            caller_org_id=caller_org_id,
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_name_and_association(
        cls,
        topic_name: str,
        association: Association,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        roboto_client = RobotoClient.defaulted(roboto_client)
        quoted_topic_name = urllib.parse.quote_plus(topic_name)
        encoded_association = association.url_encode()

        response = roboto_client.get(
            f"v1/topics/association/{encoded_association}/name/{quoted_topic_name}",
            owner_org_id=owner_org_id,
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def get_by_association(
        cls,
        association: Association,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Topic", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        encoded_association = association.url_encode()

        page_token: typing.Optional[str] = None
        while True:
            response = roboto_client.get(
                f"v1/topics/association/{encoded_association}",
                owner_org_id=owner_org_id,
                query={"page_token": page_token} if page_token else None,
            )
            paginated_results = response.to_paginated_list(TopicRecord)
            for topic_record in paginated_results.items:
                yield cls(topic_record, roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: TopicRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
        topic_data_service: typing.Optional[TopicDataService] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__topic_data_service = topic_data_service or TopicDataService(
            self.__roboto_client
        )

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def association(self) -> Association:
        return self.__record.association

    @property
    def default_representation(self) -> typing.Optional[RepresentationRecord]:
        return self.__record.default_representation

    @property
    def message_paths(self) -> collections.abc.Sequence[MessagePathRecord]:
        return self.__record.message_paths

    @property
    def name(self) -> str:
        return self.__record.topic_name

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def record(self) -> TopicRecord:
        return self.__record

    @property
    def url_quoted_name(self) -> str:
        return urllib.parse.quote_plus(self.name)

    def add_message_path(
        self,
        message_path: str,
        data_type: str,
        canonical_data_type: CanonicalDataType,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
    ) -> MessagePathRecord:

        request = AddMessagePathRequest(
            message_path=message_path,
            data_type=data_type,
            canonical_data_type=canonical_data_type,
            metadata=metadata or {},
        )

        encoded_association = self.association.url_encode()
        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path",
            data=request,
            owner_org_id=self.org_id,
        )
        message_path_record = response.to_record(MessagePathRecord)
        self.__refresh()
        return message_path_record

    def add_message_path_representation(
        self,
        association: Association,
        storage_format: RepresentationStorageFormat,
        version: int,
        topic_message_path_id: int,
    ) -> RepresentationRecord:
        encoded_association = self.association.url_encode()

        request = AddMessagePathRepresentationRequest(
            association=association,
            storage_format=storage_format,
            version=version,
            topic_message_path_id=topic_message_path_id,
        )

        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.__refresh()
        return representation_record

    def delete(self) -> None:
        encoded_association = self.association.url_encode()
        self.__roboto_client.delete(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}",
            owner_org_id=self.org_id,
        )

    def get_data(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> collections.abc.Generator[dict[str, typing.Any], None, None]:
        """
        Return this topic's underlying data.
        Each yielded datum is a dictionary that matches this topic's schema.

        If ``message_paths_include`` or ``message_paths_exclude`` are defined,
        they should be dot notation paths that match attributes of individual data records.

        If ``start_time`` or ``end_time`` are defined,
        they should either be integers that represent nanoseconds since UNIX epoch,
        or convertible to such by :py:func:`~roboto.time.to_epoch_nanoseconds`.
        Either or both may be omitted.
        ``start_time`` is inclusive, while ``end_time`` is exclusive.

        If ``cache_dir`` is defined, topic data will be downloaded to this location if necessary.
        If not provided, ``cache_dir`` defaults to
        :py:attr:`~roboto.domain.topics.topic_data_service.TopicDataService.DEFAULT_CACHE_DIR`.

        For each example below, assume the following is a sample datum record that can be found in this topic:

        ::

            {
                "angular_velocity": {
                    "x": <uint32>,
                    "y": <uint32>,
                    "z": <uint32>
                },
                "orientation": {
                    "x": <uint32>,
                    "y": <uint32>,
                    "z": <uint32>,
                    "w": <uint32>
                }
            }

        Examples:
            Print all data to stdout.

            >>> topic = Topic.from_name_and_association(...)
            >>> for record in topic.get_data():
            >>>      print(record)

            Only include the `"angular_velocity"` sub-object, but filter out its `"y"` property.

            >>> topic = Topic.from_name_and_association(...)
            >>> for record in topic.get_data(
            >>>   message_paths_include=["angular_velocity"],
            >>>   message_paths_exclude=["angular_velocity.y"],
            >>> ):
            >>>      print(record)

            Only include data between two timestamps:

            >>> topic = Topic.from_name_and_association(...)
            >>> for record in topic.get_data(
            >>>   start_time=1722870127699468923,
            >>>   end_time=1722870127699468924,
            >>> ):
            >>>      print(record)

            Collect all topic data into a dataframe. Requires installing ``pandas`` into the same Python environment.

            >>> import pandas as pd
            >>> topic = Topic.from_name_and_association(...)
            >>> df = pd.json_normalize(data=list(topic.get_data()))

        """
        message_paths = set(
            message_path_record.message_path
            for message_path_record in self.__record.message_paths
        )
        if message_paths_include and message_paths.isdisjoint(
            set(message_paths_include)
        ):
            difference = set(message_paths_include) - message_paths
            raise ValueError(
                f"Unknown message_paths passed as 'message_paths_include': {difference}"
            )

        if message_paths_exclude and message_paths.isdisjoint(
            set(message_paths_exclude)
        ):
            difference = set(message_paths_exclude) - message_paths
            raise ValueError(
                f"Unknown message_paths passed as 'message_paths_exclude': {difference}"
            )

        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def get_message_path(self, message_path: str) -> MessagePath:
        for message_path_record in self.__record.message_paths:
            if message_path_record.message_path == message_path:
                return MessagePath(
                    message_path_record,
                    roboto_client=self.__roboto_client,
                    topic_data_service=self.__topic_data_service,
                )

        raise ValueError(
            f"Topic '{self.name}' does not have a message path matching '{message_path}'"
        )

    def set_default_representation(
        self,
        association: Association,
        storage_format: RepresentationStorageFormat,
        version: int,
    ) -> RepresentationRecord:
        encoded_association = self.association.url_encode()
        request = SetDefaultRepresentationRequest(
            association=association,
            storage_format=storage_format,
            version=version,
        )
        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.__refresh()
        return representation_record

    def to_association(self) -> Association:
        return Association.topic(self.record.topic_id)

    def update(
        self,
        end_time: typing.Union[typing.Optional[int], NotSetType] = NotSet,
        message_count: typing.Union[int, NotSetType] = NotSet,
        schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        start_time: typing.Union[typing.Optional[int], NotSetType] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
    ) -> "Topic":
        encoded_association = self.association.url_encode()

        request = remove_not_set(
            UpdateTopicRequest(
                end_time=end_time,
                message_count=message_count,
                schema_checksum=schema_checksum,
                schema_name=schema_name,
                start_time=start_time,
                metadata_changeset=metadata_changeset,
            )
        )

        response = self.__roboto_client.put(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(TopicRecord)
        self.__record = record
        return self

    def update_message_path(
        self,
        message_path: str,
        metadata_changeset: typing.Union[TaglessMetadataChangeset],
    ) -> MessagePathRecord:
        encoded_association = self.association.url_encode()
        request = UpdateMessagePathRequest(
            message_path=message_path,
            metadata_changeset=metadata_changeset,
        )
        response = self.__roboto_client.put(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path",
            data=request,
            owner_org_id=self.org_id,
        )
        message_path_record = response.to_record(MessagePathRecord)
        self.__refresh()
        return message_path_record

    def __refresh(self) -> None:
        topic = Topic.from_name_and_association(
            topic_name=self.name,
            association=self.association,
            owner_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )
        self.__record = topic.record
