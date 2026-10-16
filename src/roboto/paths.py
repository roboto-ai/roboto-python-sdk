# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

import pathspec

from .exceptions import RobotoIllegalArgumentException
from .query import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionOperator,
)

DOTFILE_PATTERN = ".**"
"""Git wildmatch pattern for a path with any component that starts with a dot, e.g. ``.env`` or
``.cache/run.bag``. Triggers never run on these files, and file listings leave them out."""


def join_within(directory: pathlib.Path, relative_path: str) -> pathlib.Path:
    """Return ``directory / relative_path``, refusing a path that resolves outside ``directory``.

    A file's stored path comes from the server and is not trusted to stay inside the directory it is written to.

    Raises:
        RobotoIllegalArgumentException: ``relative_path`` is absolute or climbs out of ``directory``.
    """
    destination = directory / relative_path
    if not destination.resolve().is_relative_to(directory.resolve()):
        raise RobotoIllegalArgumentException(f"File path '{relative_path}' resolves outside '{directory}'")
    return destination


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
    return None if exclude_patterns is None else pathspec.GitIgnoreSpec.from_lines(exclude_patterns)


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
    return path_matches_specs(
        path,
        include_spec=None if include_patterns is None else pathspec_from_patterns(include_patterns),
        exclude_spec=None if exclude_patterns is None else pathspec_from_patterns(exclude_patterns),
    )


def path_matches_specs(
    path: str,
    include_spec: typing.Optional[pathspec.PathSpec] = None,
    exclude_spec: typing.Optional[pathspec.PathSpec] = None,
) -> bool:
    """
    :func:`path_matches` for patterns already compiled with :func:`pathspec_from_patterns`, for callers that
    match many paths against the same patterns.
    """
    # Include patterns are provided, and the file isn't included, ignore it
    if include_spec is not None and not include_spec.match_file(path):
        return False

    # Exclude pattern is provided, and the file is included, ignore it
    if exclude_spec is not None and exclude_spec.match_file(path):
        return False

    return True


_DOTFILE_SPEC = pathspec_from_patterns([DOTFILE_PATTERN])


def is_dotfile_path(path: str) -> bool:
    """Whether ``path`` matches :data:`DOTFILE_PATTERN`."""
    return _DOTFILE_SPEC.match_file(path)


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

    ``patterns`` must be non-empty. An empty iterable yields a zero-condition group, which
    ``ConditionGroup`` rejects with a ``ValueError``; callers treat an empty pattern list as
    no filter and skip this call rather than passing it through.
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
