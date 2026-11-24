# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import typing
import urllib.parse

from roboto.warnings import experimental

from ...http import (
    BatchResponse,
    RobotoClient,
)
from ...logging import default_logger
from ...query import ConditionType
from ...sentinels import NotSet, NotSetType, remove_not_set
from ...time import Time, to_epoch_nanoseconds
from .record import (
    MAX_METRIC_GROUPS,
    MAX_METRIC_LIST_RESULTS,
    AggregateMetricsRequest,
    AggregationPeriod,
    CreateMetricDefinitionRequest,
    DayOfWeek,
    MetricDefinitionRecord,
    MetricEntry,
    MetricQueryPage,
    MetricRecord,
    MetricTimeFilter,
    NumericAggregateMetricRecord,
    NumericAggregateMetricsResponse,
    NumericAggregation,
    PublishMetricsRequest,
    QueryMetricsRequest,
    UpdateMetricDefinitionRequest,
)

logger = default_logger()


def _warn_if_groups_truncated(name: str, total_groups: typing.Optional[int], groups_truncated: bool) -> None:
    # Roboto sets groups_truncated only alongside total_groups, but they are separate response fields, so a
    # malformed response could carry the flag alone. Log nothing then, rather than `grouped into None named groups`.
    if groups_truncated and total_groups is not None:
        logger.warning(
            "Metric '%s' grouped into %s named groups; only the %d with the most sessions were returned "
            "(plus data points with no value). Narrow the read with a condition to see the others.",
            name,
            total_groups,
            MAX_METRIC_GROUPS,
        )


