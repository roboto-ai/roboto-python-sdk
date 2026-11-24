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
from ...http.response import PaginatedList
from ...query import ConditionType


class AggregationPeriod(StrEnum):
    """Length of the calendar periods a metric aggregation groups data points into.

    Each period starts at midnight in ``AggregateMetricsRequest.time_zone``, and each week starts on
    ``AggregateMetricsRequest.week_start``.
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


class DayOfWeek(StrEnum):
    """Day of the week, such as the day an aggregation's weeks start on (``AggregateMetricsRequest.week_start``)."""

    Monday = "monday"
    Tuesday = "tuesday"
    Wednesday = "wednesday"
    Thursday = "thursday"
    Friday = "friday"
    Saturday = "saturday"
    Sunday = "sunday"


class NumericAggregation(StrEnum):
    """Function a metric aggregation applies to the values of the data points in each bucket."""

    Sum = "sum"
    """Sum of the values in the bucket."""

    Mean = "mean"
    """Arithmetic mean of the values in the bucket."""

    Max = "max"
    """Largest value in the bucket."""

    Min = "min"
    """Smallest value in the bucket."""

    Count = "count"
    """Number of data points in the bucket."""


class MetricTimeFilter(StrEnum):
    """Session time that places a metric data point in a query or aggregation window: the start or the end."""

    StartTime = "start_time"
    """The session's start time, as ``MetricRecord.session_start_time_ns`` gives it."""

    EndTime = "end_time"
    """The session's end time, as ``MetricRecord.session_end_time_ns`` gives it."""


class MetricDefinitionRecord(pydantic.BaseModel):
    """Data record of a metric definition, as the Roboto API returns it.

    A metric definition is a named numeric quantity that an organization records for its sessions, such as peak CPU
    usage, with an optional unit and description. ``MetricDefinition`` wraps this record with methods that act on the
    definition.
    """

    org_id: str
    """ID of the organization that owns the metric definition."""

    metric_id: str
    """Unique ID of the metric definition, beginning with ``mt_``."""

    name: str
    """Name of the metric definition, unique within its organization."""

    description: typing.Optional[str] = None
    """Human-readable description of what the metric measures, or ``None`` if it has none."""

    unit: typing.Optional[str] = None
    """Unit of measure of every value recorded under the metric, such as ``"%"``, ``"ms"`` or ``"m/s"``.

    ``None`` means the metric is unitless. Roboto does not check the unit against any list of units.
    """

    created_by: str
    """Principal that created the metric definition, as ``<type>:<id>``, such as ``user:<user_id>``."""

    created: datetime.datetime
    """Time the metric definition was created."""

    modified_by: str
    """Principal that last modified the metric definition, in the same ``<type>:<id>`` form as ``created_by``."""

    modified: datetime.datetime
    """Time the metric definition was last modified."""


