# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import dataclasses
import datetime
import typing
import urllib.parse

from roboto.warnings import experimental

from ...http import RobotoClient
from ...logging import default_logger
from ...sentinels import NotSet, NotSetType, remove_not_set
from ...time import Time, to_epoch_nanoseconds
from .record import (
    MAX_METRIC_LIST_RESULTS,
    AggregateMetricsRequest,
    AggregationPeriod,
    CreateMetricDefinitionRequest,
    MetricDefinitionRecord,
    MetricEntry,
    MetricRecord,
    MetricTimeFilter,
    NumericAggregateMetricRecord,
    NumericAggregateMetricsResponse,
    NumericAggregation,
    PublishMetricsError,
    PublishMetricsRequest,
    PublishMetricsResponse,
    QueryMetricsRequest,
    UpdateMetricDefinitionRequest,
)

logger = default_logger()


@dataclasses.dataclass
class BulkPublishMetricsResult:
    """Result of a bulk metric publish — may contain both successes and per-item failures."""

    succeeded: list["Metric"]
    failed: list[PublishMetricsError]


@experimental
class MetricDefinition:
    """A named schema for a metric tracked across sessions and devices.

    Metric definitions are org-scoped schemas that describe a single measurable
    quantity. They act as the registry entry that all :py:class:`Metric` data
    points reference. Every metric definition has a unique ``name`` within an
    organization, and an optional human-readable ``description``.

    Metric definitions are created once per org and reused across many sessions.
    Use :py:meth:`create` to register a definition the first time, and
    :py:meth:`update` to change its description later.
    :py:meth:`for_org` lists all definitions that belong to an organization.

    Note:
        ``MetricDefinition`` instances should not be constructed directly.
        Always obtain them via :py:meth:`create`, :py:meth:`get`, or
        :py:meth:`for_org`.
    """

    __record: MetricDefinitionRecord
    __roboto_client: RobotoClient

    @classmethod
    def for_org(
        cls,
        owner_org_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["MetricDefinition", None, None]:
        """Yield all metric definitions belonging to an organization.

        Args:
            owner_org_id: Organization that owns the metric definitions to enumerate.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Yields:
            Each :py:class:`MetricDefinition` belonging to *owner_org_id*.

        Examples:
            >>> for definition in MetricDefinition.for_org("og_myorg"):
            ...     print(definition.name, "-", definition.description)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        next_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if next_token:
                query_params["page_token"] = next_token
            results = roboto_client.get(
                "v1/metrics/definitions/",
                owner_org_id=owner_org_id,
                query=query_params,
            ).to_paginated_list(MetricDefinitionRecord)
            for item in results.items:
                yield cls(item, roboto_client)
            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def create(
        cls,
        name: str,
        description: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "MetricDefinition":
        """Create a new metric definition in the caller's organization.

        Args:
            name: Unique metric name. Must contain only
                URL-safe characters (``A–Z``, ``a–z``, ``0–9``, ``-``, ``.``,
                ``_``, ``~``). Dots are conventional namespace separators, e.g.
                ``cpu.usage_pct``.
            description: Optional human-readable description of what the metric
                measures and its units.
            caller_org_id: Organization to create the definition in. Defaults
                to the authenticated caller's organization.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Returns:
            The newly created :py:class:`MetricDefinition`.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoConflictException`: A definition
                with this name already exists in the organization.

        Examples:
            >>> MetricDefinition.create(
            ...     name="cpu.usage_max",
            ...     description="Peak CPU usage percentage recorded during the session.",
            ... )
        """
        request = CreateMetricDefinitionRequest(name=name, description=description)
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post(
            "v1/metrics/definition/",
            data=request,
            idempotent=True,
            caller_org_id=caller_org_id,
        ).to_record(MetricDefinitionRecord)
        return cls(record, roboto_client)

    @classmethod
    def get(
        cls,
        name: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "MetricDefinition":
        """Retrieve an existing metric definition by name.

        Args:
            name: Name of the metric definition to retrieve. Must match exactly
                (case-sensitive) the name used when the definition was created.
            owner_org_id: Organization that owns the definition. Defaults to the
                authenticated caller's organization.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Returns:
            The :py:class:`MetricDefinition` with the given name.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoNotFoundException`: No definition
                with this name exists in the organization.

        Examples:
            >>> definition = MetricDefinition.get("cpu.usage_max")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/metrics/definition/{urllib.parse.quote(name, safe='')}",
            owner_org_id=owner_org_id,
        ).to_record(MetricDefinitionRecord)
        return cls(record, roboto_client)

    def __init__(
        self,
        record: MetricDefinitionRecord,
        roboto_client: typing.Optional[RobotoClient],
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def update(
        self,
        description: typing.Optional[typing.Union[NotSetType, str]] = NotSet,
    ) -> None:
        """Update the description of this definition.

        Args:
            description: New human-readable description, ``None`` to clear, or
                :py:data:`~roboto.sentinels.NotSet` to leave unchanged.

        Examples:
            >>> definition = MetricDefinition.get("cpu.usage_max")
            >>> definition.update(description="Peak CPU usage percentage recorded during the session.")
        """
        request = remove_not_set(UpdateMetricDefinitionRequest(description=description))
        self.__record = self.__roboto_client.put(
            f"v1/metrics/definition/{urllib.parse.quote(self.__record.name, safe='')}",
            data=request,
            owner_org_id=self.__record.org_id,
        ).to_record(MetricDefinitionRecord)

    def delete(self) -> None:
        """Delete this metric definition and all of its associated data points.

        Warning:
            This operation is irreversible. All :py:class:`Metric` data points
            recorded under this name will be permanently removed.

        Examples:
            >>> definition = MetricDefinition.get("cpu.usage_max")
            >>> definition.delete()
        """
        self.__roboto_client.delete(
            f"v1/metrics/definition/{urllib.parse.quote(self.name, safe='')}",
            owner_org_id=self.__record.org_id,
        )

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def metric_id(self) -> str:
        return self.__record.metric_id

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def description(self) -> typing.Optional[str]:
        return self.__record.description


@experimental
class Metric:
    """A summary value recorded for one session under a metric definition.

    Each ``Metric`` stores exactly **one** value per ``(metric, session)`` pair.
    Calling :py:meth:`publish` a second time for the same metric name and
    ``session_id`` replaces the previous value (upsert semantics). This makes
    metrics suitable for recording per-session summary statistics that are computed
    once (or updated as reprocessing happens), not for streaming time-series data.

    **Recording a metric** requires a :py:class:`MetricDefinition` to already
    exist under the given name. If the definition doesn't exist it will be
    created automatically.

    **Querying metrics** (:py:meth:`query`) returns the data points with a session
    timestamp in the given range.
    **Aggregating metrics** (:py:meth:`aggregate`) groups sessions by the calendar
    period their stored timestamp falls into and applies a summary function
    (sum, mean, max, min, or count) across the values in each period.

    Note:
        ``Metric`` instances should not be constructed directly. Obtain them
        via :py:meth:`publish` or :py:meth:`query`.
    """

    __record: MetricRecord
    __roboto_client: RobotoClient

    @classmethod
    def publish(
        cls,
        session_id: str,
        metrics: list[MetricEntry],
        device_id: typing.Union[NotSetType, typing.Optional[str]] = NotSet,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "BulkPublishMetricsResult":
        """Record metric values for a session in a single network call.

        Each ``(metric, session)`` pair is upserted: republishing under the same
        name and ``session_id`` replaces the previous value.

        If a metric definition does not already exist for a given name it is
        created automatically. When called from within a Roboto action,
        successfully inserted records are automatically linked to the action
        invocation.

        Args:
            session_id: Session to attach every published value to.
            metrics: Metric names and values to record.
            device_id: Device to associate with each published metric, or
                :py:data:`None` to associate no device with the metric.
                When omitted, Roboto attempts to infer a device from the session's
                attached devices. If the session has more than 1 device, device_id
                must be provided explicitly for each metric, or a
                :py:exc:`~roboto.exceptions.RobotoInvalidRequestException`:
                will be raised.
            caller_org_id: Organization context for the request. Defaults to
                the authenticated caller's organization.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Returns:
            A :py:class:`BulkPublishMetricsResult` with ``succeeded`` and
            ``failed`` lists. Items whose values are invalid, or whose names
            contain characters outside the URL-safe set, appear in ``failed``;
            the remaining items are recorded and returned in ``succeeded``.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoNotFoundException`: ``session_id``
                does not exist in the caller's organization.
            :py:exc:`~roboto.exceptions.RobotoInvalidRequestException`:
                ``device_id`` was omitted and the session has more than
                one attached devices.

        Examples:
            Publish with an explicit device:

            >>> from roboto.domain.metrics import Metric, MetricEntry
            >>> result = Metric.publish(
            ...     session_id="ss_abc123",
            ...     metrics=[MetricEntry(name="cpu.usage_max", value=87.2)],
            ...     device_id="dv_robot01",
            ... )
            >>> len(result.succeeded)
            1

            Let the server infer the device from the session's single attached device:

            >>> Metric.publish(
            ...     session_id="ss_abc123",
            ...     metrics=[MetricEntry(name="memory.peak_mb", value=2048.0)],
            ... )

            Record values that are not tied to any device:

            >>> Metric.publish(
            ...     session_id="ss_abc123",
            ...     metrics=[MetricEntry(name="run.duration_s", value=42.0)],
            ...     device_id=None,
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = PublishMetricsRequest(session_id=session_id, device_id=device_id, metrics=metrics)
        response = roboto_client.post(
            "v1/metrics",
            data=request,
            idempotent=True,
            caller_org_id=caller_org_id,
        ).to_record(PublishMetricsResponse)
        return BulkPublishMetricsResult(
            succeeded=[cls(r, roboto_client) for r in response.succeeded],
            failed=response.failed,
        )

    @classmethod
    def get_by_session(
        cls,
        session_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> list["Metric"]:
        """Return every metric published to ``session_id``.

        Args:
            session_id: Session whose metrics to fetch.
            owner_org_id: Organization that owns the session. Defaults to the
                authenticated caller's organization.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Returns:
            One :py:class:`Metric` per matching ``(metric_definition, session)``
            pair. May be empty. Order is unspecified.

        Examples:
            >>> from roboto.domain.metrics import Metric
            >>> for m in Metric.get_by_session("ss_abc123"):
            ...     print(m.metric_id, m.value)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        records = roboto_client.get(
            f"v1/metrics/session/{session_id}/",
            owner_org_id=owner_org_id,
        ).to_record_list(MetricRecord)
        return [cls(r, roboto_client) for r in records]

    @classmethod
    def query(
        cls,
        name: str,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        time_filter: MetricTimeFilter = MetricTimeFilter.EndTime,
        max_results: int = MAX_METRIC_LIST_RESULTS,
        include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        include_session_ids: typing.Union[list[str], NotSetType] = NotSet,
        include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Metric", None, None]:
        """Yield stored metric values whose session time falls in a range.

        The time window is matched against either ``session_min_timestamp_ns``
        or ``session_max_timestamp_ns`` on each metric row depending on
        ``time_filter``.

        This method auto-paginates: ``max_results`` is the **page size**
        (capped at :py:data:`MAX_METRIC_LIST_RESULTS`), not a total result
        cap. The generator continues fetching pages until the server reports
        no more data.

        Args:
            name: Name of the metric definition to query.
            start_time: Inclusive start of the query window. Accepts any
                :py:data:`~roboto.time.Time` value (int Unix-epoch
                nanoseconds, ``datetime``, ISO 8601 string, decimal seconds,
                etc.). Defaults to ``None`` (the Unix epoch).
            end_time: Exclusive end of the query window. Same input shape as
                ``start_time``. Defaults to ``None`` (now).
            time_filter: Whether to match the window against the session's
                start time or end time. Defaults to end time.
            max_results: Page size — number of data points per HTTP request.
                Total results are unbounded; pagination is automatic.
            include_device_ids: Restrict to specific device IDs, or ``None``
                to match only rows with no ``device_id``.
            include_session_ids: Restrict to specific session IDs.
            include_invocation_ids: Restrict to specific invocation IDs, or
                ``None`` to match only rows with no ``invocation_id``.
            owner_org_id: Organization that owns the metric data. Defaults to
                the authenticated caller's organization.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Yields:
            One :py:class:`Metric` per matching session, sorted by session
            time ascending with ``session_id`` as a deterministic tiebreaker.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoNotFoundException`: No metric
                with this ``name`` exists in the organization.

        Examples:
            Query a metric over a single day, passing ``datetime`` directly:

            >>> import datetime
            >>> from roboto.domain.metrics import Metric
            >>> for m in Metric.query(
            ...     name="cpu.usage_max",
            ...     start_time=datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc),
            ...     end_time=datetime.datetime(2026, 5, 2, tzinfo=datetime.timezone.utc),
            ... ):
            ...     print(m.session_id, m.value)

            Or with an ISO 8601 string:

            >>> all_records = list(
            ...     Metric.query(
            ...         name="cpu.usage_max",
            ...         start_time="2026-05-01T00:00:00Z",
            ...         end_time="2026-05-02T00:00:00Z",
            ...     )
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = QueryMetricsRequest(
            name=name,
            time_filter=time_filter,
            start_time_ns=to_epoch_nanoseconds(start_time) if start_time is not None else None,
            end_time_ns=to_epoch_nanoseconds(end_time) if end_time is not None else None,
            max_results=max_results,
            include_device_ids=include_device_ids,
            include_session_ids=include_session_ids,
            include_invocation_ids=include_invocation_ids,
        )
        next_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if next_token:
                query_params["page_token"] = next_token
            results = roboto_client.post(
                "v1/metrics/query",
                data=request,
                owner_org_id=owner_org_id,
                idempotent=True,
                query=query_params,
            ).to_paginated_list(MetricRecord)
            for record in results.items:
                yield cls(record, roboto_client)
            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def aggregate(
        cls,
        name: str,
        period: AggregationPeriod,
        aggregation: NumericAggregation,
        start_time: Time,
        end_time: Time,
        time_filter: MetricTimeFilter = MetricTimeFilter.EndTime,
        include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        include_session_ids: typing.Union[list[str], NotSetType] = NotSet,
        include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> list[NumericAggregateMetricRecord]:
        """Aggregate a metric across sessions, grouped by calendar period.

        Sessions whose ``session_min_timestamp_ns`` or
        ``session_max_timestamp_ns`` (selected via ``time_filter``) falls
        inside the [``start_time``, ``end_time``)
        window are grouped into UTC calendar buckets sized by ``period``, and
        the chosen :py:class:`~roboto.domain.metrics.NumericAggregation` is
        applied to the values in each bucket.

        The server snaps the requested window outward to whole-period
        boundaries to guarantee apples-to-apples comparisons.
        All time period buckets always cover their complete calendar period. For example,
            * a monthly aggregation requested between Jan 15 – Mar 15 will return aggregated data for all of
                January, February, and March.
            * a quarterly aggregation from Apr 27 - Dec 28 will return aggregated data for all of Q2, Q3, and Q4.

        Args:
            name: Name of the metric definition to aggregate.
            period: Calendar bucket size to group observations by.
            aggregation: Function to apply to values in each bucket.
            start_time: Inclusive start of the aggregation window. Accepts any
                :py:data:`~roboto.time.Time` value.
            end_time: Exclusive end of the aggregation window. Same input
                shape as ``start_time``.
            time_filter: Whether to match the window against each session's
                start time or end time. Defaults to end time.
            include_device_ids: Restrict to specific device IDs, or ``None``
                to match only rows with no ``device_id``.
            include_session_ids: Restrict to specific session IDs.
            include_invocation_ids: Restrict to specific invocation IDs, or
                ``None`` to match only rows with no ``invocation_id``.
            owner_org_id: Organization that owns the metric data. Defaults to
                the authenticated caller's organization.
            roboto_client: Roboto client to use. Defaults to the client
                configured in the environment.

        Returns:
            One :py:class:`NumericAggregateMetricRecord` per period bucket that
            contains at least one observation, sorted by ``start_time``
            ascending.

        Raises:
            :py:exc:`~roboto.exceptions.RobotoNotFoundException`: No metric
                with this ``name`` exists in the organization.

        Examples:
            Daily max CPU usage over a month, passing ``datetime`` directly:

            >>> import datetime
            >>> from roboto.domain.metrics import (
            ...     AggregationPeriod,
            ...     Metric,
            ...     NumericAggregation,
            ... )
            >>> for bucket in Metric.aggregate(
            ...     name="cpu.usage_max",
            ...     period=AggregationPeriod.Daily,
            ...     aggregation=NumericAggregation.Max,
            ...     start_time=datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc),
            ...     end_time=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
            ... ):
            ...     print(bucket.start_time, bucket.value)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = AggregateMetricsRequest(
            name=name,
            period=period,
            aggregation=aggregation,
            time_filter=time_filter,
            start_time_ns=to_epoch_nanoseconds(start_time),
            end_time_ns=to_epoch_nanoseconds(end_time),
            include_device_ids=include_device_ids,
            include_session_ids=include_session_ids,
            include_invocation_ids=include_invocation_ids,
        )
        return (
            roboto_client.post(
                "v1/metrics/aggregate",
                data=request,
                owner_org_id=owner_org_id,
                idempotent=True,
            )
            .to_record(NumericAggregateMetricsResponse)
            .records
        )

    def __init__(self, record: MetricRecord, roboto_client: typing.Optional[RobotoClient]):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def metric_id(self) -> str:
        return self.__record.metric_id

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def value(self) -> float:
        return self.__record.value

    @property
    def session_id(self) -> str:
        return self.__record.session_id

    @property
    def device_id(self) -> typing.Optional[str]:
        return self.__record.device_id

    @property
    def invocation_id(self) -> typing.Optional[str]:
        return self.__record.invocation_id

    @property
    def published(self) -> datetime.datetime:
        return self.__record.published

    @property
    def published_by(self) -> str:
        return self.__record.published_by

    @property
    def min_timestamp_ns(self) -> typing.Optional[int]:
        return self.__record.min_timestamp_ns

    @property
    def max_timestamp_ns(self) -> typing.Optional[int]:
        return self.__record.max_timestamp_ns

    @property
    def record(self) -> MetricRecord:
        return self.__record
