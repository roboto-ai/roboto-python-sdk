# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


from typing import Optional

import pathspec


def git_pathspec_escape_path(path: str) -> str:
    """
    Turns a literal path into a gitignore glob that matches the literal path.
    """
    escaped = path.replace("[", "\\[")
    escaped = escaped.replace("]", "\\]")
    return escaped


def git_paths_to_spec(paths: list[str]) -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, paths)


def git_paths_match(
    include_patterns: Optional[list[str]],
    exclude_patterns: Optional[list[str]],
    file: str,
) -> bool:
    # Include patterns are provided, and the file isn't included, ignore it
    if include_patterns is not None:
        if not git_paths_to_spec(include_patterns).match_file(file):
            return False

    # Exclude pattern is provided, and the file is included, ignore it
    if exclude_patterns is not None:
        if git_paths_to_spec(exclude_patterns).match_file(file):
            return False

    return True


def exclude_patterns_to_spec(
    exclude_patterns: Optional[list[str]] = None,
) -> Optional[pathspec.PathSpec]:
    return (
        None
        if exclude_patterns is None
        else pathspec.GitIgnoreSpec.from_lines(exclude_patterns)
    )
