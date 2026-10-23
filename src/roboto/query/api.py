# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

from ..compat import StrEnum
from ..warnings import experimental
from .specification import QuerySpecification


class QueryTarget(StrEnum):
    """
    The type of resource a specific query is requesting.
    """

    Collections = "collections"
    Datasets = "datasets"
    Devices = "devices"
    Files = "files"
    Sessions = "sessions"
    Topics = "topics"
    TopicMessagePaths = "topic_message_paths"
    Events = "events"


class QueryStatus(enum.Enum):
    """
    The query lifecycle state of a given query.
    """

    Failed = "failed"
    """
    Indicates the query failed to execute.
    """

    ResultsAvailable = "results_available"
    """
    Indicates that query results are available for clients to retrieve.

    Results might be available immediately, such as in paginated database search, or once a
    (potentially expensive) calculation completes for more advanced search modalities.
    """

    Scheduled = "scheduled"
    """
    Indicates the query is scheduled for execution.
    """


class QueryContentMode(StrEnum):
    """
    Hint to query APIs on whether to return Roboto entities with custom metadata.

    In ``RecordOnly`` mode, Roboto entities are returned without custom metadata,
    ensuring a smaller and more predictable response size. Use this mode when you
    need lower query latency, larger result page sizes, or both.

    In ``RecordWithMeta`` mode, Roboto entities are returned with all available
    custom metadata. Use this mode if you need immediate access to metadata fields.

    Note: content mode support is initially available for dataset queries, and will
    be added incrementally for other entity types.
    """

    RecordOnly = "record_only"
    """Query results are returned with core Roboto data attributes only.

    Those attributes establish the identity and function of Roboto entities.
    """

    RecordWithMeta = "record_with_meta"
    """Query results are returned with all available entity attributes.

    This includes core Roboto data attributes as well as custom metadata.
    """


class QueryScheme(StrEnum):
    """
    A specific query format/schema which can be used in combination with some context JSON to provide all information
    required to execute a query.
    """

    QuerySpecV1 = "query_spec_v1"
    """
    The initial variant of roboto.query.QuerySpecification which powered search since mid 2023.
    """


MAX_VALUE_COUNTS_LIMIT: int = 1_000
"""The largest and the default :py:attr:`ValueCountsSpec.limit`: the most values one :py:class:`ValueCounts` lists."""


@experimental
class ValueCountsSpec(pydantic.BaseModel):
    """
    A request to count how many of the records a query matches hold each value of one field. Submit it as
    :py:attr:`SubmitStructuredQueryRequest.value_counts`, then read the :py:class:`ValueCounts` with
    ``GET /v1/query/id/<query_id>/value-counts``. The endpoint is enabled per caller; a caller it is not enabled for
    gets :py:exc:`~roboto.exceptions.RobotoFeatureNotAvailableException`.

    Supported for the ``events``, ``sessions``, ``datasets``, ``devices``, ``collections``, and ``files`` query
    targets. Every record the query's ``condition`` matches is counted: the query's ``sort_by``, ``sort_direction``,
    ``limit``, ``after`` and ``max_results`` do not apply.
    """

    field: str = pydantic.Field(
        min_length=1,
        description=(
            "The field whose values are counted: a field the query's target accepts as QuerySpecification.sort_by, "
            "under its name or one of its aliases, or custom.<name> for one of the organization's custom fields "
            "with status CustomFieldStatus.Ready."
        ),
    )
    limit: int = pydantic.Field(
        default=MAX_VALUE_COUNTS_LIMIT,
        ge=1,
        le=MAX_VALUE_COUNTS_LIMIT,
        description="The most values returned, most common first.",
    )
    time_field: typing.Optional[str] = pydantic.Field(
        default=None,
        description=(
            "A time field the query's target accepts as QuerySpecification.sort_by, such as start_time on sessions "
            "and events, or created on the other targets; a custom field is not accepted. Each value then carries "
            "the earliest and latest time among the records holding it."
        ),
    )


@experimental
class ValueCount(pydantic.BaseModel):
    """
    One value of the counted field, and how many of the matched records hold it.
    """

    value: typing.Any = pydantic.Field(
        description=(
            "The value, as JSON of the field's type: a string, number or boolean. An audit time (created, modified) "
            "or a custom timestamp field is an ISO 8601 string; a recorded time (start_time) is integer nanoseconds "
            "since the Unix epoch."
        )
    )
    count: int = pydantic.Field(description="How many of the matched records hold the value.")
    first_time: typing.Union[int, str, None] = pydantic.Field(
        default=None,
        description=(
            "The earliest time_field value among the records holding the value: integer nanoseconds for a recorded "
            "time such as start_time, an ISO 8601 string for an audit time such as created. Null when no time_field "
            "was named or none of those records has a time."
        ),
    )
    last_time: typing.Union[int, str, None] = pydantic.Field(
        default=None,
        description="The latest time_field value among the records holding the value, as first_time is.",
    )


