# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

from .specification import QuerySpecification


class QueryTarget(str, enum.Enum):
    """
    The type of resource a specific query is requesting.
    """

    Collections = "collections"
    Datasets = "datasets"
    Files = "files"
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


class QueryScheme(str, enum.Enum):
    """
    A specific query format/schema which can be used in combination with some context JSON to provide all information
    required to execute a query.
    """

    QuerySpecV1 = "query_spec_v1"
    """
    The initial variant of roboto.query.QuerySpecification which powered search since mid 2023.
    """


class QueryContext(pydantic.BaseModel):
    """
    Context for a query
    """

    query_scheme: QueryScheme
    query: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class QueryStorageScheme(str, enum.Enum):
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
    org_id: str = pydantic.Field(
        description="The org on behalf of whom a query was run."
    )
    query_id: str = pydantic.Field(
        description="Unique identifier for an individual query."
    )
    query_ctx: QueryContext = pydantic.Field(
        description="The actual query being run and resolved."
    )
    result_count: int = pydantic.Field(
        description="The number of records matched by this query. Defaults to 0 for incomplete queries.",
        default=0,
    )
    status: QueryStatus = pydantic.Field(
        description="The query lifecycle status of this query."
    )
    submitted: datetime.datetime = pydantic.Field(
        description="The time at which this query was first created."
    )
    submitted_by: str = pydantic.Field(description="The user who scheduled this query.")
    target: QueryTarget = pydantic.Field(
        description="The type of data being requested, e.g. 'Datasets' or 'Topics'."
    )


class SubmitStructuredQueryRequest(pydantic.BaseModel):
    """
    Request payload to submit a structured query
    """

    query: QuerySpecification = pydantic.Field(
        description="The conditions, sorting behavior, and limit of this query."
    )
    target: QueryTarget = pydantic.Field(
        description="The type of data being requested, e.g. 'Datasets' or 'Topics'."
    )


class SubmitRoboqlQueryRequest(pydantic.BaseModel):
    """
    Request payload to submit a RoboQL query
    """

    query: typing.Optional[str] = pydantic.Field(
        description="The conditions, sorting behavior, and limit of this query."
    )
    target: QueryTarget = pydantic.Field(
        description="The type of data being requested, e.g. 'Datasets' or 'Topics'."
    )


class SubmitTermQueryRequest(pydantic.BaseModel):
    """
    Request payload to submit a simple term query
    """

    term: str = pydantic.Field(
        default="",
        description="A string search term which this query will attempt to match across any appropriate fields.",
    )
    target: QueryTarget = pydantic.Field(
        description="The type of data being requested, e.g. 'Datasets' or 'Topics'."
    )