class MetricRecord(pydantic.BaseModel):
    """Data record of a metric data point, as the Roboto API returns it.

    A metric data point is one numeric value recorded for one session under a metric definition. A session holds at
    most one data point per metric definition, and publishing another value replaces it. ``Metric`` wraps this record
    and exposes it as ``Metric.record``.
    """

    org_id: str
    """ID of the organization that owns the data point."""

    metric_id: str
    """ID of the metric definition the data point is recorded under."""

    name: str
    """Name of the metric definition the data point is recorded under.

    Roboto copies it from the definition, so displaying the name beside the value needs no second request.
    """

    session_id: str
    """ID of the session the data point is recorded for."""

    min_timestamp_ns: typing.Optional[int] = None
    """Earliest time covered by the data point's session, in nanoseconds since the Unix epoch.

    It is the session's :py:attr:`~roboto.experimental.sessions.SessionRecord.min_timestamp_ns`, and ``None`` while
    none of the session's files supplies a time, such as before the session holds any file.
    """

    max_timestamp_ns: typing.Optional[int] = None
    """Latest time covered by the data point's session, in nanoseconds since the Unix epoch.

    It is the session's :py:attr:`~roboto.experimental.sessions.SessionRecord.max_timestamp_ns`, and ``None`` in the
    same cases as ``min_timestamp_ns``.
    """

    session_start_time_ns: typing.Optional[int] = None
    """Time at which ``MetricTimeFilter.StartTime`` places the data point, in nanoseconds since the Unix epoch.

    It is ``min_timestamp_ns``, or the time the session was created while the session has no start or end time. A
    query or aggregation window holds the data point when it holds this time, and an aggregation counts the data point
    in the period that holds this time. ``None`` only in a response from a version of Roboto older than this field.
    """

    session_end_time_ns: typing.Optional[int] = None
    """Time at which ``MetricTimeFilter.EndTime`` places the data point, in nanoseconds since the Unix epoch.

    It is ``max_timestamp_ns``, or the time the session was created while the session has no start or end time, and
    is used as ``session_start_time_ns`` is. ``None`` only in a response from a version of Roboto older than this
    field.
    """

    value: float
    """Numeric value of the data point."""

    unit: typing.Optional[str] = None
    """Unit of measure of ``value``, or ``None`` if the metric is unitless.

    Roboto copies it from the metric definition, as it does ``name``.
    """

    device_id: typing.Optional[str] = None
    """ID of the device that produced the data point, or ``None`` if it was published without one."""

    invocation_id: typing.Optional[str] = None
    """ID of the action invocation that published the data point, or ``None`` if no action published it."""

    group_key: typing.Optional[str] = None
    """Value of the ``QueryMetricsRequest.group_by`` field for this data point, as text whatever the field's type.

    ``None`` unless a query with ``group_by`` returned the data point, and ``None`` on a data point with no value for
    that field: one published without a device, or one whose session or device has no value for the custom field.
    ``NumericAggregateMetricRecord.group_key`` holds the same value for a bucket of an aggregation.
    """

    published_by: str
    """Principal that last published the data point, as ``<type>:<id>``, such as ``user:<user_id>``."""

    published: datetime.datetime
    """Time the data point was last published."""


class AggregateMetricRecord(pydantic.BaseModel):
    """Bucket of a metric aggregation: the data points of one calendar period, or of one period and one group value.

    A bucket holds one group value when the aggregation sets ``AggregateMetricsRequest.group_by``.
    ``NumericAggregateMetricRecord`` is the only kind of bucket Roboto returns.
    """

    metric_id: str
    """ID of the aggregated metric definition."""

    name: str
    """Name of the aggregated metric definition."""

    period: AggregationPeriod
    """Length of the calendar period the bucket covers."""

    start_time: int
    """Inclusive start of the bucket's period, in nanoseconds since the Unix epoch.

    It is midnight, in the request's ``AggregateMetricsRequest.time_zone``, on the period's first day.
    """

    end_time: int
    """Exclusive end of the bucket's period, in nanoseconds since the Unix epoch.

    It is midnight, in the request's ``AggregateMetricsRequest.time_zone``, on the next period's first day. A period
    in which that time zone's clocks change is longer or shorter by the size of the change, so a daily bucket can span
    23 or 25 hours.
    """

    total: int
    """Number of data points the bucket aggregates."""


class NumericAggregateMetricRecord(AggregateMetricRecord):
    """Data record of a bucket of a numeric metric aggregation, as ``Metric.aggregate`` returns it."""

    value: float
    """Result of ``aggregation`` over the values of the bucket's data points."""

    unit: typing.Optional[str] = None
    """Unit of measure of ``value``, or ``None`` if the metric is unitless.

    Roboto copies it from the metric definition, as it does ``AggregateMetricRecord.name``.
    """

    aggregation: NumericAggregation
    """Function applied to the values of the bucket's data points to produce ``value``."""

    group_key: typing.Optional[str] = None
    """Value of the ``AggregateMetricsRequest.group_by`` field that the bucket's data points share, as text.

    The value is rendered as text whatever the field's type. ``None`` on every bucket of an aggregation without
    ``group_by``, and on the bucket of the data points with no value for that field: data points published without a
    device, or whose session or device has no value for the custom field.
    """


class NumericAggregateMetricsResponse(pydantic.BaseModel):
    """Response body of ``Metric.aggregate``."""

    aggregation: NumericAggregation
    """Function the aggregation applied to each bucket."""

    records: list[NumericAggregateMetricRecord]
    """Buckets of the aggregation, sorted by ``AggregateMetricRecord.start_time``, earliest first."""

    total_groups: typing.Optional[int] = None
    """Number of distinct named values of ``AggregateMetricsRequest.group_by`` with data in the returned periods.

    Data points with no value for the field count as no group. When ``AggregateMetricsRequest.widen_to_whole_periods``
    is true, the periods can reach past the requested window, so this counts a value whose data points all fall
    outside the requested window. ``None`` on an aggregation without ``group_by``.
    """

    groups_truncated: bool = False
    """Whether ``total_groups`` exceeds ``MAX_METRIC_GROUPS``, so that only some named groups came back.

    The groups that come back are those with the most data points in the requested window, together with the group of
    data points that have no value for the field. ``MAX_METRIC_GROUPS`` describes how groups are ranked.
    """


