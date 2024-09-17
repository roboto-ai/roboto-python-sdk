# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import enum
import typing
import urllib.parse

import pydantic

from .exceptions import (
    RobotoIllegalArgumentException,
)


class AssociationType(enum.Enum):
    """AssociationType is the Roboto domain entity type of the association."""

    Dataset = "dataset"
    File = "file"
    Topic = "topic"


class Association(pydantic.BaseModel):
    """Use to declare an association between two Roboto entities."""

    URL_ENCODING_SEP: typing.ClassVar[str] = ":"

    @staticmethod
    def group_by_type(
        associations: collections.abc.Collection["Association"],
    ) -> collections.abc.Mapping[
        AssociationType, collections.abc.Sequence["Association"]
    ]:
        response: dict[AssociationType, list[Association]] = {}

        for association in associations:
            if association.association_type not in response:
                response[association.association_type] = []
            response[association.association_type].append(association)

        return response

    @classmethod
    def from_url_encoded_value(cls, encoded: str) -> "Association":
        """Reverse of Association::url_encode."""
        unquoted = urllib.parse.unquote_plus(encoded)
        association_type, association_id = unquoted.split(cls.URL_ENCODING_SEP)
        try:
            return cls(
                association_id=association_id,
                association_type=AssociationType(association_type),
            )
        except ValueError:
            raise RobotoIllegalArgumentException(
                f"Invalid association type '{association_type}'"
            ) from None

    @classmethod
    def coalesce(
        cls,
        associations: typing.Optional[collections.abc.Collection["Association"]] = None,
        dataset_ids: typing.Optional[collections.abc.Collection[str]] = None,
        file_ids: typing.Optional[collections.abc.Collection[str]] = None,
        topic_ids: typing.Optional[collections.abc.Collection[str]] = None,
        throw_on_empty: bool = False,
    ) -> list["Association"]:
        coalesced: list[Association] = []

        if associations:
            coalesced.extend(associations)

        if dataset_ids:
            coalesced.extend(cls.dataset(dataset_id) for dataset_id in dataset_ids)

        if file_ids:
            coalesced.extend(cls.file(file_id) for file_id in file_ids)

        if topic_ids:
            coalesced.extend(cls.topic(topic_id) for topic_id in topic_ids)

        if len(coalesced) == 0 and throw_on_empty:
            raise RobotoIllegalArgumentException(
                "At least one association must be provided"
            )

        return coalesced

    @classmethod
    def dataset(cls, dataset_id: str):
        return cls(association_id=dataset_id, association_type=AssociationType.Dataset)

    @classmethod
    def file(cls, file_id: str):
        return cls(association_id=file_id, association_type=AssociationType.File)

    @classmethod
    def topic(cls, topic_id: str):
        return cls(association_id=topic_id, association_type=AssociationType.Topic)

    association_id: str
    """Roboto identifier"""

    association_type: AssociationType
    """association_type is the Roboto domain entity type of the association."""

    @property
    def is_dataset(self) -> bool:
        return self.association_type == AssociationType.Dataset

    @property
    def is_file(self) -> bool:
        return self.association_type == AssociationType.File

    @property
    def is_topic(self) -> bool:
        return self.association_type == AssociationType.Topic

    def url_encode(self) -> str:
        """Association encoded in a URL path segment ready format."""
        return urllib.parse.quote_plus(
            f"{self.association_type.value}{Association.URL_ENCODING_SEP}{self.association_id}"
        )
