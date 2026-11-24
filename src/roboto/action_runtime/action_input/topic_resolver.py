# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...domain.actions import DataSelector
from ...domain.topics import Topic
from ...http import RobotoClient
from ...logging import default_logger
from ...query.roboql_literal import as_roboql_string_literal
from ...roboto_search import RobotoSearch

log = default_logger()


class InputTopicResolver:
    """Resolver that fetches the topics an action invocation's topic selectors choose.

    :py:meth:`~roboto.action_runtime.ActionInputResolver.resolve_input_spec` resolves an input's topic selectors
    through it, so most code never calls it. Action code reads the resolved topics from
    :py:meth:`~roboto.action_runtime.InvocationContext.get_input` instead.
    """

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        roboto_search: typing.Optional[RobotoSearch] = None,
    ):
        self.roboto_client = RobotoClient.defaulted(roboto_client)
        """Client to make requests to Roboto with.

        Defaults to one configured from the environment, by :py:meth:`~roboto.http.RobotoClient.from_env`.
        """

        self.roboto_search = (
            roboto_search if roboto_search is not None else RobotoSearch.for_roboto_client(self.roboto_client)
        )
        """Search client that runs the selectors' RoboQL queries.

        Defaults to one that sends its queries through ``roboto_client``.
        """

    def resolve_all(self, topic_selectors: collections.abc.Sequence[DataSelector]) -> list[Topic]:
        """Fetch the topics that any of the selectors choose, each topic once.

        Topics come back in the order ``resolve`` finds them, selector by selector. Fails as ``resolve`` does.

        Args:
            topic_selectors: Topic selectors to resolve.
        """
        topic_ids: set[str] = set()
        all_topics: list[Topic] = []

        for topic_selector in topic_selectors:
            topics = self.resolve(topic_selector)

            for topic in topics:
                if topic.topic_id not in topic_ids:
                    all_topics.append(topic)
                    topic_ids.add(topic.topic_id)

        return all_topics

    def resolve(self, topic_selector: DataSelector) -> list[Topic]:
        """Fetch the topics one selector chooses.

        Looks up the selector's ``ids``, then its ``names``, then its ``query``, and returns every match in that
        order, so a topic that more than one of them matches appears more than once. A name matches every topic with
        exactly that name, in any dataset. A ``dataset_id`` on the selector does not narrow the lookup; it is ignored,
        with a logged warning.

        Args:
            topic_selector: Selector that chooses topics by ID, by name, or with a RoboQL query.

        Raises:
            RobotoNotFoundException: No topic has one of the selector's IDs.
            RobotoIllegalArgumentException: The selector's ``query`` is not valid RoboQL.
        """
        topics: list[Topic] = []

        if topic_selector.dataset_id:
            # In a topic query, dataset.dataset_id matches the topics in that dataset's files.
            dataset_id = topic_selector.dataset_id
            log.warning(
                f"Ignoring dataset_id {dataset_id!r}. Use DataSelector.query instead: "
                f"dataset.dataset_id = {as_roboql_string_literal(dataset_id)}"
            )

        if topic_selector.ids:
            log.info(f"Looking up topics with IDs: {topic_selector.ids}")
            topics.extend(self._resolve_from_ids(topic_selector.ids))

        if topic_selector.names:
            log.info(f"Looking up topics with names: {topic_selector.names}")
            topics.extend(self._resolve_from_names(topic_selector.names))

        if topic_selector.query:
            log.info(f"Looking up topics using RoboQL query: {topic_selector.query}")
            topics.extend(self._resolve_from_query(topic_selector.query))

        return topics

    def _resolve_from_query(self, query: str) -> list[Topic]:
        return list(self.roboto_search.find_topics(query))

    def _resolve_from_names(self, topic_names: collections.abc.Sequence[str]) -> list[Topic]:
        query = " OR ".join(f"name = {as_roboql_string_literal(name)}" for name in topic_names)
        return self._resolve_from_query(query)

    def _resolve_from_ids(self, topic_ids: collections.abc.Sequence[str]) -> list[Topic]:
        return [Topic.from_id(topic_id, self.roboto_client) for topic_id in topic_ids]
