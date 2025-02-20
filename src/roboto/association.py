# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import enum
import typing
import urllib.parse

import pydantic

from .exceptions import (
    RobotoIllegalArgumentException,
    RobotoInvalidRequestException,
)


class AssociationType(enum.Enum):
    """AssociationType is the Roboto domain entity type of the association."""

    Dataset = "dataset"
    File = "file"
    Topic = "topic"
    MessagePath = "message_path"


class Association(pydantic.BaseModel):
    """Use to declare an association between two Roboto entities."""

    URL_ENCODING_SEP: typing.ClassVar[str] = ":"

    @staticmethod
    def group_by_type(
        associations: collections.abc.Collection[Association],
    ) -> collections.abc.Mapping[
        AssociationType, collections.abc.Sequence[Association]
    ]:
        response: dict[AssociationType, list[Association]] = {}

        for association in associations:
            if association.association_type not in response:
                response[association.association_type] = []
            response[association.association_type].append(association)

        return response

    @classmethod
    def from_url_encoded_value(cls, encoded: str) -> Association:
        """Reverse of Association::url_encode."""
        unquoted = urllib.parse.unquote_plus(encoded)

        association_type, association_id, *rest = unquoted.split(cls.URL_ENCODING_SEP)
        association_version: int | None = None
        if rest:
            association_version = int(rest[0])

        try:
            return cls(
                association_id=association_id,
                association_type=AssociationType(association_type),
                association_version=association_version,
            )
        except ValueError:
            raise RobotoIllegalArgumentException(
                f"Invalid association type '{association_type}'"
            ) from None

    @classmethod
    def coalesce(
        cls,
        associations: typing.Optional[collections.abc.Collection[Association]] = None,
        dataset_ids: typing.Optional[collections.abc.Collection[str]] = None,
        file_ids: typing.Optional[collections.abc.Collection[str]] = None,
        topic_ids: typing.Optional[collections.abc.Collection[str]] = None,
        message_path_ids: typing.Optional[collections.abc.Collection[str]] = None,
        throw_on_empty: bool = False,
    ) -> list[Association]:
        coalesced: list[Association] = []

        if associations:
            coalesced.extend(associations)

        if dataset_ids:
            coalesced.extend(cls.dataset(dataset_id) for dataset_id in dataset_ids)

        if file_ids:
            coalesced.extend(cls.file(file_id) for file_id in file_ids)

        if message_path_ids:
            coalesced.extend(cls.msgpath(msgpath_id) for msgpath_id in message_path_ids)

        if topic_ids:
            coalesced.extend(cls.topic(topic_id) for topic_id in topic_ids)

        if len(coalesced) == 0 and throw_on_empty:
            raise RobotoInvalidRequestException(
                "At least one association must be provided"
            )

        return coalesced

    @classmethod
    def dataset(cls, dataset_id: str) -> Association:
        return cls(association_id=dataset_id, association_type=AssociationType.Dataset)

    @classmethod
    def file(cls, file_id: str, version: typing.Optional[int] = None):
        return cls(
            association_id=file_id,
            association_type=AssociationType.File,
            association_version=version,
        )

    @classmethod
    def topic(cls, topic_id: str):
        return cls(association_id=topic_id, association_type=AssociationType.Topic)

    @classmethod
    def msgpath(cls, msgpath_id: str) -> Association:
        return cls(
            association_id=msgpath_id, association_type=AssociationType.MessagePath
        )

    association_id: str
    """Roboto identifier"""

    association_type: AssociationType
    """association_type is the Roboto domain entity type of the association."""

    association_version: int | None = None
    """association_version is the Roboto domain entity version of the association, if it exists."""

    parent: typing.Optional[Association] = None
    """
    The next level up in the hierarchy of this association. A message path's parent is its topic,
    a topic's parent is its file, and a file's parent is its dataset.

    The absense of a parent in an Association object doesn't necessarily mean that a parent doesn't exist; parents
    are only provided when they're easily computable in the context of a given request.
    """

    @property
    def dataset_id(self) -> typing.Optional[str]:
        if self.is_dataset:
            return self.association_id

        if self.parent is not None:
            return self.parent.dataset_id

        return None

    @property
    def file_id(self) -> typing.Optional[str]:
        if self.is_file:
            return self.association_id

        if self.parent is not None:
            return self.parent.file_id

        return None

    @property
    def is_dataset(self) -> bool:
        return self.association_type == AssociationType.Dataset

    @property
    def is_file(self) -> bool:
        return self.association_type == AssociationType.File

    @property
    def is_msgpath(self) -> bool:
        return self.association_type == AssociationType.MessagePath

    @property
    def is_topic(self) -> bool:
        return self.association_type == AssociationType.Topic

    @property
    def message_path_id(self) -> typing.Optional[str]:
        if self.is_msgpath:
            return self.association_id

        return None

    @property
    def topic_id(self) -> typing.Optional[str]:
        if self.is_topic:
            return self.association_id

        if self.parent is not None:
            return self.parent.topic_id

        return None

    def url_encode(self) -> str:
        """Association encoded in a URL path segment ready format."""

        parts = [
            self.association_type.value,
            self.association_id,
        ]

        if self.association_version is not None:
            parts.append(str(self.association_version))

        return urllib.parse.quote_plus(Association.URL_ENCODING_SEP.join(parts))
