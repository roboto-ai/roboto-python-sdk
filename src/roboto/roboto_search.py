# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import math
import typing

from .config import RobotoConfig
from .domain import (
    collections as roboto_collections,
)
from .domain import (
    datasets,
    devices,
    events,
    files,
    topics,
)
from .env import RobotoEnv
from .experimental import events as experimental_events
from .experimental import sessions
from .http import RobotoClient
from .query import Query, QueryClient, QueryContentMode, QueryTarget
from .warnings import experimental


def _profile_org_id() -> typing.Optional[str]:
    # RobotoConfig.from_env raises OSError for a config file it cannot read and ValueError for one it cannot use.
    # Either can happen even after RobotoClient.from_env has returned a client: it keeps the client it first built,
    # and the config file may have been moved or changed since. The search then names no organization.
    try:
        return RobotoConfig.from_env().org_id
    except (OSError, ValueError):
        return None


class RobotoSearch:
    """Entry point for finding the datasets, files, topics, events and other resources that match a query.

    Each ``find_*`` method takes a query, either a RoboQL string such as ``"tags CONTAINS 'flight'"`` or a
    :py:class:`~roboto.query.QuerySpecification`, and yields the matching resources as SDK objects, in the query's
    sort order. It sends nothing until iteration starts. Then it submits the query, checks every 2 seconds until
    Roboto has the results, and fetches them one page at a time as iteration reaches each page. To cap the number of
    results, add ``LIMIT N`` to a RoboQL query or set ``max_results`` on a specification.

    Get a ``RobotoSearch`` from ``from_env`` or ``for_roboto_client``, or build one from a
    :py:class:`~roboto.query.QueryClient`.

    Args:
        query_client: Client that submits the queries and fetches their results. ``None`` builds one from the
            access token or config file profile that :py:meth:`~roboto.config.RobotoConfig.from_env` reads. That
            client names no organization, so a caller who belongs to more than one organization should use
            ``from_env`` instead.

    Raises:
        FileNotFoundError: ``query_client`` is not given, no access token is set, and the config file does not exist.
        OSError: ``query_client`` is not given and the config file exists but cannot be read.
        ValueError: ``query_client`` is not given and the config file is not a JSON object, holds no valid profile,
            or has no profile by the chosen name.
        RobotoDeprecatedException: ``query_client`` is not given and the access token begins with ``robo_pat``, a
            format Roboto retired in March 2024.

    Note:
        Roboto does not report a query that fails to run. Iteration keeps waiting for its results until
        ``timeout_seconds`` passes, which by default it never does.
    """

    __query_client: QueryClient

    @classmethod
    def for_roboto_client(cls, roboto_client: RobotoClient, org_id: typing.Optional[str] = None) -> RobotoSearch:
        """Build a ``RobotoSearch`` that sends its queries through ``roboto_client``.

        Args:
            roboto_client: Client to make requests to Roboto with.
            org_id: Organization to search. Required when the caller belongs to more than one organization;
                otherwise the caller's only organization.

        Examples:
            >>> from roboto import RobotoClient, RobotoSearch
            >>> roboto_client = RobotoClient.for_profile("prod")
            >>> roboto_search = RobotoSearch.for_roboto_client(roboto_client, org_id="og_12345")
        """
        return RobotoSearch(query_client=QueryClient(roboto_client, org_id))

    @classmethod
    def from_env(cls) -> RobotoSearch:
        """Build a ``RobotoSearch`` that uses the credentials and organization the environment gives.

        Queries go through the client :py:meth:`~roboto.http.RobotoClient.from_env` returns, which reads an access
        token from ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN``, or else a profile from the Roboto config file, and
        raises when it can read neither. The search runs in the organization ``ROBOTO_ORG_ID`` names or, when that is
        unset, in the :py:attr:`~roboto.config.RobotoConfig.org_id` that ``roboto setup`` saved to the config file
        profile. Only a caller who belongs to more than one organization needs either.

        Examples:
            >>> import roboto
            >>> roboto_search = roboto.RobotoSearch.from_env()
            >>> for dataset in roboto_search.find_datasets():
            ...     print(dataset.name)
        """
        roboto_client = RobotoClient.from_env()
        env = RobotoEnv.default()
        return cls.for_roboto_client(roboto_client, env.org_id or _profile_org_id())

    def __init__(self, query_client: typing.Optional[QueryClient] = None):
        self.__query_client = query_client if query_client is not None else QueryClient()

    def find_collections(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[roboto_collections.Collection, None, None]:
        """Yield the collections that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every collection.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            >>> from roboto import RobotoSearch
            >>> for collection in RobotoSearch.from_env().find_collections("name CONTAINS 'regression'"):
            ...     print(collection.collection_id)
        """
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
        """Yield the datasets that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every dataset.
            content_mode: Whether each dataset comes with its key-value metadata.
                :py:attr:`~roboto.query.QueryContentMode.RecordOnly` leaves it out, and the first
                :py:meth:`~roboto.domain.datasets.Dataset.get_metadata` call on a dataset fetches it.
                :py:attr:`~roboto.query.QueryContentMode.RecordWithMeta` includes it, at the cost of larger responses.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            Print the metadata of every dataset tagged ``flight``:

            >>> from roboto import RobotoSearch
            >>> from roboto.query import QueryContentMode
            >>> for dataset in RobotoSearch.from_env().find_datasets(
            ...     "tags CONTAINS 'flight'", content_mode=QueryContentMode.RecordWithMeta
            ... ):
            ...     print(dataset.dataset_id, dataset.get_metadata())
        """
        for result in self.__query_client.submit_query(
            query, QueryTarget.Datasets, timeout_seconds, content_mode=content_mode
        ):
            yield datasets.Dataset(
                datasets.DatasetRecord.model_validate(result),
                self.__query_client.roboto_client,
                content_mode=content_mode,
            )

    def find_devices(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[devices.Device, None, None]:
        """Yield the devices that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every device.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            >>> from roboto import RobotoSearch
            >>> searcher = RobotoSearch.from_env()
            >>> for device in searcher.find_devices("tags CONTAINS 'warehouse'"):
            ...     print(device.device_id)
        """
        for result in self.__query_client.submit_query(query, QueryTarget.Devices, timeout_seconds):
            yield devices.Device(
                devices.DeviceRecord.model_validate(result),
                self.__query_client.roboto_client,
            )

    def find_files(
        self,
        query: typing.Optional[Query] = None,
        timeout_seconds: float = math.inf,
    ) -> collections.abc.Generator[files.File, None, None]:
        """Yield the files that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every file.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            >>> from roboto import RobotoSearch
            >>> for file in RobotoSearch.from_env().find_files("name CONTAINS '.mcap'"):
            ...     print(file.file_id, file.relative_path)
        """
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
        """Yield the message paths that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every message path.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            >>> from roboto import RobotoSearch
            >>> for message_path in RobotoSearch.from_env().find_message_paths("message_path CONTAINS 'velocity'"):
            ...     print(message_path.topic_id, message_path.path)
        """
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
        """Yield the topics that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every topic.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            Plot the CPU load of every topic whose ``cpuload.load`` passed 0.9:

            >>> import matplotlib.pyplot as plt
            >>> from roboto import RobotoSearch
            >>> searcher = RobotoSearch.from_env()
            >>> for topic in searcher.find_topics("msgpaths[cpuload.load].max > 0.9"):
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
    ) -> collections.abc.Generator[typing.Union[events.Event, experimental_events.Event]]:
        """Yield the events that match a query.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every event.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Yields:
            Dataset events as :py:class:`~roboto.domain.events.Event` and, in organizations that have session events
            enabled and to a caller who may view the organization's sessions, session events as
            ``roboto.experimental.events.Event``. Only a session event has a ``session_id``, so a condition on
            ``session_id`` selects one kind or the other.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.

        Examples:
            Print every event named ``Hard landing``:

            >>> from roboto import RobotoSearch
            >>> for event in RobotoSearch.from_env().find_events("name = 'Hard landing'"):
            ...     print(event.event_id, event.name)

            Print only the events created on one session:

            >>> for event in RobotoSearch.from_env().find_events("session_id = 'se_12345'"):
            ...     print(event.event_id, event.start_time)
        """
        for result in self.__query_client.submit_query(query, QueryTarget.Events, timeout_seconds):
            if result.get("session_id") is not None:
                yield experimental_events.Event(
                    experimental_events.EventRecord.model_validate(result), self.__query_client.roboto_client
                )
            else:
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
        """Yield the sessions that match a query.

        A query can filter on these fields, among others:

        - ``session_id`` (alias ``id``).
        - ``name``.
        - ``min_timestamp_ns`` (alias ``start_time``): inclusive start of the session's recorded time window.
        - ``max_timestamp_ns`` (alias ``end_time``): inclusive end of the session's recorded time window.
        - ``duration``: ``max_timestamp_ns - min_timestamp_ns``, compared only with an integer number of nanoseconds.
        - ``dataset.dataset_id`` (alias ``dataset.id``): matches sessions that include at least one file from the
          dataset. Takes ``=`` and ``!=`` only.
        - ``device.device_id`` (alias ``device.id``): matches sessions attached to the device. Takes ``=`` and ``!=``
          only.
        - ``device.device_type_id``: matches sessions attached to a device of that type. Takes ``=``, ``!=``,
          ``IS_NULL`` and ``IS_NOT_NULL`` only.
        - ``collection.collection_id`` (alias ``collection.id``): matches sessions in the collection. Takes ``=`` and
          ``!=`` only.
        - ``metric.<name>`` (alias ``metrics.<name>``): matches sessions by the session metric ``<name>``, whose dots
          are part of the name (``metric.cpu.load.max``). ``=``, ``!=``, ``>``, ``>=``, ``<`` and ``<=`` take a number
          and match only sessions that have the metric with a value that satisfies the comparison. ``IS_NOT_NULL``
          and ``EXISTS`` take no value and match sessions that have the metric; ``IS_NULL`` and ``NOT_EXISTS`` match
          sessions that lack it.

        ``min_timestamp_ns`` and ``max_timestamp_ns`` accept any value :py:func:`~roboto.time.to_epoch_nanoseconds`
        accepts: an integer is nanoseconds since the Unix epoch, a float, ``Decimal`` or ``"<sec>.<nsec>"`` string is
        seconds, and an ISO 8601 string or a ``datetime`` is read as UTC when it has no timezone. A session with no
        files has no recorded time window, so on those two fields only ``IS_NULL`` matches it.

        Results can be sorted by ``session_id``, ``name``, ``min_timestamp_ns`` or ``duration``.

        Args:
            query: RoboQL query string or :py:class:`~roboto.query.QuerySpecification` to match. ``None`` matches
                every session.
            timeout_seconds: Seconds to wait for the query's results. Waits indefinitely by default.

        Raises:
            RobotoIllegalArgumentException: ``query`` is a string that is not valid RoboQL. It surfaces on the first
                iteration.
            roboto.waiters.TimeoutError: The query's results were not ready within ``timeout_seconds``. It surfaces on
                the first iteration.
        """
        for result in self.__query_client.submit_query(query, QueryTarget.Sessions, timeout_seconds):
            yield sessions.Session(
                record=sessions.SessionRecord.model_validate(result),
                roboto_client=self.__query_client.roboto_client,
            )
