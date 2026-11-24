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
    """Kind of Roboto entity an association refers to."""

    Dataset = "dataset"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`)."""

    Device = "device"
    """Devices (:py:class:`~roboto.domain.devices.Device`)."""

    DeviceType = "device_type"
    """Device types (``roboto.domain.device_types.DeviceType``)."""

    File = "file"
    """Files (:py:class:`~roboto.domain.files.File`)."""

    Topic = "topic"
    """Topics (:py:class:`~roboto.domain.topics.Topic`)."""

    MessagePath = "message_path"
    """Message paths (:py:class:`~roboto.domain.topics.MessagePath`)."""

    Org = "org"
    """Organizations (:py:class:`~roboto.domain.orgs.Org`)."""


class Association(pydantic.BaseModel):
    """A reference to one Roboto entity, such as a dataset, file, or topic, by its type and ID.

    SDK methods take associations to name the entities they act on or annotate, such as the datasets and files an
    event annotates or the file whose topic to fetch. Build one with a class method such as ``dataset`` or
    ``from_id``.
    """

    URL_ENCODING_SEP: typing.ClassVar[str] = ":"
    """Separator between the type, ID, and version in an encoded association."""

    @staticmethod
    def group_by_type(
        associations: collections.abc.Collection[Association],
    ) -> collections.abc.Mapping[AssociationType, collections.abc.Sequence[Association]]:
        """Group associations by their type.

        Args:
            associations: Associations to group.

        Returns:
            Each type present in ``associations``, mapped to its associations in their input order. A type with no
            associations is absent.
        """
        response: dict[AssociationType, list[Association]] = {}

        for association in associations:
            if association.association_type not in response:
                response[association.association_type] = []
            response[association.association_type].append(association)

        return response

    @classmethod
    def from_url_encoded_value(cls, encoded: str) -> Association:
        """Parse an association from the form ``url_encode`` returns.

        The parsed association has no ``parent``.

        Args:
            encoded: URL-quoted ``<type>:<id>`` or ``<type>:<id>:<version>``, where ``<type>`` is an
                ``AssociationType`` value such as ``file``.

        Raises:
            RobotoIllegalArgumentException: ``<type>`` is not an ``AssociationType`` value.
            ValueError: ``encoded`` has no ``:`` separator, or its version is not an integer.
        """
        unquoted = urllib.parse.unquote_plus(encoded)

        association_type, association_id, *rest = unquoted.split(cls.URL_ENCODING_SEP)
        association_version: typing.Union[int, None] = None
        if rest:
            association_version = int(rest[0])

        try:
            return cls(
                association_id=association_id,
                association_type=AssociationType(association_type),
                association_version=association_version,
            )
        except ValueError:
            raise RobotoIllegalArgumentException(f"Invalid association type '{association_type}'") from None

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
        """Combine associations and lists of entity IDs into one list of associations.

        Duplicates are kept.

        Args:
            associations: Associations to include as given. ``None`` includes none.
            dataset_ids: IDs of datasets to include. ``None`` includes none.
            file_ids: IDs of files to include, each with no version. ``None`` includes none.
            topic_ids: IDs of topics to include. ``None`` includes none.
            message_path_ids: IDs of message paths to include. ``None`` includes none.
            throw_on_empty: Whether to raise ``RobotoInvalidRequestException`` when the result would be empty.

        Returns:
            ``associations``, then one association for each dataset ID, file ID, message path ID, and topic ID, in that
            order.

        Raises:
            RobotoInvalidRequestException: ``throw_on_empty`` is true and every other argument is empty or ``None``.
        """
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
            raise RobotoInvalidRequestException("At least one association must be provided")

        return coalesced

    @classmethod
    def from_id(cls, association_id: str) -> Association:
        """Build an association from an entity's ID, taking its type from the ID's prefix.

        The prefixes and the types they map to:

        - ``ds_``: datasets.
        - ``fl_``: files, with no version.
        - ``tp_``: topics.
        - ``mp_``: message paths.
        - ``dv_``: devices.
        - ``og_``: organizations.
        - ``dt_``: device types.

        Args:
            association_id: ID of a dataset, file, topic, message path, device, organization, or device type.

        Raises:
            RobotoIllegalArgumentException: ``association_id`` begins with none of these prefixes.
        """
        prefix_to_type = {
            "ds_": AssociationType.Dataset,
            "fl_": AssociationType.File,
            "tp_": AssociationType.Topic,
            "mp_": AssociationType.MessagePath,
            "dv_": AssociationType.Device,
            "og_": AssociationType.Org,
            "dt_": AssociationType.DeviceType,
        }

        for prefix, assoc_type in prefix_to_type.items():
            if association_id.startswith(prefix):
                return cls(association_id=association_id, association_type=assoc_type)

        raise RobotoIllegalArgumentException(
            f"Cannot infer association type from ID '{association_id}'. "
            f"Expected ID to start with one of: {', '.join(prefix_to_type.keys())}"
        )

    @classmethod
    def dataset(cls, dataset_id: str) -> Association:
        """Build an association with a dataset.

        Args:
            dataset_id: ID of the dataset, beginning with ``ds_``.
        """
        return cls(association_id=dataset_id, association_type=AssociationType.Dataset)

    @classmethod
    def device(cls, universal_device_id: str) -> Association:
        """Build an association with a device.

        Args:
            universal_device_id: ID of the device, beginning with ``dv_``
                (:py:attr:`~roboto.domain.devices.DeviceRecord.universal_device_id`), not the ``device_id`` the
                organization gave it.
        """
        return cls(association_id=universal_device_id, association_type=AssociationType.Device)

    @classmethod
    def device_type(cls, device_type_id: str) -> Association:
        """Build an association with a device type.

        Args:
            device_type_id: ID of the device type, beginning with ``dt_``, not its name.
        """
        return cls(association_id=device_type_id, association_type=AssociationType.DeviceType)

    @classmethod
    def org(cls, org_id: str) -> Association:
        """Build an association with an organization.

        Args:
            org_id: ID of the organization, beginning with ``og_``.
        """
        return cls(association_id=org_id, association_type=AssociationType.Org)

    @classmethod
    def file(cls, file_id: str, version: typing.Optional[int] = None):
        """Build an association with a file, or with one version of it.

        Args:
            file_id: ID of the file, beginning with ``fl_``.
            version: Version of the file. ``None`` names no version.
        """
        return cls(
            association_id=file_id,
            association_type=AssociationType.File,
            association_version=version,
        )

    @classmethod
    def topic(cls, topic_id: str):
        """Build an association with a topic.

        Args:
            topic_id: ID of the topic, beginning with ``tp_``.
        """
        return cls(association_id=topic_id, association_type=AssociationType.Topic)

    @classmethod
    def msgpath(cls, msgpath_id: str) -> Association:
        """Build an association with a message path.

        Args:
            msgpath_id: ID of the message path, beginning with ``mp_``.
        """
        return cls(association_id=msgpath_id, association_type=AssociationType.MessagePath)

    association_id: str
    """ID of the entity the association refers to."""

    association_type: AssociationType
    """Kind of entity ``association_id`` identifies."""

    association_version: typing.Union[int, None] = None
    """Version of the entity, or ``None`` if the association names no version. Only files have versions."""

    parent: typing.Optional[Association] = None
    """Association with the entity one level up: a message path's topic, a topic's file, or a file's dataset.

    ``None`` does not mean the entity has no parent. Roboto sets ``parent`` only in some responses, such as the
    ``associations`` of an event.
    """

    @property
    def dataset_id(self) -> typing.Optional[str]:
        """ID of the dataset the association refers to or its ``parent`` chain reaches, or ``None`` if neither."""
        if self.is_dataset:
            return self.association_id

        if self.parent is not None:
            return self.parent.dataset_id

        return None

    @property
    def file_id(self) -> typing.Optional[str]:
        """ID of the file the association refers to or its ``parent`` chain reaches, or ``None`` if neither."""
        if self.is_file:
            return self.association_id

        if self.parent is not None:
            return self.parent.file_id

        return None

    @property
    def is_dataset(self) -> bool:
        """Whether the association is with a dataset."""
        return self.association_type == AssociationType.Dataset

    @property
    def is_device(self) -> bool:
        """Whether the association is with a device."""
        return self.association_type == AssociationType.Device

    @property
    def is_device_type(self) -> bool:
        """Whether the association is with a device type."""
        return self.association_type == AssociationType.DeviceType

    @property
    def is_file(self) -> bool:
        """Whether the association is with a file."""
        return self.association_type == AssociationType.File

    @property
    def is_msgpath(self) -> bool:
        """Whether the association is with a message path."""
        return self.association_type == AssociationType.MessagePath

    @property
    def is_org(self) -> bool:
        """Whether the association is with an organization."""
        return self.association_type == AssociationType.Org

    @property
    def is_topic(self) -> bool:
        """Whether the association is with a topic."""
        return self.association_type == AssociationType.Topic

    @property
    def message_path_id(self) -> typing.Optional[str]:
        """ID of the message path the association refers to, or ``None`` if it refers to another kind of entity."""
        if self.is_msgpath:
            return self.association_id

        return None

    @property
    def topic_id(self) -> typing.Optional[str]:
        """ID of the topic the association refers to or its ``parent`` chain reaches, or ``None`` if neither."""
        if self.is_topic:
            return self.association_id

        if self.parent is not None:
            return self.parent.topic_id

        return None

    def url_encode(self) -> str:
        """Encode the association as one URL path segment.

        The segment is ``<type>:<id>``, or ``<type>:<id>:<version>`` when ``association_version`` is set, where
        ``<type>`` is the ``AssociationType`` value such as ``file``. It is quoted with
        ``urllib.parse.quote_plus``, so each ``:`` becomes ``%3A``. ``parent`` is left out.
        ``from_url_encoded_value`` parses it back.
        """
        parts = [
            self.association_type.value,
            self.association_id,
        ]

        if self.association_version is not None:
            parts.append(str(self.association_version))

        return urllib.parse.quote_plus(Association.URL_ENCODING_SEP.join(parts))
