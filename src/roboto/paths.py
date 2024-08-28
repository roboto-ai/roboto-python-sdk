# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

import pathspec

from .query import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionOperator,
)


def path_to_pattern(path: str) -> str:
    """
    Transform a literal path into a Git wildmatch pattern that matches that literal path.
    """
    escaped = path.replace("[", "\\[")
    escaped = escaped.replace("]", "\\]")
    return escaped


def excludespec_from_patterns(
    exclude_patterns: typing.Optional[collections.abc.Iterable[str]] = None,
) -> typing.Optional[pathspec.PathSpec]:
    """
    Transform a list of Git wildmatch patterns into a pathspec.PathSpec.
    """
    return (
        None
        if exclude_patterns is None
        else pathspec.GitIgnoreSpec.from_lines(exclude_patterns)
    )


def pathspec_from_patterns(
    patterns: collections.abc.Iterable[str],
) -> pathspec.PathSpec:
    """
    Transform a list of Git wildmatch patterns into a pathspec.PathSpec.
    """
    return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)


def path_matches(
    path: str,
    include_patterns: typing.Optional[collections.abc.Iterable[str]] = None,
    exclude_patterns: typing.Optional[collections.abc.Iterable[str]] = None,
) -> bool:
    """
    Does the given path match the given include pattern(s) and not match the given exclude pattern(s)?
    """
    # Include patterns are provided, and the file isn't included, ignore it
    if include_patterns is not None:
        if not pathspec_from_patterns(include_patterns).match_file(path):
            return False

    # Exclude pattern is provided, and the file is included, ignore it
    if exclude_patterns is not None:
        if pathspec_from_patterns(exclude_patterns).match_file(path):
            return False

    return True


def pattern_to_like_value(pattern: str) -> str:
    return pattern.replace("**/*", "%").replace("**", "%").replace("*", "%")


def patterns_to_condition_group(
    patterns: collections.abc.Iterable[str],
    path_field_name: str,
    comparator: Comparator,
    operator: ConditionOperator,
) -> ConditionGroup:
    """
    Transform a list of Git wildmatch patterns into a ConditionGroup.
    """
    return ConditionGroup(
        conditions=[
            Condition(
                field=path_field_name,
                comparator=comparator,
                value=pattern_to_like_value(pattern),
            )
            for pattern in patterns
        ],
        operator=operator,
    )
