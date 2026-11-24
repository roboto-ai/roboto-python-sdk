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
    """Kind of resource a query searches."""

    Collections = "collections"
    """Collections (:py:class:`~roboto.domain.collections.Collection`)."""

    Datasets = "datasets"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`)."""

    Devices = "devices"
    """Devices (:py:class:`~roboto.domain.devices.Device`)."""

    Files = "files"
    """Files (:py:class:`~roboto.domain.files.File`)."""

    Sessions = "sessions"
    """Sessions (:py:class:`~roboto.experimental.sessions.Session`)."""

    Topics = "topics"
    """Topics (:py:class:`~roboto.domain.topics.Topic`)."""

    TopicMessagePaths = "topic_message_paths"
    """Message paths of topics (:py:class:`~roboto.domain.topics.MessagePath`)."""

    Events = "events"
    """Events (:py:class:`~roboto.domain.events.Event`)."""


class QueryStatus(enum.Enum):
    """Status of a query: whether its results are ready to fetch.

    Fetching the results of a query in any status but ``ResultsAvailable`` raises ``RobotoNotReadyException``.
    """

    Failed = "failed"
    """Unused. Roboto sets no query to this status.

    A query that cannot run instead raises an error when it is submitted or when its results are fetched.
    """

    ResultsAvailable = "results_available"
    """Results are ready to fetch.

    Roboto sets a query to this status when it is submitted, and runs the query each time a page of its results is
    fetched.
    """

    Scheduled = "scheduled"
    """Query is stored, and its results are not yet ready to fetch."""


class QueryContentMode(StrEnum):
    """Content mode of query results: whether each result includes its key-value metadata.

    Only dataset queries honor it. Queries of every other target return the same results in either mode.
    """

    RecordOnly = "record_only"
    """Results without their key-value metadata.

    Each dataset keeps its tags and custom fields. Leaving out metadata, which can be large, keeps responses small, so
    a page of results returns sooner and can hold more results. Use this mode unless you need each result's metadata
    at once.
    """

    RecordWithMeta = "record_with_meta"
    """Results with their key-value metadata."""


class QueryScheme(StrEnum):
    """Format of a stored query, as ``QueryContext.query_scheme`` holds it."""

    QuerySpecV1 = "query_spec_v1"
    """Query stored as a serialized :py:class:`~roboto.query.QuerySpecification`.

    Roboto stores every query this way.
    """


MAX_VALUE_COUNTS_LIMIT: int = 1_000
"""Maximum number of values one query's value counts list, and the number they list when the request sets no limit."""


@experimental
class ValueCountsSpec(pydantic.BaseModel):
    """Request to count how many of the records a query matches hold each value of one field.

    Submit it as ``SubmitStructuredQueryRequest.value_counts``, then read the ``ValueCounts`` with
    ``GET /v1/query/id/{query_id}/value-counts``. Only some callers may read value counts; any other caller gets
    ``RobotoFeatureNotAvailableException``.

    Supported for the ``Events``, ``Sessions``, ``Datasets``, ``Devices``, ``Collections``, and ``Files`` members of
    ``QueryTarget``. Every record the query's ``condition`` matches is counted: the query's ``sort_by``,
    ``sort_direction``, ``limit``, ``after`` and ``max_results`` do not apply.
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
    """One value of the counted field, and how many of the matched records hold it."""

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
    """Response body of ``GET /v1/query/id/{query_id}/value-counts``.

    Counts the values of the field the query's ``ValueCountsSpec`` names, over the records the query matches.
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
        """Whether the matched records hold more distinct values than ``values`` lists."""
        return self.distinct_values > len(self.values)


class QueryContext(pydantic.BaseModel):
    """Stored form of a query: the format it is stored in, and its contents.

    Carried in ``QueryRecord.query_ctx``.
    """

    query_scheme: QueryScheme
    """Format of ``query``."""

    query: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Contents of the query, in the format ``query_scheme`` names.

    Under ``QueryScheme.QuerySpecV1``, ``spec`` holds the serialized :py:class:`~roboto.query.QuerySpecification` and
    ``content_mode`` the ``QueryContentMode``. A query submitted as RoboQL also holds the RoboQL string under
    ``roboql``, and one submitted as a search term holds the term under ``term``.
    """


class QueryStorageScheme(StrEnum):
    """Format of a query's stored results, as ``QueryStorageContext.storage_scheme`` holds it.

    No Roboto API returns or accepts it.
    """

    S3ManifestV1 = "s3_manifest_v1"
    """Results stored as files, with a manifest file that lists the result parts and how to read them into rows."""


class QueryStorageContext(pydantic.BaseModel):
    """Location and format of a query's stored results.

    No SDK method or Roboto route uses this model.
    """

    storage_scheme: QueryStorageScheme
    """Format of the stored results."""

    storage_ctx: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Location of the stored results, in the form ``storage_scheme`` names."""


class QueryRecord(pydantic.BaseModel):
    """Data record of a query, as the Roboto API returns it.

    A query is a search of one kind of resource in an organization, stored so that its results can be fetched a page
    at a time. :py:meth:`~roboto.query.QueryClient.get_query_record` and the ``submit_*`` methods of
    :py:class:`~roboto.query.QueryClient` return it.
    """

    modified: datetime.datetime = pydantic.Field(
        description="The last time the database record for a query was modified."
    )
    """Time the query was last modified."""

    org_id: str = pydantic.Field(description="The org on behalf of whom a query was run.")
    """ID of the organization the query searches."""

    query_id: str = pydantic.Field(description="Unique identifier for an individual query.")
    """Unique ID of the query, beginning with ``q_``."""

    query_ctx: QueryContext = pydantic.Field(description="The actual query being run and resolved.")
    """Stored form of the query."""

    result_count: int = pydantic.Field(
        description="The number of records matched by this query. Defaults to 0 for incomplete queries.",
        default=0,
    )
    """Unused. Roboto always returns ``0``, since it does not count a query's results when it stores the query.

    ``GET /v1/query/id/{query_id}/count`` returns the number of results.
    """

    status: QueryStatus = pydantic.Field(description="The query lifecycle status of this query.")
    """Status of the query: whether its results are ready to fetch."""

    submitted: datetime.datetime = pydantic.Field(description="The time at which this query was first created.")
    """Time the query was submitted."""

    submitted_by: str = pydantic.Field(description="The user who scheduled this query.")
    """ID of the user who submitted the query."""

    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
    """Kind of resource the query searches."""


class QualifiedRoboqlQuery(pydantic.BaseModel):
    """Response body of ``POST /v1/query/convert/nlp-to-roboql``.

    Holds the RoboQL query Roboto's AI writes from a natural-language prompt, and the kind of resource it searches.
    """

    query: str = pydantic.Field(description="The conditions, sorting behavior, and limit of this query.")
    """RoboQL query: its conditions, and any sort order and limit."""

    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
    """Kind of resource the query searches."""


class SubmitStructuredQueryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.query.QueryClient.submit_structured`."""

    content_mode: QueryContentMode = pydantic.Field(
        default=QueryContentMode.RecordWithMeta, description="The content mode for query results."
    )
    """Whether each result includes its key-value metadata (``QueryContentMode``)."""

    query: QuerySpecification = pydantic.Field(description="The conditions, sorting behavior, and limit of this query.")
    """Condition, sort order, and maximum number of results of the query.

    When it sets no ``sort_by``, Roboto sorts the results by the target's default sort field, if the target has one.
    """

    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
    """Kind of resource the query searches."""
    value_counts: typing.Optional[ValueCountsSpec] = pydantic.Field(
        default=None,
        description=(
            "Experimental: this field may change or be removed without notice. A field whose values to count over "
            "this query's matching records. Read the counts with GET /v1/query/id/<query_id>/value-counts, which "
            "is enabled per caller and refuses others with RobotoFeatureNotAvailableException. Supported for the "
            "events, sessions, datasets, devices, collections, and files targets."
        ),
    )
    """Experimental, and may change or be removed without notice.

    Field whose values to count over the records the query matches, or ``None`` to count none. Read the counts with
    ``GET /v1/query/id/{query_id}/value-counts``. Only some callers may read them; any other caller gets
    ``RobotoFeatureNotAvailableException``. Supported for the ``Events``, ``Sessions``, ``Datasets``, ``Devices``,
    ``Collections``, and ``Files`` members of ``QueryTarget``.
    """


class SubmitRoboqlQueryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.query.QueryClient.submit_roboql`."""

    content_mode: QueryContentMode = pydantic.Field(
        default=QueryContentMode.RecordWithMeta, description="The content mode for query results."
    )
    """Whether each result includes its key-value metadata (``QueryContentMode``)."""

    query: typing.Optional[str] = pydantic.Field(
        description="The conditions, sorting behavior, and limit of this query."
    )
    """RoboQL query: its conditions, and any sort order and ``LIMIT`` on the total number of results.

    ``None`` matches every resource of ``target``. A string that is not valid RoboQL raises
    ``RobotoIllegalArgumentException``.
    """

    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
    """Kind of resource the query searches."""


class SubmitTermQueryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.query.QueryClient.submit_term`."""

    content_mode: QueryContentMode = pydantic.Field(
        default=QueryContentMode.RecordWithMeta, description="The content mode for query results."
    )
    """Whether each result includes its key-value metadata (``QueryContentMode``)."""

    term: str = pydantic.Field(
        default="",
        description="A string search term which this query will attempt to match across any appropriate fields.",
    )
    """Text to search for in the target's ID and text fields, such as a dataset's ID, name, description, and tags."""

    target: QueryTarget = pydantic.Field(description="The type of data being requested, e.g. 'Datasets' or 'Topics'.")
    """Kind of resource the query searches."""