# The limit sits on the str type, not on each field, so a field that also accepts NotSet applies it only to strings.
MetricUnit = typing.Annotated[str, pydantic.Field(max_length=63)]
"""Unit of measure of a metric definition, as a request sets it: at most 63 characters.

The limit is the one the OpenTelemetry Metrics API specification sets on the unit of a metric instrument.
https://opentelemetry.io/docs/specs/otel/metrics/api/#instrument-unit
"""


class CreateMetricDefinitionRequest(pydantic.BaseModel):
    """Request body for ``MetricDefinition.create``.

    Building it raises ``pydantic.ValidationError`` when ``unit`` is longer than 63 characters.
    """

    name: str
    """Name of the metric definition, unique within its organization.

    A name may use only ASCII letters, digits, ``-``, ``.``, ``_`` and ``~``; any other character raises
    ``RobotoIllegalArgumentException``.
    """

    description: typing.Optional[str] = None
    """Human-readable description of what the metric measures."""

    unit: typing.Optional[MetricUnit] = None
    """Unit of measure of values recorded under the metric, such as ``"%"`` or ``"ms"``, at most 63 characters.

    ``None`` makes the metric unitless.
    """


class UpdateMetricDefinitionRequest(pydantic.BaseModel):
    """Request body for ``MetricDefinition.update``.

    A field left unset (:py:const:`~roboto.sentinels.NotSet`) is unchanged. Building it raises
    ``pydantic.ValidationError`` when ``unit`` is longer than 63 characters.
    """

    description: typing.Optional[typing.Union[NotSetType, str]] = NotSet
    """Human-readable description of what the metric measures. ``None`` clears it."""

    unit: typing.Optional[typing.Union[NotSetType, MetricUnit]] = NotSet
    """Unit of measure of values recorded under the metric, at most 63 characters.

    ``None`` makes the metric unitless.
    """

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


# ---------------------------------------------------------------------------
# Publish requests
# ---------------------------------------------------------------------------


class MetricEntry(pydantic.BaseModel):
    """Metric name and value of one data point to publish.

    Carried in ``PublishMetricsRequest.metrics``. Pass a list of them to ``Metric.publish``.
    """

    name: str
    """Name of the metric definition to record the value under.

    It takes the characters ``CreateMetricDefinitionRequest.name`` allows; ``Metric.publish`` refuses an entry whose
    name uses any other. Roboto creates a definition with this name, and no description or unit, when the
    organization has none.
    """

    value: float
    """Numeric value to record."""


class PublishMetricsRequest(pydantic.BaseModel):
    """Request body for ``Metric.publish``.

    :py:meth:`~roboto.experimental.sessions.Session.publish_metrics` sends it through ``Metric.publish``.
    """

    session_id: str
    """ID of the session to record every data point for."""

    device_id: typing.Union[NotSetType, typing.Optional[str]] = NotSet
    """ID of the device that produced the data points, or ``None`` to record them without a device.

    Left unset (:py:const:`~roboto.sentinels.NotSet`), Roboto records them under the one device attached to the
    session; a session with no attached device, or more than one, raises ``RobotoInvalidRequestException``.
    """

    metrics: list[MetricEntry]
    """Names and values of the data points to record."""

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)


# ---------------------------------------------------------------------------
# Query and aggregation requests
# ---------------------------------------------------------------------------

MAX_METRIC_GROUPS: int = 100
"""Maximum number of named groups a grouped metric query or aggregation returns.

A query or aggregation with ``group_by`` keeps the named values with the most data points in the requested window,
ties broken alphabetically by value, and leaves out every data point of the others. The group of data points with no
value for the field is never left out and does not count toward the limit. The ranking does not depend on the
aggregation, the period, or which page of a query is read, so the same window always keeps the same groups.
Responses report the full count in ``total_groups`` and whether any group was left out in ``groups_truncated``.
"""

