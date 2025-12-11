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
from ...roboto_search import RobotoSearch

log = default_logger()


class InputFileResolver:
    """Resolves file selectors to file entities, if available."""

    def __init__(
        self,
        roboto_client: typing.Optional[RobotoClient] = None,
        roboto_search: typing.Optional[RobotoSearch] = None,
    ):
        self.roboto_client = RobotoClient.defaulted(roboto_client)
        self.roboto_search = (
            roboto_search if roboto_search is not None else RobotoSearch.for_roboto_client(self.roboto_client)
        )

    def resolve_all(self, file_selectors: collections.abc.Sequence[FileSelector]) -> list[File]:
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
                # Don't include "hidden"/"system" files
                # This is currently heuristic based,
                # and must be updated once https://roboto.atlassian.net/browse/ROBO-1105 is addressed.
                exclude_patterns=[".*/**/*"],
            )
        )

    def _resolve_from_ids(self, file_ids: list[str]) -> list[File]:
        return [File.from_id(file_id, roboto_client=self.roboto_client) for file_id in file_ids]

    def _resolve_from_query(self, query: str) -> list[File]:
        return list(self.roboto_search.find_files(query))

    def _resolve_from_names(self, file_names: list[str]) -> list[File]:
        query = " OR ".join(f'path LIKE "{file_name}"' for file_name in file_names)
        return self._resolve_from_query(query)

    @staticmethod
    def __ignore_dataset_id(dataset_id: str | None, message: str | None = None) -> None:
        if dataset_id:
            message = message if message else "currently only supported with 'paths'"
            log.warning(f"Ignoring dataset ID '{dataset_id}': {message}.")
