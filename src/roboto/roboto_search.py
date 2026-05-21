# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import math
import typing

from .domain import (
    collections as roboto_collections,
)
from .domain import (
    datasets,
    events,
    files,
    sessions,
    topics,
)
from .env import RobotoEnv
from .http import RobotoClient
from .query import Query, QueryClient, QueryContentMode, QueryTarget
from .warnings import experimental


class RobotoSearch:
    """
    A high-level interface for querying the Roboto data platform.

    In most cases, using this class should be as simple as:

    >>> from roboto import RobotoSearch
    >>> rs = RobotoSearch()
    >>> for dataset in rs.find_datasets(...):
    ...     ...
    """

    __query_client: QueryClient

    @classmethod
    def for_roboto_client(cls, roboto_client: RobotoClient, org_id: typing.Optional[str] = None) -> RobotoSearch:
        return RobotoSearch(query_client=QueryClient(roboto_client, org_id))

    @classmethod
    def from_env(cls) -> RobotoSearch:
        """Create a RobotoSearch instance configured from environment variables.

        Reads authentication credentials and endpoint configuration from environment
        variables ($ROBOTO_API_KEY/$ROBOTO_BEARER_TOKEN, $ROBOTO_SERVICE_ENDPOINT)
        or the config file at $ROBOTO_CONFIG_FILE (default: ~/.roboto/config.json).
        If using the config file, $ROBOTO_PROFILE can be used to select a profile from the config.

        $ROBOTO_ORG_ID can be used to set the organization ID to query.
        This should only be necessary if you belong to multiple organizations.

        Returns:
            A configured RobotoSearch instance ready to query the Roboto platform.

        Examples:
            >>> import roboto
            >>> roboto_search = roboto.RobotoSearch.from_env()
            >>> for dataset in roboto_search.find_datasets():
            ...     print(dataset.name)
        """
        roboto_client = RobotoClient.from_env()
        env = RobotoEnv.default()
        return cls.for_roboto_client(roboto_client, env.org_id)

    def __init__(self, query_client: typing.Optional[QueryClient] = None):
        self.__query_client = query_client if query_client is not None else QueryClient()

    def find_collections(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[roboto_collections.Collection, None, None]:
        for result in self.__query_client.submit_query(query, QueryTarget.Collections, timeout_seconds):
            yield roboto_collections.Collection(
                roboto_collections.CollectionRecord.model_validate(result),
                self.__query_client.roboto_client,
            )

    def find_datasets(
        self,
        query: typing.Optional[Query] = None,
        content_mode: QueryContentMode = QueryContentMode.RecordOnly,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[datasets.Dataset, None, None]:
        for result in self.__query_client.submit_query(
            query, QueryTarget.Datasets, timeout_seconds, content_mode=content_mode
        ):
            yield datasets.Dataset(
                datasets.DatasetRecord.model_validate(result),
                self.__query_client.roboto_client,
                content_mode=content_mode,
            )

    def find_files(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[files.File, None, None]:
        for result in self.__query_client.submit_query(query, QueryTarget.Files, timeout_seconds):
            yield files.File(
                files.FileRecord.model_validate(result),
                self.__query_client.roboto_client,
            )

    def find_message_paths(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[topics.MessagePath, None, None]:
        for result in self.__query_client.submit_query(query, QueryTarget.TopicMessagePaths, timeout_seconds):
            yield topics.MessagePath(
                topics.MessagePathRecord.model_validate(result),
                self.__query_client.roboto_client,
            )

    def find_topics(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[topics.Topic, None, None]:
        """
        Examples:
            >>> import matplotlib.pyplot as plt
            >>> from roboto import RobotoSearch
            >>> robosearch = RobotoSearch()
            >>> for topic in robosearch.find_topics("msgpaths[cpuload.load].max > 0.9"):
            ...     df = topic.get_data_as_df(message_paths_include=["cpuload.load"])
            ...     plt.plot(df.index, df["cpuload.load"], label=topic.topic_id)
            >>> plt.legend()
            >>> plt.show()
        """
        for result in self.__query_client.submit_query(query, QueryTarget.Topics, timeout_seconds):
            yield topics.Topic(
                topics.TopicRecord.model_validate(result),
                self.__query_client.roboto_client,
            )

    def find_events(
        self, query: typing.Optional[Query] = None, timeout_seconds: float = math.inf
    ) -> collections.abc.Generator[events.Event]:
        for result in self.__query_client.submit_query(query, QueryTarget.Events, timeout_seconds):
            yield events.Event(
                events.EventRecord.model_validate(result),
                self.__query_client.roboto_client,
            )

    @experimental
    def find_sessions(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[sessions.Session, None, None]:
        """Yield ``Session`` objects matching ``query``, one at a time.

        Submits ``query`` against the structured-query API targeting Sessions and lazily
        materializes each row into a ``Session`` instance bound to the caller's
        ``RobotoClient``. Iteration drives server-side pagination under the hood;
        ``timeout_seconds`` bounds the total wall-clock time spent waiting for query
        results before iteration stops.

        Filterable fields:

        - ``session_id`` (alias ``id``).
        - ``name``.
        - ``min_timestamp_ns`` (alias ``start_time``) — inclusive lower bound of the
          session's recorded time window.
        - ``max_timestamp_ns`` (alias ``end_time``) — inclusive upper bound of the
          session's recorded time window.
        - ``duration`` — synthetic numeric field equal to
          ``max_timestamp_ns - min_timestamp_ns``; accepts integer nanoseconds only.
        - ``dataset.dataset_id`` (alias ``dataset.id``) — matches sessions that
          include at least one file from the given dataset. ``=`` / ``!=`` only.
        - ``device.device_id`` (alias ``device.id``) — matches sessions attached
          to the given device. ``=`` / ``!=`` only.

        The four time-window fields accept any shape :py:data:`roboto.time.Time`
        permits — integer epoch nanoseconds, float / Decimal / ``<sec>.<nsec>`` string
        seconds, ISO8601 strings, or tz-aware ``datetime`` — and the server normalizes
        the value to epoch nanoseconds before the comparison runs.

        Sortable fields: ``session_id``, ``min_timestamp_ns``, and ``duration``.
        """
        for result in self.__query_client.submit_query(query, QueryTarget.Sessions, timeout_seconds):
            yield sessions.Session(
                record=sessions.SessionRecord.model_validate(result),
                roboto_client=self.__query_client.roboto_client,
            )
