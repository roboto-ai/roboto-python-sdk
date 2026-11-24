# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import functools
import typing

T = typing.TypeVar("T")
"""Type of the values a ``defaultlist`` holds."""


def get_by_path(
    target: collections.abc.Mapping[typing.Any, typing.Any],
    key_path: collections.abc.Sequence[typing.Any],
) -> typing.Any:
    """Return the value at the end of a path of keys through nested mappings.

    Args:
        target: Mapping to read from.
        key_path: Keys to follow, outermost first. An empty sequence returns ``target`` itself.

    Returns:
        The value at the end of the path, or ``None`` when a key along it is missing, unhashable, or reached through a
        value that is not a mapping. A ``None`` stored at the end of the path is returned the same way, so the result
        does not tell a missing key from a stored ``None``.

    Examples:
        >>> get_by_path({"error": {"error_code": "NOT_FOUND"}}, ["error", "error_code"])
        'NOT_FOUND'
        >>> get_by_path({"error": "Not found"}, ["error", "error_code"]) is None
        True
    """
    try:
        return functools.reduce(lambda d, key: d.get(key, None), key_path, target)
    except (TypeError, AttributeError):
        return None


class defaultlist(list[T], typing.Generic[T]):
    """List that extends itself to any non-negative index read or written, filling new positions from a factory.

    It works as ``collections.defaultdict`` does for keys: reading or writing an index past the end appends a value
    from ``factory`` for each missing position, then reads or writes that index, instead of raising ``IndexError``.
    ``factory`` is called once per new position, so mutable values such as dictionaries are not shared between
    positions. Negative indexes and slices behave as they do on a ``list``.

    Examples:
        >>> dl = defaultlist[int](factory=lambda: 0)
        >>> dl[5] += 1
        >>> print(dl)
        [0, 0, 0, 0, 0, 1]
    """

    def __init__(self, factory: typing.Callable[[], T]):
        self.factory = factory
        """Function that takes no arguments and returns the value for a new position."""
        super().__init__()

    @typing.overload
    def __getitem__(self, idx: typing.SupportsIndex) -> T: ...

    @typing.overload
    def __getitem__(self, idx: slice) -> list[T]: ...

    def __getitem__(self, idx: typing.Union[typing.SupportsIndex, slice]) -> typing.Union[T, list[T]]:
        if isinstance(idx, slice):
            return super().__getitem__(idx)
        index = idx.__index__()
        while index >= len(self):
            self.append(self.factory())
        return super().__getitem__(idx)

    @typing.overload
    def __setitem__(self, idx: typing.SupportsIndex, value: T) -> None: ...

    @typing.overload
    def __setitem__(self, idx: slice, value: typing.Iterable[T]) -> None: ...

    def __setitem__(
        self,
        idx: typing.Union[typing.SupportsIndex, slice],
        value: typing.Union[T, typing.Iterable[T]],
    ) -> None:
        if isinstance(idx, slice):
            super().__setitem__(idx, typing.cast(typing.Iterable[T], value))
        else:
            index = idx.__index__()
            while index >= len(self):
                self.append(self.factory())
            super().__setitem__(idx, typing.cast(T, value))
