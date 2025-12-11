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
    topics,
)
from .env import RobotoEnv
from .http import RobotoClient
from .query import Query, QueryClient, QueryTarget


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
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[datasets.Dataset, None, None]:
        for result in self.__query_client.submit_query(query, QueryTarget.Datasets, timeout_seconds):
            yield datasets.Dataset(
                datasets.DatasetRecord.model_validate(result),
                self.__query_client.roboto_client,
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
            >>> import pandas as pd
            >>> from roboto import RobotoSearch
            >>> robosearch = RobotoSearch()
            >>> for topic in robosearch.find_topics("msgpaths[cpuload.load].max > 0.9"):
            ...     topic_data = list(topic.get_data())
            ...     df = pd.json_normalize(topic_data)
            ... plt.plot(df["log_time"], df["load"], label=f"{topic.topic_id}")
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
