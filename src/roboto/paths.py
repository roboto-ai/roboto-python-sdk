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
"""Gitignore-style pattern that matches a path with any component starting with a dot, such as ``.env``.

It also matches ``.cache/run.bag`` and ``logs/.tmp/run.bag``. Triggers never run on files whose paths match it.
"""


def join_within(directory: pathlib.Path, relative_path: str) -> pathlib.Path:
    """Return ``directory / relative_path``, refusing a path that resolves outside ``directory``.

    :py:meth:`~roboto.domain.files.FileSystem.download_files` checks each file's destination through it, so most code
    never calls it. The check follows symbolic links.

    Args:
        directory: Directory the path must stay within.
        relative_path: Path to join to ``directory``, such as a file's path within its dataset.

    Returns:
        ``directory / relative_path`` as joined, not resolved.

    Raises:
        RobotoIllegalArgumentException: ``relative_path`` resolves outside ``directory``, as ``../notes.txt`` or an
            absolute path elsewhere does.
    """
    destination = directory / relative_path
    if not destination.resolve().is_relative_to(directory.resolve()):
        raise RobotoIllegalArgumentException(f"File path '{relative_path}' resolves outside '{directory}'")
    return destination


def path_to_pattern(path: str) -> str:
    """Return ``path`` with ``[`` and ``]`` escaped, so a Gitignore-style pattern made from it matches them literally.

    Other wildcard characters, such as ``*`` and ``?``, are not escaped and still match as wildcards.

    Args:
        path: Path to escape.
    """
    escaped = path.replace("[", "\\[")
    escaped = escaped.replace("]", "\\]")
    return escaped


def excludespec_from_patterns(
    exclude_patterns: typing.Optional[collections.abc.Iterable[str]] = None,
) -> typing.Optional[pathspec.PathSpec]:
    """Build a ``pathspec.GitIgnoreSpec`` from Gitignore-style patterns.

    :py:meth:`~roboto.domain.files.FileSystem.upload_directory` builds its include and exclude specs through it, so
    most code never calls it.

    Args:
        exclude_patterns: Patterns to compile. ``None`` returns ``None``.

    Returns:
        A spec that matches a path when the patterns select it, as a ``.gitignore`` file with these lines would, or
        ``None`` when ``exclude_patterns`` is ``None``.
    """
    return None if exclude_patterns is None else pathspec.GitIgnoreSpec.from_lines(exclude_patterns)


def pathspec_from_patterns(
    patterns: collections.abc.Iterable[str],
) -> pathspec.PathSpec:
    """Build a ``pathspec.PathSpec`` from Gitignore-style patterns, which matches a path any of them selects.

    A pattern starting with ``!`` stops an earlier pattern from selecting a path, as in a ``.gitignore`` file. An empty
    ``patterns`` matches no path.

    Args:
        patterns: Patterns to compile.
    """
    return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)


def path_matches(
    path: str,
    include_patterns: typing.Optional[collections.abc.Iterable[str]] = None,
    exclude_patterns: typing.Optional[collections.abc.Iterable[str]] = None,
) -> bool:
    """Return whether ``path`` matches an include pattern and no exclude pattern.

    To match many paths against the same patterns, compile them once with ``pathspec_from_patterns`` and call
    ``path_matches_specs``.

    Args:
        path: Path to test, relative to the root the patterns are written against.
        include_patterns: Gitignore-style patterns ``path`` must match one of. ``None`` includes every path; an empty
            list includes none.
        exclude_patterns: Gitignore-style patterns ``path`` must match none of. ``None`` excludes no path.
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
    """Return whether ``path`` matches ``include_spec`` and does not match ``exclude_spec``.

    This is ``path_matches`` for patterns already compiled with ``pathspec_from_patterns``, for callers that match
    many paths against the same patterns.

    Args:
        path: Path to test, relative to the root the patterns are written against.
        include_spec: Spec ``path`` must match. ``None`` includes every path.
        exclude_spec: Spec ``path`` must not match. ``None`` excludes no path.
    """
    if include_spec is not None and not include_spec.match_file(path):
        return False

    if exclude_spec is not None and exclude_spec.match_file(path):
        return False

    return True


_DOTFILE_SPEC = pathspec_from_patterns([DOTFILE_PATTERN])


def is_dotfile_path(path: str) -> bool:
    """Return whether any component of ``path`` starts with a dot, as ``DOTFILE_PATTERN`` matches.

    Roboto calls this when a trigger decides which files to run on. A file whose path it matches is skipped.

    Args:
        path: Path to test, relative to its dataset.
    """
    return _DOTFILE_SPEC.match_file(path)


def pattern_to_like_value(pattern: str) -> str:
    """Return a Gitignore-style pattern as a value for :py:attr:`~roboto.query.Comparator.Like`.

    Each ``**/*``, ``**`` and ``*`` becomes ``%``, which matches any run of characters, ``/`` included, so ``*``
    matches across directories here as ``**`` does. Nothing else is translated: ``?`` and ``[...]`` stay as written, a
    pattern with no wildcard matches only that exact path rather than a file of that name in any directory, and ``_``
    and ``%`` in the pattern act as ``LIKE`` wildcards. ``patterns_to_condition_group`` converts each pattern through
    it, so most code never calls it.

    Args:
        pattern: Pattern to convert.
    """
    return pattern.replace("**/*", "%").replace("**", "%").replace("*", "%")


def patterns_to_condition_group(
    patterns: collections.abc.Iterable[str],
    path_field_name: str,
    comparator: Comparator,
    operator: ConditionOperator,
) -> ConditionGroup:
    """Build a condition group that compares a path field against each of several Gitignore-style patterns.

    Roboto calls this when a caller lists a dataset's files with include or exclude patterns. Roboto treats an empty
    pattern list as no filter and does not call this for it. Each pattern is converted by ``pattern_to_like_value``,
    so it matches as that function describes.

    Args:
        patterns: Patterns to compare against. Must not be empty.
        path_field_name: Name of the field that holds the path, such as ``"relative_path"``.
        comparator: Comparator for each pattern's condition, such as
            :py:attr:`~roboto.query.Comparator.Like` to include matching paths or
            :py:attr:`~roboto.query.Comparator.NotLike` to exclude them.
        operator: Operator that joins the conditions: :py:attr:`~roboto.query.ConditionOperator.Or` to match any
            pattern, or :py:attr:`~roboto.query.ConditionOperator.And` to match all of them.

    Raises:
        pydantic.ValidationError: ``patterns`` is empty, because a condition group needs at least one condition.
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
