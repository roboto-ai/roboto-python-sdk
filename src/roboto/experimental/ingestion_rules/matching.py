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
    """The path half of an ingestion rule: include and exclude Git wildmatch patterns.

    File annotation and the rule's trigger both decide through :meth:`matches`, so a file is marked
    ingestable exactly when the rule's trigger would accept its upload.
    """

    include_patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...] = ()

    @classmethod
    def of(
        cls, include_patterns: collections.abc.Iterable[str], exclude_patterns: collections.abc.Iterable[str] = ()
    ) -> "IngestionPathRule":
        return cls(tuple(include_patterns), tuple(exclude_patterns))

    def matches(self, relative_path: str) -> bool:
        """Whether ``relative_path`` matches an include pattern and no exclude pattern, and is not a dotfile.

        No rule makes a dotfile ingestable, because triggers never run on dotfiles.
        """
        if is_dotfile_path(relative_path):
            return False
        return path_matches_specs(relative_path, include_spec=self._include_spec, exclude_spec=self._exclude_spec)

    # Rule patterns never start with "!" (the create and update requests refuse them), so one PathSpec over all
    # of a rule's patterns matches exactly the paths some single pattern matches.
    @functools.cached_property
    def _include_spec(self) -> pathspec.PathSpec:
        return pathspec_from_patterns(self.include_patterns)

    @functools.cached_property
    def _exclude_spec(self) -> pathspec.PathSpec:
        return pathspec_from_patterns(self.exclude_patterns)
