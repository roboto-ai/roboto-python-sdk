# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import dataclasses
import functools

import pathspec

from ...paths import (
    is_dotfile_path,
    path_matches_specs,
    pathspec_from_patterns,
)


@dataclasses.dataclass(frozen=True)
class IngestionPathRule:
    """Path patterns of an ingestion rule, which decide whether the rule matches a file's path.

    Roboto decides with this class both when it marks a file ingestable and when the rule's trigger decides whether to
    ingest an upload, so a file is marked ingestable exactly when the rule's trigger would accept its upload. Use it to
    check locally which paths a rule matches.
    """

    include_patterns: tuple[str, ...]
    """Gitignore-style patterns, such as ``**/*.mcap``, for the files the rule makes ingestable."""

    exclude_patterns: tuple[str, ...] = ()
    """Gitignore-style patterns for the files the rule leaves out, even when they match ``include_patterns``."""

    @classmethod
    def of(
        cls, include_patterns: collections.abc.Iterable[str], exclude_patterns: collections.abc.Iterable[str] = ()
    ) -> "IngestionPathRule":
        """Build a rule from iterables of patterns, such as the lists on an ``IngestionRuleRecord``."""
        return cls(tuple(include_patterns), tuple(exclude_patterns))

    def matches(self, relative_path: str) -> bool:
        """Return whether ``relative_path`` matches an include pattern and no exclude pattern.

        A path with a component that starts with a dot never matches, because triggers never run on such files.

        Args:
            relative_path: Path of the file within its dataset, such as ``logs/run_1.mcap``.
        """
        if is_dotfile_path(relative_path):
            return False
        return path_matches_specs(relative_path, include_spec=self._include_spec, exclude_spec=self._exclude_spec)

    # Rule patterns never start with "!" (CreateIngestionRuleRequest and UpdateIngestionRuleRequest refuse them), so a
    # PathSpec over a list of them matches exactly the paths that some single pattern in the list matches.
    @functools.cached_property
    def _include_spec(self) -> pathspec.PathSpec:
        return pathspec_from_patterns(self.include_patterns)

    @functools.cached_property
    def _exclude_spec(self) -> pathspec.PathSpec:
        return pathspec_from_patterns(self.exclude_patterns)
