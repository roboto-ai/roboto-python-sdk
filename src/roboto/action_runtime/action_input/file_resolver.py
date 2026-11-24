# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...domain.actions import FileSelector
from ...domain.datasets import Dataset
from ...domain.files import File
from ...http import RobotoClient
from ...logging import default_logger
from ...query.roboql_literal import as_roboql_string_literal
from ...roboto_search import RobotoSearch

log = default_logger()


class InputFileResolver:
    """Resolver that fetches the files an action invocation's file selectors choose.

    :py:meth:`~roboto.action_runtime.ActionInputResolver.resolve_input_spec` resolves an invocation's file selectors
    through it, so most code never calls it. Action code reads the resolved files from
    :py:meth:`~roboto.action_runtime.InvocationContext.get_input` instead.
    """

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        roboto_search: typing.Optional[RobotoSearch] = None,
    ):
        self.roboto_client = RobotoClient.defaulted(roboto_client)
        """Client this resolver makes requests to Roboto with.

        Defaults to one configured from the environment, by :py:meth:`~roboto.http.RobotoClient.from_env`.
        """
        self.roboto_search = (
            roboto_search if roboto_search is not None else RobotoSearch.for_roboto_client(self.roboto_client)
        )
        """Search client that runs the RoboQL lookups for a selector's ``query`` and ``names``.

        Defaults to one that sends its queries through ``roboto_client``.
        """

    def resolve_all(self, file_selectors: collections.abc.Sequence[FileSelector]) -> list[File]:
        """Fetch the files that any of the selectors choose, each file once.

        Files come back in the order they are first found: selector by selector, and within one selector in the
        order ``resolve`` gives.

        Args:
            file_selectors: Selectors of the files to fetch.

        Raises:
            RobotoNotFoundException: No file has one of the IDs in a selector's ``ids``, or no dataset has a
                selector's ``dataset_id``.
            RobotoIllegalArgumentException: A selector's ``query`` is not valid RoboQL.
        """
        file_ids: set[str] = set()
        all_files: list[File] = []

        for file_selector in file_selectors:
            resolved = self.resolve(file_selector)

            for file in resolved:
                if file.file_id not in file_ids:
                    file_ids.add(file.file_id)
                    all_files.append(file)

        return all_files

    def resolve(self, selector: FileSelector) -> list[File]:
        """Fetch the files one selector chooses.

        Files come back with those ``paths`` match first, then those ``query`` matches, then those named by ``ids``,
        then those named by ``names``. A file that more than one of these fields matches appears once for each.

        - ``paths`` select files from the dataset ``dataset_id`` names, leaving out files beneath a top-level
          directory whose name starts with a dot. Without ``dataset_id``, ``paths`` select nothing.
        - A name in ``names`` matches a file whose whole path, not only its name, equals it: ``"drive1.mcap"``
          matches ``drive1.mcap`` at the top of a dataset but not ``logs/drive1.mcap``. A ``%`` or ``_`` in a name
          matches as a wildcard.
        - ``dataset_id`` narrows only ``paths``. When ``query``, ``ids`` or ``names`` is also set, a warning is
          logged that it does not narrow them.

        Args:
            selector: Selector of the files to fetch.

        Raises:
            RobotoNotFoundException: No file has one of the IDs in the selector's ``ids``, or no dataset has the
                selector's ``dataset_id``.
            RobotoIllegalArgumentException: The selector's ``query`` is not valid RoboQL.
        """
        files: list[File] = []

        if selector.dataset_id and selector.paths:
            log.info(
                "Looking up files matching %s from dataset '%s'",
                selector.paths,
                selector.dataset_id,
            )

            files.extend(self._resolve_from_dataset_file_paths(selector.dataset_id, selector.paths))

        if selector.query:
            log.info(f"Looking up files using RoboQL query: {selector.query}")
            InputFileResolver.__ignore_dataset_id(selector.dataset_id)
            files.extend(self._resolve_from_query(selector.query))

        if selector.ids:
            log.info(f"Looking up files by IDs: {selector.ids}")
            InputFileResolver.__ignore_dataset_id(selector.dataset_id)
            files.extend(self._resolve_from_ids(selector.ids))

        if selector.names:
            log.info(f"Looking up files by names: {selector.names}")
            InputFileResolver.__ignore_dataset_id(selector.dataset_id)
            files.extend(self._resolve_from_names(selector.names))

        return files

    def _resolve_from_dataset_file_paths(self, dataset_id: str, paths: list[str]) -> list[File]:
        dataset = Dataset.from_id(dataset_id=dataset_id, roboto_client=self.roboto_client)

        return list(
            dataset.list_files(
                include_patterns=paths,
                # Leave out files beneath a top-level dot-named directory, such as ".cache/run.bag". A dot-named
                # file, or a dot-named directory below the top level, is still listed.
                exclude_patterns=[".*/**/*"],
            )
        )

    def _resolve_from_ids(self, file_ids: list[str]) -> list[File]:
        return [File.from_id(file_id, roboto_client=self.roboto_client) for file_id in file_ids]

    def _resolve_from_query(self, query: str) -> list[File]:
        return list(self.roboto_search.find_files(query))

    def _resolve_from_names(self, file_names: list[str]) -> list[File]:
        # as_roboql_string_literal escapes only backslashes and double quotes, so LIKE treats a % or _ in a name
        # as a wildcard.
        query = " OR ".join(f"path LIKE {as_roboql_string_literal(file_name)}" for file_name in file_names)
        return self._resolve_from_query(query)

    @staticmethod
    def __ignore_dataset_id(dataset_id: str | None, message: str | None = None) -> None:
        if dataset_id:
            message = message if message else "currently only supported with 'paths'"
            log.warning(f"Ignoring dataset ID '{dataset_id}': {message}.")