@experimental
class ValueCounts(pydantic.BaseModel):
    """
    Response of ``GET /v1/query/id/<query_id>/value-counts``: the values of the field the query's
    :py:class:`ValueCountsSpec` names, over the records the query matches.
    """

    field: str = pydantic.Field(description="The counted field, as ValueCountsSpec.field spelled it.")
    matched: int = pydantic.Field(description="How many records the query matches.")
    without_value: int = pydantic.Field(description="How many of the matched records hold no value for the field.")
    distinct_values: int = pydantic.Field(
        description="How many distinct values the matched records hold, including values past the limit."
    )
    values: list[ValueCount] = pydantic.Field(
        description=(
            "Up to ValueCountsSpec.limit values, most common first; values with equal counts are in ascending order."
        )
    )

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def truncated(self) -> bool:
        """True when the matched records hold more distinct values than ``values`` lists."""
        return self.distinct_values > len(self.values)


class QueryContext(pydantic.BaseModel):
    """
    Context for a query
    """

    query_scheme: QueryScheme
    query: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class QueryStorageScheme(StrEnum):
    """
    A specific query result storage format/schema which can be used in combination with some context JSON to provide all
    information required to vend query results
    """

    S3ManifestV1 = "s3_manifest_v1"
    """
    Query results are in S3, and a manifest file enumerates the result parts and how to resolve them into rows.
    """


class QueryStorageContext(pydantic.BaseModel):
    """
    Context for query storage
    """

    storage_scheme: QueryStorageScheme
    storage_ctx: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class QueryRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of a query.
    """

    modified: datetime.datetime = pydantic.Field(
        description="The last time the database record for a query was modified."
    )
    org_id: str = pydantic.Field(description="The org on behalf of whom a query was run.")
    query_id: str = pydantic.Field(description="Unique identifier for an individual query.")
    query_ctx: QueryContext = pydantic.Field(description="The actual query being run and resolved.")
    result_count: int = pydantic.Field(
        description="The number of records matched by this query. Defaults to 0 for incomplete queries.",
        default=0,
    )
    status: QueryStatus = pydantic.Field(description="The query lifecycle status of this query.")
    submitted: datetime.datetime = pydantic.Field(description="The time at which this query was first created.")
    submitted_by: str = pydantic.Field(description="The user who scheduled this query.")
    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")


class QualifiedRoboqlQuery(pydantic.BaseModel):
    """
    A RoboQL query which has been qualified with a target.
    """

    query: str = pydantic.Field(description="The conditions, sorting behavior, and limit of this query.")
    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")


class SubmitStructuredQueryRequest(pydantic.BaseModel):
    """
    Request payload to submit a structured query
    """

    content_mode: QueryContentMode = pydantic.Field(
        default=QueryContentMode.RecordWithMeta, description="The content mode for query results."
    )
    query: QuerySpecification = pydantic.Field(description="The conditions, sorting behavior, and limit of this query.")
    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
    value_counts: typing.Optional[ValueCountsSpec] = pydantic.Field(
        default=None,
        description=(
            "Experimental: this field may change or be removed without notice. A field whose values to count over "
            "this query's matching records. Read the counts with GET /v1/query/id/<query_id>/value-counts, which "
            "is enabled per caller and refuses others with RobotoFeatureNotAvailableException. Supported for the "
            "events, sessions, datasets, devices, collections, and files targets."
        ),
    )


class SubmitRoboqlQueryRequest(pydantic.BaseModel):
    """
    Request payload to submit a RoboQL query
    """

    content_mode: QueryContentMode = pydantic.Field(
        default=QueryContentMode.RecordWithMeta, description="The content mode for query results."
    )
    query: typing.Optional[str] = pydantic.Field(
        description="The conditions, sorting behavior, and limit of this query."
    )
    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")


class SubmitTermQueryRequest(pydantic.BaseModel):
    """
    Request payload to submit a simple term query
    """

    content_mode: QueryContentMode = pydantic.Field(
        default=QueryContentMode.RecordWithMeta, description="The content mode for query results."
    )
    term: str = pydantic.Field(
        default="",
        description="A string search term which this query will attempt to match across any appropriate fields.",
    )
    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
