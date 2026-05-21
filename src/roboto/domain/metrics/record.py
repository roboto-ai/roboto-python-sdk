# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType

from ...compat import StrEnum


class AggregationPeriod(StrEnum):
    """
    Calendar bucket size used when grouping metric observations.

    All aggregation start/end times are based on UTC time.
    """

    Daily = "daily"
    """One bucket per calendar day."""

    Weekly = "weekly"
    """One bucket per calendar week."""

    Monthly = "monthly"
    """One bucket per calendar month."""

    Quarterly = "quarterly"
    """One bucket per calendar quarter (three months)."""

    Yearly = "yearly"
    """One bucket per calendar year."""


class NumericAggregation(StrEnum):
    """Aggregation function applied to numeric metric values within each period bucket."""

    Sum = "sum"
    """Sum of all values in the bucket."""

    Mean = "mean"
    """Arithmetic mean of all values in the bucket."""

    Max = "max"
    """Maximum value observed in the bucket."""

    Min = "min"
    """Minimum value observed in the bucket."""

    Count = "count"
    """Count of observations in the bucket."""


class MetricTimeFilter(StrEnum):
    StartTime = "start_time"
    EndTime = "end_time"


class MetricDefinitionRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a metric definition."""

    org_id: str
    """Organization that owns this metric definition."""

    metric_id: str
    """Unique identifier for this metric definition."""

    name: str
    """Unique name for this metric."""

    description: typing.Optional[str] = None
    """Human-readable description of what the metric measures and its units."""

    created_by: str
    """User or service account that created this metric definition."""

    created: datetime.datetime
    """Timestamp when this metric definition was created."""

    modified_by: str
    """User or service account that last modified this metric definition."""

    modified: datetime.datetime
    """Timestamp when this metric definition was last modified."""


class MetricRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a metric data point."""

    org_id: str
    """Organization that owns this metric data point."""

    metric_id: str
    """Identifier of the metric definition this data point belongs to."""

    name: str
    """Human-readable name of the metric definition this data point belongs to.
    Resolved server-side from the parent :py:class:`MetricDefinitionRecord` so
    callers do not need a second lookup to display the metric name alongside
    the value."""

    session_id: str
    """Session this metric is associated with."""

    min_timestamp_ns: typing.Optional[int] = None
    """Lower bound of the source session's aggregate timestamps, in Unix-epoch
    nanoseconds. ``None`` until the session has at least one file contribution.
    Mirrors :py:attr:`~roboto.domain.sessions.SessionRecord.min_timestamp_ns`."""

    max_timestamp_ns: typing.Optional[int] = None
    """Upper bound of the source session's aggregate timestamps, in Unix-epoch
    nanoseconds. ``None`` until the session has at least one file contribution.
    Mirrors :py:attr:`~roboto.domain.sessions.SessionRecord.max_timestamp_ns`."""

    value: float
    """Observed numeric value."""

    device_id: typing.Optional[str] = None
    """Device that produced the data."""

    invocation_id: typing.Optional[str] = None
    """Action invocation that produced this data point, if any."""

    published_by: str
    """User or service account that published this data point."""

    published: datetime.datetime
    """Timestamp when this data point was published to the platform."""


class AggregateMetricRecord(pydantic.BaseModel):
    metric_id: str
    """Identifier of the aggregated metric definition."""

    name: str
    """Name of the aggregated metric."""

    period: AggregationPeriod
    """Calendar bucket size used for this aggregation."""

    start_time: int
    """Inclusive start of this period bucket, in Unix-epoch nanoseconds (UTC)."""

    end_time: int
    """Exclusive end of this period bucket, in Unix-epoch nanoseconds (UTC)."""

    total: int
    """Number of raw observations that contributed to this bucket."""


class NumericAggregateMetricRecord(AggregateMetricRecord):
    """A wire-transmissible representation of one period bucket in a numeric metric aggregation."""

    value: float
    """Aggregated result for this bucket."""

    aggregation: NumericAggregation
    """Aggregation function that was applied to produce this record."""


class NumericAggregateMetricsResponse(pydantic.BaseModel):
    """Response payload for a numeric metric aggregation request."""

    aggregation: NumericAggregation
    """Aggregation function that was applied."""

    records: list[NumericAggregateMetricRecord]
    """Period buckets returned by the aggregation, sorted by start_time ascending."""


class CreateMetricDefinitionRequest(pydantic.BaseModel):
    """Request payload to create a metric definition."""

    name: str
    """Unique metric name."""

    description: typing.Optional[str] = None
    """Human-readable description of what the metric measures and its units."""


class UpdateMetricDefinitionRequest(pydantic.BaseModel):
    """Request payload to update a metric definition."""

    description: typing.Optional[typing.Union[NotSetType, str]] = NotSet
    """New description, ``None`` to clear, or :py:data:`~roboto.sentinels.NotSet` to leave unchanged."""

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


# ---------------------------------------------------------------------------
# Bulk insert requests
# ---------------------------------------------------------------------------


class MetricEntry(pydantic.BaseModel):
    """A single name+value pair within a bulk metric publish."""

    name: str
    """Name of the metric definition to record a value for. If the definition
    does not exist, it is auto-created."""

    value: float
    """Observed numeric value."""


