# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

from ...http import RobotoClient
from ...warnings import experimental
from .record import (
    SchemaFieldRecord,
    TopicSchemaRecord,
)


@experimental
class TopicSchema:
    """Describes the field structure of a topic's messages.

    A topic schema is identified by a name (e.g., ``"sensor_msgs/Imu"``) and a
    content-based checksum deterministically derived from its fields.
    Schemas are deduplicated within an organization: topics whose fields share the same names,
    paths, and data types reference the same schema.

    Use :py:meth:`from_id` when you already know the ``schema_id``, or :py:meth:`for_topic` to retrieve the
    schema associated with a specific topic. :py:meth:`Topic.get_schema` is also a convenient entry point.

    Examples:
        Retrieve a topic's schema and inspect its fields:

        >>> from roboto.domain.topics import TopicSchema
        >>> schema = TopicSchema.for_topic(topic_id="tp_abc123")
        >>> print(schema.name, schema.checksum)
        >>> for field in schema.fields:
        ...     print(field.path_in_schema, field.data_type)
    """

    __record: TopicSchemaRecord
    __fields: list[SchemaFieldRecord]
    __roboto_client: RobotoClient

    @classmethod
    def for_topic(
        cls,
        topic_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "TopicSchema":
        """Retrieve the schema associated with a topic.

        Args:
            topic_id: Unique identifier of the topic whose schema to retrieve.
            owner_org_id: Organization that owns the topic. Required for cross-org access.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            A :py:class:`TopicSchema` for the topic.

        Raises:
            RobotoNotFoundException: The topic does not exist, or has no schema associated with it.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/topics/id/{topic_id}/schema",
            owner_org_id=owner_org_id,
        ).to_record(TopicSchemaRecord)
        fields = roboto_client.get(
            f"v1/topics/schema/id/{record.schema_id}/fields",
            owner_org_id=owner_org_id,
        ).to_record_list(SchemaFieldRecord)
        return cls(record, fields, roboto_client)

    @classmethod
    def from_id(
        cls,
        schema_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "TopicSchema":
        """Retrieve a schema by its ID.

        Args:
            schema_id: Unique identifier of the schema to retrieve.
            owner_org_id: Organization that owns the schema. Required when the caller belongs to multiple orgs.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            A :py:class:`TopicSchema` for the given ``schema_id``.

        Raises:
            RobotoNotFoundException: No schema with this ID exists in the scoped org.

        Examples:
            >>> from roboto.domain.topics import TopicSchema
            >>> schema = TopicSchema.from_id("ts_abc123")
            >>> for field in schema.fields:
            ...     print(field.path_in_schema, field.data_type)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/topics/schema/id/{schema_id}",
            owner_org_id=owner_org_id,
        ).to_record(TopicSchemaRecord)
        fields = roboto_client.get(
            f"v1/topics/schema/id/{schema_id}/fields",
            owner_org_id=owner_org_id,
        ).to_record_list(SchemaFieldRecord)
        return cls(record, fields, roboto_client)

    def __init__(
        self,
        record: TopicSchemaRecord,
        fields: list[SchemaFieldRecord],
        roboto_client: RobotoClient,
    ):
        self.__record = record
        self.__fields = fields
        self.__roboto_client = roboto_client

    @property
    def checksum(self) -> str:
        """Content-based checksum of the schema's field set."""
        return self.__record.checksum

    @property
    def fields(self) -> list[SchemaFieldRecord]:
        """Field definitions belonging to this schema."""
        return self.__fields

    @property
    def name(self) -> typing.Optional[str]:
        """Informational label for the schema (e.g. ``"sensor_msgs/Imu"``). Not part of identity; may be ``None``."""
        return self.__record.name

    @property
    def record(self) -> TopicSchemaRecord:
        """Underlying schema record."""
        return self.__record

    @property
    def schema_id(self) -> str:
        """Unique identifier for this schema."""
        return self.__record.schema_id
