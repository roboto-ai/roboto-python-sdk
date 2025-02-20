# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
from datetime import datetime
import pathlib
import typing
import urllib.parse
import urllib.request

from ...association import Association
from ...compat import import_optional_dependency
from ...http import RobotoClient
from ...logging import default_logger
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
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
    MessagePathChangeset,
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

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep

logger = default_logger()


class Topic:
    """
    A sequence of structured time-series data linked to a source file.
    Each topic follows a defined schema, where the message paths represent the
    individual fields or signals within that schema.
    """

    __record: TopicRecord
    __roboto_client: RobotoClient
    __topic_data_service: TopicDataService

    @classmethod
    def create(
        cls,
        file_id: str,
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
            association=Association.file(file_id),
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
    def from_id(
        cls,
        topic_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        roboto_client = RobotoClient.defaulted(roboto_client)

        response = roboto_client.get(
            f"v1/topics/id/{topic_id}",
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_name_and_file(
        cls,
        topic_name: str,
        file_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Topic":
        roboto_client = RobotoClient.defaulted(roboto_client)
        quoted_topic_name = urllib.parse.quote_plus(topic_name)
        encoded_association = Association.file(file_id).url_encode()

        response = roboto_client.get(
            f"v1/topics/association/{encoded_association}/name/{quoted_topic_name}",
            owner_org_id=owner_org_id,
        )
        record = response.to_record(TopicRecord)
        return cls(record, roboto_client)

    @classmethod
    def get_by_dataset(
        cls, dataset_id: str, roboto_client: typing.Optional[RobotoClient] = None
    ):
        """
        List all topics associated with files of a dataset. If multiple files have topics with the same name (i.e.
        if a dataset has chunked files with the same schema), they'll be returned as separate topic objects.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        page_token: typing.Optional[str] = None

        while True:
            query_params: dict[str, typing.Any] = {}
            if page_token:
                query_params["page_token"] = str(page_token)

            paginated_results = roboto_client.get(
                f"v1/datasets/{dataset_id}/topics",
                query=query_params,
            ).to_paginated_list(TopicRecord)

            for record in paginated_results.items:
                yield cls(record=record, roboto_client=roboto_client)
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    @classmethod
    def get_by_file(
        cls,
        file_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Topic", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        encoded_association = Association.file(file_id).url_encode()

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

    def __eq__(self, other: typing.Any):
        if not isinstance(other, Topic):
            return NotImplemented

        return self.__record == other.__record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def association(self) -> Association:
        return self.__record.association

    @property
    def created(self) -> datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def dataset_id(self) -> typing.Optional[str]:
        if self.association.is_dataset:
            return self.association.association_id

        if self.association.is_file:
            # This is equivalent to File.from_id(file_id), but without introducing a circular dependency
            return self.__roboto_client.get(
                f"v1/files/record/{self.association.association_id}"
            ).to_dict(json_path=["data", "association_id"])

        return None

    @property
    def default_representation(self) -> typing.Optional[RepresentationRecord]:
        return self.__record.default_representation

    @property
    def end_time(self) -> typing.Optional[int]:
        return self.__record.end_time

    @property
    def file_id(self) -> typing.Optional[str]:
        if self.association.is_file:
            return self.association.association_id

        return None

    @property
    def message_count(self) -> typing.Optional[int]:
        return self.__record.message_count

    @property
    def message_paths(self) -> collections.abc.Sequence[MessagePathRecord]:
        return self.__record.message_paths

    @property
    def metadata(self) -> dict[str, typing.Any]:
        return dict(self.__record.metadata)

    @property
    def modified(self) -> datetime:
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        return self.__record.modified_by

    @property
    def name(self) -> str:
        return self.__record.topic_name

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def record(self) -> TopicRecord:
        """Topic representation in the Roboto database.

        This property is on the path to deprecation. All ``TopicRecord`` attributes
        are accessible directly using a ``Topic`` instance.
        """

        return self.__record

    @property
    def schema_checksum(self) -> typing.Optional[str]:
        return self.__record.schema_checksum

    @property
    def schema_name(self) -> typing.Optional[str]:
        return self.__record.schema_name

    @property
    def start_time(self) -> typing.Optional[int]:
        return self.__record.start_time

    @property
    def topic_id(self) -> str:
        return self.__record.topic_id

    @property
    def topic_name(self) -> str:
        return self.__record.topic_name

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
        self.refresh()
        return message_path_record

    def add_message_path_representation(
        self,
        message_path_id: str,
        association: Association,
        storage_format: RepresentationStorageFormat,
        version: int,
    ) -> RepresentationRecord:
        encoded_association = self.association.url_encode()

        request = AddMessagePathRepresentationRequest(
            association=association,
            message_path_id=message_path_id,
            storage_format=storage_format,
            version=version,
        )

        response = self.__roboto_client.post(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path/representation",
            data=request,
            owner_org_id=self.org_id,
        )
        representation_record = response.to_record(RepresentationRecord)
        self.refresh()
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

            >>> topic = Topic.from_name_and_file(...)
            >>> for record in topic.get_data():
            >>>      print(record)

            Only include the `"angular_velocity"` sub-object, but filter out its `"y"` property.

            >>> topic = Topic.from_name_and_file(...)
            >>> for record in topic.get_data(
            >>>   message_paths_include=["angular_velocity"],
            >>>   message_paths_exclude=["angular_velocity.y"],
            >>> ):
            >>>      print(record)

            Only include data between two timestamps:

            >>> topic = Topic.from_name_and_file(...)
            >>> for record in topic.get_data(
            >>>   start_time=1722870127699468923,
            >>>   end_time=1722870127699468924,
            >>> ):
            >>>      print(record)

            Collect all topic data into a dataframe. Requires installing the ``roboto[analytics]`` extra.

            >>> topic = Topic.from_name_and_file(...)
            >>> df = topic.get_data_as_df()

        """
        yield from self.__topic_data_service.get_data(
            topic_id=self.__record.topic_id,
            message_paths_include=message_paths_include,
            message_paths_exclude=message_paths_exclude,
            start_time=start_time,
            end_time=end_time,
            cache_dir_override=cache_dir,
        )

    def get_data_as_df(
        self,
        message_paths_include: typing.Optional[collections.abc.Sequence[str]] = None,
        message_paths_exclude: typing.Optional[collections.abc.Sequence[str]] = None,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        cache_dir: typing.Union[str, pathlib.Path, None] = None,
    ) -> pandas.DataFrame:
        """
        Return this topic's underlying data as a pandas DataFrame.

        Requires installing this package using the ``roboto[analytics]`` extra.

        See :py:meth:`~roboto.domain.topics.topic.Topic.get_data` for more information on the parameters.
        """
        pandas = import_optional_dependency("pandas", "analytics")

        df = pandas.json_normalize(
            data=list(
                self.get_data(
                    message_paths_include=message_paths_include,
                    message_paths_exclude=message_paths_exclude,
                    start_time=start_time,
                    end_time=end_time,
                    cache_dir=cache_dir,
                )
            )
        )

        if TopicDataService.LOG_TIME_ATTR_NAME in df.columns:
            return df.set_index(TopicDataService.LOG_TIME_ATTR_NAME)

        return df

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

    def refresh(self) -> None:
        topic = Topic.from_id(self.topic_id, self.__roboto_client)
        self.__record = topic.__record

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
        self.refresh()
        return representation_record

    def to_association(self) -> Association:
        return Association.topic(self.topic_id)

    def update(
        self,
        end_time: typing.Union[typing.Optional[int], NotSetType] = NotSet,
        message_count: typing.Union[int, NotSetType] = NotSet,
        schema_checksum: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        schema_name: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        start_time: typing.Union[typing.Optional[int], NotSetType] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        message_path_changeset: typing.Union[MessagePathChangeset, NotSetType] = NotSet,
    ) -> "Topic":
        """Updates a topic's attributes and (optionally) its message paths.

        Args:
            schema_name:
              topic schema name. Setting to ``None`` clears the attribute.
            schema_checksum:
              topic schema checksum. Setting to ``None`` clears the attribute.
            start_time:
              topic data start time, in epoch nanoseconds.
              Must be non-negative. Setting to ``None`` clears the attribute.
            end_time:
              topic data end time, in epoch nanoseconds. Must be non-negative, and greater than `start_time`.
              Setting to `None` clears the attribute.
            message_count:
              number of messages recorded for this topic. Must be non-negative.
            metadata_changeset:
              a set of changes to apply to the topic's metadata
            message_path_changeset:
              a set of additions, deletions or updates to this topic's message paths.
              Updating or deleting non-existent message paths has no effect.
              Attempting to (re-)add existing message paths raises ``RobotoConflictException``,
              unless the changeset's ``replace_all`` flag is set to ``True``

        Returns:
            this ``Topic`` object with any updates applied

        Raises:
            RobotoInvalidRequestException:
              if any method argument has an invalid value, e.g. a negative ``message_count``
            RobotoConflictException:
              if, as part of the update, an attempt is made to add an already extant
              message path, and to this topic, and ``replace_all`` is not toggled
              on the ``message_path_changeset``
        """

        request = remove_not_set(
            UpdateTopicRequest(
                end_time=end_time,
                message_count=message_count,
                schema_checksum=schema_checksum,
                schema_name=schema_name,
                start_time=start_time,
                metadata_changeset=metadata_changeset,
                message_path_changeset=message_path_changeset,
            )
        )

        response = self.__roboto_client.put(
            f"v1/topics/id/{self.topic_id}",
            data=request,
            owner_org_id=self.org_id,
        )

        record = response.to_record(TopicRecord)
        self.__record = record

        if is_set(message_path_changeset) and message_path_changeset.has_changes():
            self.refresh()

        return self

    def update_message_path(
        self,
        message_path: str,
        metadata_changeset: typing.Union[TaglessMetadataChangeset, NotSetType] = NotSet,
        data_type: typing.Union[str, NotSetType] = NotSet,
        canonical_data_type: typing.Union[CanonicalDataType, NotSetType] = NotSet,
    ) -> MessagePath:
        """Updates the metadata and (optionally) other attributes of a message path.

        Args:
            message_path:
              name of the message path to update
            metadata_changeset:
              metadata changeset to apply to any existing metadata
            data_type:
              native (i.e. application-specific) message path data type.
            canonical_data_type:
              canonical Roboto data type corresponding to the native data type.

        Returns:
            A ``MessagePath`` representing the updated message path

        Raises:
            RobotoNotFoundException: if no such message path exists for this topic
        """

        request = remove_not_set(
            UpdateMessagePathRequest(
                message_path=message_path,
                metadata_changeset=metadata_changeset,
                data_type=data_type,
                canonical_data_type=canonical_data_type,
            )
        )

        encoded_association = self.association.url_encode()
        response = self.__roboto_client.put(
            f"v1/topics/association/{encoded_association}/name/{self.url_quoted_name}/message-path",
            data=request,
            owner_org_id=self.org_id,
        )

        message_path_record = response.to_record(MessagePathRecord)
        self.refresh()

        return MessagePath(
            record=message_path_record,
            roboto_client=self.__roboto_client,
            topic_data_service=self.__topic_data_service,
        )