@experimental
class MetricDefinition:
    """A metric definition: a named numeric quantity that an organization records for its sessions.

    Peak CPU usage is one example. A metric definition has an optional unit and description, and its name is unique
    within its organization. Every
    ``Metric`` data point is recorded under one. Publishing a value under a name the organization has no definition
    for creates the definition, so ``create`` is needed only to set a description or unit from the start.

    Get a ``MetricDefinition`` from ``create``, ``get``, or ``for_org`` rather than building one directly.
    """

    __record: MetricDefinitionRecord
    __roboto_client: RobotoClient

    @classmethod
    def for_org(
        cls,
        owner_org_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["MetricDefinition", None, None]:
        """List the metric definitions an organization owns.

        Fetches the definitions a page at a time as you iterate.

        Args:
            owner_org_id: Organization whose metric definitions to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each metric definition the organization owns.

        Examples:
            >>> for definition in MetricDefinition.for_org("og_12345"):
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
        unit: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "MetricDefinition":
        """Create a metric definition.

        Args:
            name: Name of the metric definition, unique within its organization. It may use only ASCII letters, digits,
                ``-``, ``.``, ``_`` and ``~``. Dots conventionally separate namespaces, as in ``cpu.usage_pct``.
            description: Human-readable description of what the metric measures.
            unit: Unit of measure of every value recorded under the metric, such as ``"%"``, ``"ms"`` or ``"m/s"``, at
                most 63 characters. Roboto does not check it against any list of units. ``None`` makes the metric
                unitless.
            caller_org_id: Organization to create the metric definition in. Required when the caller belongs to more
                than one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new metric definition.

        Raises:
            RobotoConflictException: The organization already has a metric definition with this name.
            RobotoIllegalArgumentException: ``name`` uses a character other than those listed above.
            pydantic.ValidationError: ``unit`` is longer than 63 characters.

        Examples:
            >>> MetricDefinition.create(
            ...     name="cpu.usage_max",
            ...     description="Peak CPU usage recorded during the session.",
            ...     unit="%",
            ... )
        """
        request = CreateMetricDefinitionRequest(name=name, description=description, unit=unit)
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
        """Fetch a metric definition by name.

        Args:
            name: Name of the metric definition, matched exactly, case included.
            owner_org_id: Organization that owns the metric definition. Defaults to the organization the caller acts
                in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The metric definition with this name.

        Raises:
            RobotoNotFoundException: The organization has no metric definition with this name.

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
        unit: typing.Optional[typing.Union[NotSetType, str]] = NotSet,
    ) -> None:
        """Update the metric definition's description or unit.

        An argument left unset (:py:const:`~roboto.sentinels.NotSet`) is unchanged. This instance's record is updated
        from Roboto's response.

        Args:
            description: Human-readable description of what the metric measures. ``None`` clears it.
            unit: Unit of measure of every value recorded under the metric, at most 63 characters. ``None`` makes the
                metric unitless.

        Raises:
            RobotoNotFoundException: The metric definition no longer exists.
            pydantic.ValidationError: ``unit`` is longer than 63 characters.

        Examples:
            >>> definition = MetricDefinition.get("cpu.usage_max")
            >>> definition.update(description="Peak CPU usage recorded during the session.", unit="%")
        """
        request = remove_not_set(UpdateMetricDefinitionRequest(description=description, unit=unit))
        self.__record = self.__roboto_client.put(
            f"v1/metrics/definition/{urllib.parse.quote(self.__record.name, safe='')}",
            data=request,
            owner_org_id=self.__record.org_id,
        ).to_record(MetricDefinitionRecord)

    def delete(self) -> None:
        """Delete the metric definition and every data point recorded under it.

        Note:
            Deleting cannot be undone.

        Raises:
            RobotoNotFoundException: The metric definition no longer exists.

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
        """Unique ID of the metric definition, beginning with ``mt_``."""
        return self.__record.metric_id

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def description(self) -> typing.Optional[str]:
        return self.__record.description

    @property
    def unit(self) -> typing.Optional[str]:
        return self.__record.unit


@experimental
class Metric:
    """A metric data point: one numeric value recorded for one session under a metric definition.

    A session holds at most one data point per metric definition, and publishing another value replaces it. Metrics
    therefore suit per-session summary statistics, computed once or again when a session is reprocessed, and not
    streams of values over time.

    ``publish`` records values under the ``MetricDefinition`` of each name, ``query`` yields the data points whose
    session time falls in a time range, and ``aggregate`` groups data points by the calendar period their session time
    falls in and applies a sum, mean, maximum, minimum, or count to each period's values.

    Get a ``Metric`` from ``publish``, ``get_by_session``, or ``query`` rather than building one directly.
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
    ) -> BatchResponse[Metric]:
        """Publish metric values for a session in one request.

        Publishing a value under a name the session already has a value for replaces that value. When one call names a
        metric more than once, Roboto stores the last of those values it accepts, and every accepted entry naming that
        metric reports the stored value. Roboto creates a metric definition, with no description or unit, for any name
        the organization has none for. When an action invocation publishes, every value records the invocation's ID in
        ``MetricRecord.invocation_id``.

        Args:
            session_id: ID of the session to record every value for.
            metrics: Metric names and values to publish. An empty list returns an empty response without a request to
                Roboto.
            device_id: ID of the device to associate with each published value. ``None`` associates none. Left unset
                (:py:const:`~roboto.sentinels.NotSet`), Roboto uses the session's attached device, which succeeds only
                when exactly one device is attached.
            caller_org_id: Organization to act in. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            A :py:class:`~roboto.http.BatchResponse` with one element per entry, in request order, holding either the
            published ``Metric`` or the exception Roboto refused the entry with. Roboto refuses an entry on its own
            when its value is not finite or its name uses a character other than an ASCII letter, a digit, ``-``,
            ``.``, ``_`` or ``~``, and records the other entries. When recording fails for the whole request, Roboto
            stores none of the entries and reports that failure on every entry it had not already refused.

        Raises:
            RobotoNotFoundException: The organization has no session with this ID.
            RobotoInvalidRequestException: ``device_id`` is left unset and the session has no attached device, or
                more than one.

        Examples:
            Publish with an explicit device:

            >>> from roboto.domain.metrics import Metric, MetricEntry
            >>> published = Metric.publish(
            ...     session_id="se_12345",
            ...     metrics=[MetricEntry(name="cpu.usage_max", value=87.2)],
            ...     device_id="robot01",
            ... )
            >>> for metric in published.succeeded:
            ...     print(metric.name, metric.value)

            Let Roboto take the device from the session's one attached device:

            >>> Metric.publish(
            ...     session_id="se_12345",
            ...     metrics=[MetricEntry(name="memory.peak_mb", value=2048.0)],
            ... )

            Record values that are not tied to any device:

            >>> Metric.publish(
            ...     session_id="se_12345",
            ...     metrics=[MetricEntry(name="run.duration_s", value=42.0)],
            ...     device_id=None,
            ... )
        """
        if not metrics:
            return BatchResponse[Metric](responses=[])

        roboto_client = RobotoClient.defaulted(roboto_client)
        request = PublishMetricsRequest(session_id=session_id, device_id=device_id, metrics=metrics)
        published = roboto_client.post(
            "v1/metrics",
            data=request,
            idempotent=True,
            caller_org_id=caller_org_id,
        ).to_record(BatchResponse[MetricRecord])
        return published.map_data(lambda record: cls(record, roboto_client))

    @classmethod
    def get_by_session(
        cls,
        session_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        name_prefix: typing.Optional[str] = None,
        exclude_name_prefix: typing.Optional[str] = None,
    ) -> list["Metric"]:
        """List a session's metric data points, at most 10,000 of them (``MAX_METRIC_LIST_RESULTS``).

        For a session with more data points than that, the listing returns 10,000 and gives no sign that it left any
        out; which ones it leaves out is not specified. Narrow the listing with ``name_prefix`` or
        ``exclude_name_prefix`` to read such a session's data points in parts.

        Args:
            session_id: ID of the session whose data points to list.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            name_prefix: List only data points of metrics whose name starts with this text. ``None`` lists every
                metric.
            exclude_name_prefix: Leave out data points of metrics whose name starts with this text. ``None`` leaves
                out none.

        Returns:
            One ``Metric`` per metric definition that has a value for the session, in no specified order. Empty when
            the session has none.

        Examples:
            >>> from roboto.domain.metrics import Metric
            >>> for m in Metric.get_by_session("se_12345"):
            ...     print(m.name, m.value)
            >>> topic_stats = Metric.get_by_session("se_12345", name_prefix="topic_stats.")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        query: dict[str, typing.Any] = {}
        if name_prefix is not None:
            query["name_prefix"] = name_prefix
        if exclude_name_prefix is not None:
            query["exclude_name_prefix"] = exclude_name_prefix
        records = roboto_client.get(
            f"v1/metrics/session/{session_id}/",
            query=query or None,
        ).to_record_list(MetricRecord)
        return [cls(r, roboto_client) for r in records]

    @classmethod
    def prune_session(
        cls,
        session_id: str,
        name_prefix: str,
        published_before: datetime.datetime,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        """Delete a session's metrics under ``name_prefix`` that the calling action invocation did not write.

        Only code running in an action invocation may call this. It deletes the values under ``name_prefix`` that
        were published before ``published_before`` and were last written by another invocation or by none. An
        action that republishes a session's metrics calls it after publishing, with the time its run started, so
        that names the run no longer writes do not keep their old values, while a concurrent run's newer values
        survive.

        Args:
            session_id: ID of the session whose data points to delete.
            name_prefix: Delete only data points of metrics whose name starts with this text. Must not be empty.
            published_before: Delete only values published before this time. Must carry a UTC offset.
            caller_org_id: Organization to act in, which must own the session. Required when the caller belongs to
                more than one organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoUnauthorizedException: The caller is not running in an action invocation.
            RobotoNotFoundException: The organization has no session with this ID.
            RobotoInvalidRequestException: ``name_prefix`` is empty, or ``published_before`` has no UTC offset.

        Examples:
            >>> import datetime
            >>> from roboto.domain.metrics import Metric
            >>> started = datetime.datetime.now(datetime.timezone.utc)
            >>> Metric.publish(...)  # doctest: +SKIP
            >>> Metric.prune_session("se_12345", name_prefix="my_stats.", published_before=started)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        roboto_client.delete(
            f"v1/metrics/session/{session_id}/",
            caller_org_id=caller_org_id,
            query={"name_prefix": name_prefix, "published_before": published_before.isoformat()},
        )

    @classmethod
    def query(
        cls,
        name: str,
        start_time: typing.Optional[Time] = None,
        end_time: typing.Optional[Time] = None,
        time_filter: MetricTimeFilter = MetricTimeFilter.EndTime,
        max_results: int = MAX_METRIC_LIST_RESULTS,
        descending: bool = False,
        include_device_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        include_session_ids: typing.Union[list[str], NotSetType] = NotSet,
        include_invocation_ids: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        condition: typing.Optional[ConditionType] = None,
        group_by: typing.Optional[str] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        sort_by: typing.Optional[str] = None,
    ) -> collections.abc.Generator["Metric", None, None]:
        """Yield a metric's data points whose session time falls in a time range.

        ``time_filter`` selects whether the session's start time or its end time must fall in the range. A session
        with no start or end time counts as starting and ending when it was created, both for matching the range and
        for sorting by time; its data point has ``None`` for ``min_timestamp_ns`` and ``max_timestamp_ns``.

        Fetches one page of data points at a time as you iterate, until Roboto reports no more, so ``max_results``
        limits each page, not the number of data points yielded. The exceptions under ``Raises`` surface on the first
        iteration.

        Args:
            name: Name of the metric definition to read.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts. ``None`` starts at the Unix epoch.
            end_time: Exclusive end of the time range, in the same form. ``None`` ends at the time of the request.
            time_filter: Session time that places each data point in the time range: its start or its end.
            max_results: Maximum number of data points per page, from 1 to 10,000 (``MAX_METRIC_LIST_RESULTS``). A
                page holds fewer when that many data points would exceed the size limit of one API response.
            descending: Whether to yield the largest ``sort_by`` values first. With the default ``sort_by``, the most
                recent sessions come first. It orders the whole result, not each page. Data points with no
                ``device_id``, ``invocation_id`` or group key then sort before every other value.
            include_device_ids: IDs of the devices whose data points to read. ``None`` reads only data points
                published without a device. Left unset (:py:const:`~roboto.sentinels.NotSet`), the device does not
                filter the query.
            include_session_ids: IDs of the sessions whose data points to read. Left unset (``NotSet``), the session
                does not filter the query.
            include_invocation_ids: IDs of the action invocations whose data points to read. ``None`` reads only data
                points no action published. Left unset (``NotSet``), the invocation does not filter the query.
            condition: :py:class:`~roboto.query.Condition` or :py:class:`~roboto.query.ConditionGroup` that the data
                point's session, the device that produced it, or the session's collections must match.
                ``QueryMetricsRequest.condition`` lists the accepted fields, and says how a collection condition
                matches a session in several collections or in none.
            group_by: Field whose value each yielded data point carries in ``MetricRecord.group_key``, so that the
                data points can be separated into one series per value. ``QueryMetricsRequest.group_by`` lists the
                accepted fields. Only the data points of at most 100 named values (``MAX_METRIC_GROUPS``) are yielded,
                together with those with no value for the field, and the SDK logs a warning when it leaves any out.
            owner_org_id: Organization that owns the metric. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            sort_by: Field to order the data points by, one of those ``QueryMetricsRequest.sort_by`` lists. ``None``
                orders them by the session time ``time_filter`` selects.

        Yields:
            One ``Metric`` per matching session, ordered by ``sort_by`` and then by ``session_id``.

        Raises:
            RobotoNotFoundException: The organization has no metric definition with this name.
            RobotoInvalidRequestException: ``sort_by`` names a field the query cannot order by.
            RobotoIllegalArgumentException: ``condition`` or ``group_by`` names a field or comparator the query does
                not accept, or a custom field the organization has not defined or that is not
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            pydantic.ValidationError: ``max_results`` is not from 1 to 10,000.

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

            Take the 10 most recent sessions:

            >>> import itertools
            >>> recent = list(itertools.islice(Metric.query(name="cpu.usage_max", descending=True), 10))

            Take the 10 sessions with the highest value:

            >>> highest = list(
            ...     itertools.islice(
            ...         Metric.query(name="cpu.usage_max", sort_by="value", descending=True),
            ...         10,
            ...     )
            ... )

            Read only data points of sessions tagged ``production`` that either ran in the EMEA region or were
            produced by a device at the Berlin site. Your organization must have defined both custom fields,
            ``region`` on sessions and ``site`` on devices, and moved them to ``Ready``; otherwise the query raises
            ``RobotoIllegalArgumentException``:

            >>> from roboto.query import Comparator, Condition, ConditionGroup, ConditionOperator
            >>> for m in Metric.query(
            ...     name="cpu.usage_max",
            ...     condition=ConditionGroup(
            ...         operator=ConditionOperator.And,
            ...         conditions=[
            ...             Condition(
            ...                 field="session.tags",
            ...                 comparator=Comparator.Contains,
            ...                 value="production",
            ...             ),
            ...             ConditionGroup(
            ...                 operator=ConditionOperator.Or,
            ...                 conditions=[
            ...                     Condition(
            ...                         field="session.custom.region",
            ...                         comparator=Comparator.Equals,
            ...                         value="emea",
            ...                     ),
            ...                     Condition(
            ...                         field="device.custom.site",
            ...                         comparator=Comparator.Equals,
            ...                         value="berlin",
            ...                     ),
            ...                 ],
            ...             ),
            ...         ],
            ...     ),
            ... ):
            ...     print(m.session_id, m.value)

            Separate the data points by the device that published them:

            >>> from collections import defaultdict
            >>> by_device = defaultdict(list)
            >>> for m in Metric.query(name="cpu.usage_max", group_by="device.device_id"):
            ...     by_device[m.group_key].append(m.value)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = QueryMetricsRequest(
            name=name,
            time_filter=time_filter,
            start_time_ns=to_epoch_nanoseconds(start_time) if start_time is not None else None,
            end_time_ns=to_epoch_nanoseconds(end_time) if end_time is not None else None,
            max_results=max_results,
            sort_by=sort_by,
            descending=descending,
            include_device_ids=include_device_ids,
            include_session_ids=include_session_ids,
            include_invocation_ids=include_invocation_ids,
            condition=condition,
            group_by=group_by,
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
            ).to_record(MetricQueryPage)
            if next_token is None:
                # Every page of one query carries the same total_groups and groups_truncated, so warn on the first only.
                _warn_if_groups_truncated(name, results.total_groups, results.groups_truncated)
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
        condition: typing.Optional[ConditionType] = None,
        group_by: typing.Optional[str] = None,
        time_zone: str = "UTC",
        week_start: DayOfWeek = DayOfWeek.Monday,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> list[NumericAggregateMetricRecord]:
        """Aggregate a metric's data points by calendar period.

        Groups the data points whose session time, the start or end that ``time_filter`` selects, falls in
        [``start_time``, ``end_time``) into periods of length ``period``, each starting at midnight in ``time_zone``,
        and applies ``aggregation`` to the values in each period.

        Roboto widens the time range to whole periods, so the first and last buckets aggregate their whole calendar
        period, including data points outside the requested range. A monthly aggregation from January 15 to March 15
        returns buckets for all of January, February and March, and a quarterly one from April 27 to December 28
        returns buckets for all of the second, third and fourth quarters.

        Args:
            name: Name of the metric definition to aggregate.
            period: Length of the calendar periods to group data points into.
            aggregation: Function to apply to the values of the data points in each bucket.
            start_time: Inclusive start of the time range, in nanoseconds since the Unix epoch or any value
                :py:func:`~roboto.time.to_epoch_nanoseconds` accepts.
            end_time: Exclusive end of the time range, in the same form.
            time_filter: Session time that places each data point in the time range and in a period: its start or its
                end.
            include_device_ids: IDs of the devices whose data points to aggregate. ``None`` aggregates only data points
                published without a device. Left unset (:py:const:`~roboto.sentinels.NotSet`), the device does not
                filter the aggregation.
            include_session_ids: IDs of the sessions whose data points to aggregate. Left unset (``NotSet``), the
                session does not filter the aggregation.
            include_invocation_ids: IDs of the action invocations whose data points to aggregate. ``None`` aggregates
                only data points no action published. Left unset (``NotSet``), the invocation does not filter the
                aggregation.
            condition: :py:class:`~roboto.query.Condition` or :py:class:`~roboto.query.ConditionGroup` that the data
                point's session, the device that produced it, or the session's collections must match. It narrows
                what each bucket aggregates without moving the periods' bounds, and a period left with no matching
                data points has no bucket. ``QueryMetricsRequest.condition`` lists the accepted fields, and says how a
                collection condition matches a session in several collections or in none.
            group_by: Field to split each period's bucket by, giving one bucket per period and distinct value of the
                field. ``None`` aggregates every matching data point of a period into one bucket. Accepts
                ``device.device_id`` and String, Enum, or Boolean custom fields of sessions and devices
                (``session.custom.<name>``, ``device.custom.<name>``). Data points with no value for the field are
                aggregated into a bucket whose ``NumericAggregateMetricRecord.group_key`` is ``None``. At most 100
                named values (``MAX_METRIC_GROUPS``) come back, those with the most data points in the requested
                range, and the SDK logs a warning when it leaves any out.
            time_zone: IANA name of the time zone in which each period starts at midnight, such as
                ``"America/Los_Angeles"``.
            week_start: Day each week starts on when ``period`` is ``AggregationPeriod.Weekly``. Other periods ignore
                it.
            owner_org_id: Organization that owns the metric. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The buckets that hold at least one data point, sorted by ``start_time``, earliest first: one
            ``NumericAggregateMetricRecord`` per period, or with ``group_by``, per period and distinct value, each
            carrying its value in ``group_key``.

        Raises:
            RobotoNotFoundException: The organization has no metric definition with this name.
            RobotoIllegalArgumentException: ``condition`` names a field or comparator the aggregation does not accept;
                ``condition`` or ``group_by`` names a custom field the organization has not defined or that is not
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`; ``group_by`` names a field that
                cannot form a series; or ``time_zone`` is ``CET``, ``EET``, ``MET``, ``WET``, or a name not in the
                IANA time zone database.

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

            The same aggregation over data points published from a device in the ``delivery`` fleet. Your
            organization must have defined the device custom field ``fleet`` and moved it to ``Ready``; otherwise the
            aggregation raises ``RobotoIllegalArgumentException``. A data point published without a device carries no
            ``fleet``, so ``Equals`` leaves it out, and so does ``NotEquals``: only ``IsNull`` and ``NotExists`` match
            a data point with no device. ``QueryMetricsRequest.condition`` gives the full field and comparator rules:

            >>> from roboto.query import Comparator, Condition
            >>> delivery_buckets = Metric.aggregate(
            ...     name="cpu.usage_max",
            ...     period=AggregationPeriod.Daily,
            ...     aggregation=NumericAggregation.Max,
            ...     start_time="2026-05-01T00:00:00Z",
            ...     end_time="2026-06-01T00:00:00Z",
            ...     condition=Condition(
            ...         field="device.custom.fleet",
            ...         comparator=Comparator.Equals,
            ...         value="delivery",
            ...     ),
            ... )
            >>> for bucket in delivery_buckets:
            ...     print(bucket.start_time, bucket.end_time, bucket.value, bucket.total)

            One series per device rather than one for the fleet. The buckets of data points published without a
            device have ``None`` as their ``group_key``:

            >>> per_device = Metric.aggregate(
            ...     name="cpu.usage_max",
            ...     period=AggregationPeriod.Daily,
            ...     aggregation=NumericAggregation.Max,
            ...     start_time="2026-05-01T00:00:00Z",
            ...     end_time="2026-06-01T00:00:00Z",
            ...     group_by="device.device_id",
            ... )
            >>> for bucket in per_device:
            ...     print(bucket.group_key, bucket.start_time, bucket.value)

            Weekly totals for a team in Los Angeles whose weeks start on Sunday. Each bucket starts at
            00:00 on a Sunday, Los Angeles time, and ends at 00:00 on the following Sunday:

            >>> from roboto.domain.metrics import DayOfWeek
            >>> weekly = Metric.aggregate(
            ...     name="track.length_km",
            ...     period=AggregationPeriod.Weekly,
            ...     aggregation=NumericAggregation.Sum,
            ...     start_time="2026-05-03T00:00:00-07:00",
            ...     end_time="2026-05-31T00:00:00-07:00",
            ...     time_zone="America/Los_Angeles",
            ...     week_start=DayOfWeek.Sunday,
            ... )
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
            condition=condition,
            group_by=group_by,
            time_zone=time_zone,
            week_start=week_start,
        )
        response = roboto_client.post(
            "v1/metrics/aggregate",
            data=request,
            owner_org_id=owner_org_id,
            idempotent=True,
        ).to_record(NumericAggregateMetricsResponse)
        _warn_if_groups_truncated(name, response.total_groups, response.groups_truncated)
        return response.records

    def __init__(self, record: MetricRecord, roboto_client: typing.Optional[RobotoClient]):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def metric_id(self) -> str:
        """ID of the metric definition the data point is recorded under."""
        return self.__record.metric_id

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def value(self) -> float:
        return self.__record.value

    @property
    def unit(self) -> typing.Optional[str]:
        return self.__record.unit

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
    def group_key(self) -> typing.Optional[str]:
        """Value of the ``QueryMetricsRequest.group_by`` field for this data point, as text whatever the field's type.

        ``MetricRecord.group_key`` says when it is ``None``.
        """
        return self.__record.group_key

    @property
    def published(self) -> datetime.datetime:
        """Time the data point was last published."""
        return self.__record.published

    @property
    def published_by(self) -> str:
        """Principal that last published the data point, as ``<type>:<id>``, such as ``user:<user_id>``."""
        return self.__record.published_by

    @property
    def min_timestamp_ns(self) -> typing.Optional[int]:
        """Earliest time covered by the data point's session, in nanoseconds since the Unix epoch.

        ``MetricRecord.min_timestamp_ns`` says when it is ``None``.
        """
        return self.__record.min_timestamp_ns

    @property
    def max_timestamp_ns(self) -> typing.Optional[int]:
        """Latest time covered by the data point's session, in nanoseconds since the Unix epoch.

        ``MetricRecord.max_timestamp_ns`` says when it is ``None``.
        """
        return self.__record.max_timestamp_ns

    @property
    def record(self) -> MetricRecord:
        """Record of the metric data point that this instance holds."""
        return self.__record
