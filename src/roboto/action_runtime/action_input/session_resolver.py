# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...domain.actions import DataSelector
from ...experimental.sessions import Session
from ...http import RobotoClient
from ...logging import default_logger
from ...query.roboql_literal import as_roboql_string_literal
from ...roboto_search import RobotoSearch

log = default_logger()


class InputSessionResolver:
    """Looks up the sessions an action invocation runs on, from the session selectors declared as its inputs.

    A selector names sessions by ID, by name, or with a RoboQL query; every field it populates is looked up and
    the matches are returned together. ``resolve_all`` returns each session once, while ``resolve`` repeats a
    session that matches on more than one field.
    """

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        roboto_search: typing.Optional[RobotoSearch] = None,
    ):
        self.roboto_client = RobotoClient.defaulted(roboto_client)
        self.roboto_search = (
            roboto_search if roboto_search is not None else RobotoSearch.for_roboto_client(self.roboto_client)
        )

    def resolve_all(self, session_selectors: collections.abc.Sequence[DataSelector]) -> list[Session]:
        session_ids: set[str] = set()
        sessions: list[Session] = []

        for selector in session_selectors:
            resolved = self.resolve(selector)

            for session in resolved:
                if session.session_id not in session_ids:
                    sessions.append(session)
                    session_ids.add(session.session_id)

        return sessions

    def resolve(self, session_selector: DataSelector) -> list[Session]:
        """Looks up the sessions one selector names. A ``dataset_id`` on the selector is ignored, with a warning."""
        sessions: list[Session] = []

        if session_selector.dataset_id:
            # A Sessions query can express the same narrowing with dataset.dataset_id,
            # which matches sessions holding at least one file from that dataset.
            dataset_id = session_selector.dataset_id
            log.warning(
                f"Ignoring dataset_id {dataset_id!r}. Use DataSelector.query instead: "
                f"dataset.dataset_id = {as_roboql_string_literal(dataset_id)}"
            )

        if session_selector.ids:
            log.info(f"Looking up sessions with IDs: {session_selector.ids}")
            sessions.extend(self._resolve_from_ids(session_selector.ids))

        if session_selector.names:
            log.info(f"Looking up sessions with names: {session_selector.names}")
            sessions.extend(self._resolve_from_names(session_selector.names))

        if session_selector.query:
            log.info(f"Looking up sessions using RoboQL query: {session_selector.query}")
            sessions.extend(self._resolve_from_query(session_selector.query))

        return sessions

    def _resolve_from_query(self, query: str) -> list[Session]:
        return list(self.roboto_search.find_sessions(query))

    def _resolve_from_names(self, session_names: list[str]) -> list[Session]:
        query = " OR ".join(f"name = {as_roboql_string_literal(name)}" for name in session_names)
        return self._resolve_from_query(query)

    def _resolve_from_ids(self, session_ids: list[str]) -> list[Session]:
        return [Session.from_id(session_id, roboto_client=self.roboto_client) for session_id in session_ids]