MAX_METRIC_LIST_RESULTS: int = 10_000
"""Maximum number of metric data points in one page of a query, or in one listing of a session's metrics.

``Metric.query`` requests pages of this size by default and fetches every page, so it yields any number of data
points; set ``QueryMetricsRequest.max_results`` for smaller pages. ``Metric.get_by_session`` fetches one listing, so
it returns at most this many data points; read a session with more in parts by narrowing the listing with its
``name_prefix`` and ``exclude_name_prefix`` arguments.
"""


class MetricQueryPage(PaginatedList[MetricRecord]):
    """Response body of ``Metric.query``: one page of metric data points.

    Every page of one query carries the same ``total_groups`` and ``groups_truncated``.
    """

    total_groups: typing.Optional[int] = None
    """Number of distinct named values of ``QueryMetricsRequest.group_by`` with data in the queried window.

    Data points with no value for the field count as no group. ``None`` on a query without ``group_by``.
    """

    groups_truncated: bool = False
    """Whether ``total_groups`` exceeds ``MAX_METRIC_GROUPS``, so that some groups' data points were left out.

    Every page leaves out the data points of the same groups: the named values with the fewest data points in the
    queried window.
    """


class QueryMetricsRequest(pydantic.BaseModel):
    """Request body for ``Metric.query``.

    Exactly one of ``name`` and ``names`` selects the metrics to read. Building it raises ``pydantic.ValidationError``
    when:

    - both ``name`` and ``names`` are set, or neither is;
    - ``names`` is empty or repeats a name;
    - ``max_results`` is not from 1 to 10,000.
    """

    name: typing.Optional[str] = None
    """Name of the metric definition to read, or ``None`` when ``names`` selects the metrics instead."""

    names: typing.Optional[list[str]] = None
    """Experimental, and may change or be removed without notice.

    Names of the metric definitions to read together as one paginated result. Each returned ``MetricRecord`` carries
    its own ``name`` and ``metric_id``, which tell the data points of different metrics apart. A list of one name
    reads and pages as ``name`` does. No SDK method sets it.

    Replay a page token only with the list of names it was issued under. A token issued under ``name`` or a one-name
    list raises ``RobotoInvalidRequestException`` when replayed with two or more names, and a token issued under two
    or more names raises it when replayed with one.
    """

    time_filter: MetricTimeFilter = MetricTimeFilter.EndTime
    """Session time that places each data point in the query window: its start or its end."""

    start_time_ns: typing.Optional[int] = None
    """Inclusive start of the query window, in nanoseconds since the Unix epoch. ``None`` starts at the epoch.

    ``Metric.query`` builds it from its ``start_time`` argument with :py:func:`~roboto.time.to_epoch_nanoseconds`.
    """

    end_time_ns: typing.Optional[int] = None
    """Exclusive end of the query window, in nanoseconds since the Unix epoch. ``None`` ends at the time of the request.

    ``Metric.query`` builds it from its ``end_time`` argument the same way.
    """

    max_results: int = pydantic.Field(default=MAX_METRIC_LIST_RESULTS, le=MAX_METRIC_LIST_RESULTS, gt=0)
    """Maximum number of data points per page, from 1 to 10,000 (``MAX_METRIC_LIST_RESULTS``).

    A page holds fewer, with a page token for the rest, when this many data points would exceed the size limit of one
    API response.
    """

    sort_by: typing.Optional[str] = None
    """Field to order data points by. ``None`` orders them by ``time``.

    One of ``time`` (the session time ``time_filter`` selects), ``value``, ``published``, ``device_id``,
    ``session_id``, ``invocation_id``, or ``group_key`` (the value of ``group_by``, carried in
    ``MetricRecord.group_key``, and accepted only when ``group_by`` is set). Any other field, or ``group_key`` without
    ``group_by``, raises ``RobotoInvalidRequestException``. Ties are broken by ``session_id``, then, when ``names``
    lists several metrics, by ``metric_id``. Data points with no ``device_id``, ``invocation_id`` or group key sort
    after every other value, or before every other value when ``descending`` is true.
    """

    descending: bool = False
    """Whether to order data points from the largest ``sort_by`` value to the smallest.

    With the default ``sort_by``, the most recent data points come first.
    """

    include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """IDs of the devices whose data points to read.

    ``None`` reads only data points published without a device. Left unset (:py:const:`~roboto.sentinels.NotSet`),
    the device does not filter the query.
    """

    include_session_ids: typing.Union[list[str], NotSetType] = NotSet
    """IDs of the sessions whose data points to read.

    Left unset (:py:const:`~roboto.sentinels.NotSet`), the session does not filter the query. ``None`` is not
    accepted, since every data point belongs to a session.
    """

    include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """IDs of the action invocations whose data points to read.

    ``None`` reads only data points no action published. Left unset (:py:const:`~roboto.sentinels.NotSet`), the
    invocation does not filter the query.
    """

    condition: typing.Optional[ConditionType] = None
    """Condition, or nested group of conditions, narrowing which data points are returned.

    Every field must be prefixed with the resource it filters on, singular or plural; a bare field name such as
    ``name`` is rejected. The accepted fields are:

    - ``session.<field>``: ``session_id`` (alias ``id``), ``name``, ``min_timestamp_ns`` (alias ``start_time``),
      ``max_timestamp_ns`` (alias ``end_time``), ``duration``, ``created``, ``created_by``, ``modified``,
      ``modified_by``, ``tags``. The two timestamp bounds accept any value
      :py:func:`~roboto.time.to_epoch_nanoseconds` accepts; ``duration`` takes an integer number of nanoseconds.
    - ``device.<field>``: ``device_id`` (alias ``id``), ``tags``, ``created``, ``created_by``, ``modified``,
      ``modified_by``, ``metadata`` (including dotted paths beneath it). These read the device that produced the data
      point, not the devices attached to its session.
    - ``session.custom.<name>``, ``device.custom.<name>`` and ``collection.custom.<name>``: a custom field in the
      :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state.
    - ``collection.collection_id`` (alias ``collection.id``): the data point's session belongs to that collection.
      ``Equals`` and ``NotEquals`` only.

    A session belongs to any number of collections, so a data point matches a ``collection.*`` condition when its
    session belongs to at least one collection that satisfies it. A negated comparator (``NotEquals``,
    ``NotContains``, ``NotLike``) matches when the session belongs to no collection that satisfies the positive form,
    so a session in no collection matches every negated collection condition. ``IsNull`` and ``NotExists`` likewise
    match when no collection the session belongs to has a value for the field.

    A data point published without a device matches a ``device.*`` condition only under ``IsNull`` and
    ``NotExists``. Every other comparator, ``NotEquals``, ``NotContains`` and ``NotLike`` included, compares what the
    device's field holds, so a data point with no device, or whose device has no value for the field, does not match.
    Write ``device.<field> NotEquals x OR device.<field> IsNull`` to match both.

    Any other field, a comparator the field's type does not accept, a value the field cannot convert, or a
    :py:attr:`~roboto.query.ConditionOperator.Not` group raises ``RobotoIllegalArgumentException``.
    """

    group_by: typing.Optional[str] = None
    """Field whose value each returned data point carries in ``MetricRecord.group_key``.

    ``None`` leaves ``MetricRecord.group_key`` ``None`` on every data point. Unlike
    ``AggregateMetricsRequest.group_by``, this adds no data points: a query already returns one data point per session
    and metric, and this sets each one's ``group_key`` to the field's value, so a caller can separate the data points
    into one series per value without looking the field up itself.

    Accepts ``device.device_id`` and String, Enum, or Boolean custom fields of sessions and devices
    (``session.custom.<name>``, ``device.custom.<name>``). Any other field ``condition`` accepts raises
    ``RobotoIllegalArgumentException``. A data point with no value for the field is still returned, with a ``None``
    ``group_key``.

    At most ``MAX_METRIC_GROUPS`` named values are kept across every page: those with the most data points in the
    queried window. The data points of the others are left out. Each ``MetricQueryPage`` reports the full count in
    ``MetricQueryPage.total_groups`` and whether any value was left out in ``MetricQueryPage.groups_truncated``.
    """

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.model_validator(mode="after")
    def _validate_name_or_names(self) -> "QueryMetricsRequest":
        if (self.name is None) == (self.names is None):
            raise ValueError("Exactly one of 'name' and 'names' must be set.")
        if self.names is None:
            return self
        if len(self.names) == 0:
            raise ValueError("'names' must list at least one metric name.")
        if len(set(self.names)) != len(self.names):
            raise ValueError("'names' must not repeat a metric name.")
        return self