class PublishMetricsRequest(pydantic.BaseModel):
    """Request payload to insert multiple metric data points in a single call."""

    session_id: str
    """Session all metrics in this batch will be attached to."""

    device_id: typing.Union[NotSetType, typing.Optional[str]] = NotSet
    """Device that produced the data. When absent
    (:py:data:`~roboto.sentinels.NotSet`), the server infers the device from
    the session's attached devices: the request succeeds if exactly one device
    is attached and is rejected otherwise. Pass an explicit device ID or
    :py:data:`None` to skip inference."""

    metrics: list[MetricEntry]
    """Metric data points to insert."""

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


class PublishMetricsError(pydantic.BaseModel):
    """One failed item from a bulk metric publish."""

    name: str
    """Name of the metric that failed to insert."""

    error: str
    """Human-readable description of why the insert failed."""


class PublishMetricsResponse(pydantic.BaseModel):
    """Server response from a bulk metric publish.

    May contain a mix of successes and per-item failures if some metric
    values are invalid.
    """

    succeeded: list[MetricRecord]
    failed: list[PublishMetricsError]


# ---------------------------------------------------------------------------
# Query and aggregation requests
# ---------------------------------------------------------------------------

MAX_METRIC_LIST_RESULTS: int = 10_000
"""Upper bound on the page size accepted by metric query and list calls.

:py:meth:`~roboto.domain.metrics.Metric.query` auto-paginates with this value
as the default page size, so total result-set size is unbounded. Callers can
request smaller pages by setting
:py:attr:`~roboto.domain.metrics.QueryMetricsRequest.max_results`.

:py:meth:`~roboto.domain.metrics.Metric.get_by_session` does **not** paginate
and is still capped at this many rows; sessions with more data points should
use the paginated :py:meth:`~roboto.domain.metrics.Metric.query` instead.
"""


class QueryMetricsRequest(pydantic.BaseModel):
    """Request payload to query raw metric data points."""

    name: str
    """Name of the metric to query."""

    time_filter: MetricTimeFilter = MetricTimeFilter.EndTime
    """Whether to filter by session start time or end time."""

    start_time_ns: typing.Optional[int] = None
    """Inclusive start of the query window, in Unix-epoch nanoseconds (UTC).
    Built by :py:meth:`~roboto.domain.metrics.Metric.query` from its ``start_time``
    parameter via :py:func:`~roboto.time.to_epoch_nanoseconds`. Defaults to
    ``None`` (the Unix epoch)."""

    end_time_ns: typing.Optional[int] = None
    """Exclusive end of the query window, in Unix-epoch nanoseconds (UTC).
    Built from :py:meth:`~roboto.domain.metrics.Metric.query`'s ``end_time``
    parameter the same way. Defaults to ``None`` (now)."""

    max_results: int = pydantic.Field(default=MAX_METRIC_LIST_RESULTS, le=MAX_METRIC_LIST_RESULTS, gt=0)
    """Maximum number of data points to return. Must be between 1 and :py:data:`MAX_METRIC_LIST_RESULTS` (10,000)."""

    include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """Filter to observations from specific device IDs, ``None`` for null device_id only."""

    include_session_ids: typing.Union[list[str], NotSetType] = NotSet
    """Filter to observations for specific session IDs. ``None`` is not a valid value:
    ``metrics.session_id`` is non-nullable, so there is no "null session" subset to filter on.
    Omit (leave as :py:data:`~roboto.sentinels.NotSet`) for no filter, or pass a list of IDs."""

    include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """Filter to observations from specific invocation IDs, ``None`` for null invocation_id only."""

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


class AggregateMetricsRequest(pydantic.BaseModel):
    """Request payload for a numeric metric aggregation."""

    name: str
    """Name of the metric to aggregate."""

    period: AggregationPeriod
    """Calendar bucket size to group observations by."""

    aggregation: NumericAggregation
    """Aggregation function to apply to the values in each bucket."""

    time_filter: MetricTimeFilter = MetricTimeFilter.EndTime
    """Whether to filter by session start time or end time."""

    start_time_ns: int
    """Inclusive start of the aggregation window, in Unix-epoch nanoseconds (UTC).
    Built by :py:meth:`~roboto.domain.metrics.Metric.aggregate` from its
    ``start_time`` parameter via :py:func:`~roboto.time.to_epoch_nanoseconds`."""

    end_time_ns: int
    """Exclusive end of the aggregation window, in Unix-epoch nanoseconds (UTC).
    Built from :py:meth:`~roboto.domain.metrics.Metric.aggregate`'s ``end_time``
    parameter the same way."""

    include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """Filter to observations from specific device IDs, ``None`` for null device_id only."""

    include_session_ids: typing.Union[list[str], NotSetType] = NotSet
    """Filter to observations for specific session IDs. ``None`` is not a valid value:
    ``metrics.session_id`` is non-nullable, so there is no "null session" subset to filter on.
    Omit (leave as :py:data:`~roboto.sentinels.NotSet`) for no filter, or pass a list of IDs."""

    include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """Filter to observations from specific invocation IDs, ``None`` for null invocation_id only."""

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
