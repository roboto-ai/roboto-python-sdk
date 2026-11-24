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
    """A topic schema: the fields that make up a topic's messages, each with its path and data type.

    Within an organization, a checksum of its fields identifies a schema, so topics whose messages have identical
    fields share one schema. The schema's name, such as ``"sensor_msgs/Imu"``, is not part of that identity.

    Get a ``TopicSchema`` from ``TopicSchema.from_id``, or from ``Topic.get_schema`` for the schema of a given topic.
    """

    __record: TopicSchemaRecord
    __fields: list[SchemaFieldRecord]
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        schema_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "TopicSchema":
        """Fetch a topic schema and its fields by the schema's ID.

        Args:
            schema_id: Unique ID of the schema, beginning with ``ts_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No schema has this ID.

        Examples:
            >>> from roboto.domain.topics import TopicSchema
            >>> schema = TopicSchema.from_id("ts_12345")
            >>> print(schema.name, schema.checksum)
            >>> for field in schema.fields:
            ...     print(field.path_in_schema, field.data_type)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v2/topics/schema/id/{schema_id}",
        ).to_record(TopicSchemaRecord)
        fields = roboto_client.get(
            f"v2/topics/schema/id/{schema_id}/fields",
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
        """Checksum computed from the schema's fields; schemas with identical fields have the same checksum."""
        return self.__record.checksum

    @property
    def fields(self) -> list[SchemaFieldRecord]:
        """Fields of the schema, one per field path."""
        return self.__fields

    @property
    def name(self) -> typing.Optional[str]:
        """Informational name of the schema, such as ``"sensor_msgs/PointCloud2"``; not part of its identity.

        ``None`` if the schema has none. ``TopicSchemaRecord`` describes when Roboto replaces the name.
        """
        return self.__record.name

    @property
    def record(self) -> TopicSchemaRecord:
        """Record of the topic schema that this instance holds."""
        return self.__record

    @property
    def schema_id(self) -> str:
        """Unique ID of the schema.

        It begins with ``ts_``. See ``TopicSchemaRecord.schema_id``.
        """
        return self.__record.schema_id