class AggregateMetricsRequest(pydantic.BaseModel):
    """Request body for ``Metric.aggregate``."""

    name: str
    """Name of the metric definition to aggregate."""

    period: AggregationPeriod
    """Length of the calendar periods to group data points into."""

    aggregation: NumericAggregation
    """Function to apply to the values of the data points in each bucket."""

    time_filter: MetricTimeFilter = MetricTimeFilter.EndTime
    """Session time that places each data point in the window and in a period: its start or its end."""

    start_time_ns: int
    """Inclusive start of the aggregation window, in nanoseconds since the Unix epoch.

    ``Metric.aggregate`` builds it from its ``start_time`` argument with :py:func:`~roboto.time.to_epoch_nanoseconds`.
    """

    end_time_ns: int
    """Exclusive end of the aggregation window, in nanoseconds since the Unix epoch.

    ``Metric.aggregate`` builds it from its ``end_time`` argument the same way.
    """

    include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """IDs of the devices whose data points to aggregate.

    ``None`` aggregates only data points published without a device. Left unset
    (:py:const:`~roboto.sentinels.NotSet`), the device does not filter the aggregation.
    """

    include_session_ids: typing.Union[list[str], NotSetType] = NotSet
    """IDs of the sessions whose data points to aggregate.

    Left unset (:py:const:`~roboto.sentinels.NotSet`), the session does not filter the aggregation. ``None`` is not
    accepted, since every data point belongs to a session.
    """

    include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """IDs of the action invocations whose data points to aggregate.

    ``None`` aggregates only data points no action published. Left unset (:py:const:`~roboto.sentinels.NotSet`), the
    invocation does not filter the aggregation.
    """

    condition: typing.Optional[ConditionType] = None
    """Condition, or nested group of conditions, narrowing which data points are aggregated.

    It filters data points before they are aggregated, so it changes each bucket's ``value`` and ``total``. A period
    whose data points are all filtered out has no bucket, so a filtered aggregation can return fewer buckets than an
    unfiltered one over the same window. ``QueryMetricsRequest.condition`` describes the accepted fields and how a
    data point published without a device matches.
    """

    group_by: typing.Optional[str] = None
    """Field to split each period's bucket by, giving one bucket per period and distinct value of the field.

    ``None`` aggregates every matching data point of a period into one bucket. Each bucket carries its value in
    ``NumericAggregateMetricRecord.group_key``. Accepts ``device.device_id`` and String, Enum, or Boolean custom
    fields of sessions and devices (``session.custom.<name>``, ``device.custom.<name>``). Any other field
    ``condition`` accepts raises ``RobotoIllegalArgumentException``, since a field must hold one value per data point,
    and few values overall, to form a series. Data points with no value for the field are aggregated into a bucket
    with a ``None`` ``group_key`` rather than dropped. At most ``MAX_METRIC_GROUPS`` named values come back, those
    with the most data points in the requested window, plus that ``None`` group; the response reports the full count
    in ``NumericAggregateMetricsResponse.total_groups``.
    """

    widen_to_whole_periods: bool = True
    """Whether to widen the window to whole periods.

    When true, Roboto moves ``start_time_ns`` back to the start of its period and ``end_time_ns`` forward to the end of
    its period, so the first and last buckets aggregate every data point of their period, including those of sessions
    outside the requested window. When false, a bucket aggregates only the data points inside [``start_time_ns``,
    ``end_time_ns``), the same data points a ``QueryMetricsRequest`` with the same window, ``time_filter`` and filters
    returns, so the first and last buckets can hold part of their period. Either way, each bucket's
    ``AggregateMetricRecord.start_time`` and ``AggregateMetricRecord.end_time`` are the bounds of its whole period.
    ``Metric.aggregate`` leaves it true.
    """

    time_zone: str = "UTC"
    """IANA name of the time zone in which each period starts at midnight, such as ``"America/Los_Angeles"``.

    Roboto cuts the periods, and the window when ``widen_to_whole_periods`` widens it, in this time zone, so a day on
    which its clocks change is longer or shorter than 24 hours. A name not in the IANA time zone database raises
    ``RobotoIllegalArgumentException``, as do ``CET``, ``EET``, ``MET`` and ``WET``, which Roboto would read as fixed
    UTC offsets without daylight saving time. Name such a zone by area and location instead, such as
    ``"Europe/Paris"`` for ``CET``.
    """

    week_start: DayOfWeek = DayOfWeek.Monday
    """Day each week starts on when ``period`` is ``AggregationPeriod.Weekly``. Other periods ignore it."""

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
