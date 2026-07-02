# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import functools
import typing

T = typing.TypeVar("T")


def get_by_path(
    target: collections.abc.Mapping[typing.Any, typing.Any],
    key_path: collections.abc.Sequence[typing.Any],
) -> typing.Any:
    """
    Access a key path in a mapping.
    Returns ``None`` if any part of the path is not found or traverses through an object that is not a mapping.
    """
    try:
        return functools.reduce(lambda d, key: d.get(key, None), key_path, target)
    except (TypeError, AttributeError):
        return None


class defaultlist(list[T], typing.Generic[T]):
    """Like collections.defaultdict, but for list.

    Automatically supplies a default value when you access an index that hasn't been set or is out of bounds,
    without raising an IndexError.

    Examples:
        >>> dl = defaultlist[int](factory=lambda: 0)
        >>> dl[5] += 1  # Automatically extends list with 0s up to index 5
        >>> print(dl)  # [0, 0, 0, 0, 0, 1]
    """

    def __init__(self, factory: typing.Callable[[], T]):
        self.factory = factory
        super().__init__()

    @typing.overload
    def __getitem__(self, idx: typing.SupportsIndex) -> T: ...

    @typing.overload
    def __getitem__(self, idx: slice) -> list[T]: ...

    def __getitem__(self, idx: typing.Union[typing.SupportsIndex, slice]) -> typing.Union[T, list[T]]:
        if isinstance(idx, slice):
            return super().__getitem__(idx)
        # Convert SupportsIndex to int for comparison
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
            # Convert SupportsIndex to int for comparison
            index = idx.__index__()
            while index >= len(self):
                self.append(self.factory())
            super().__setitem__(idx, typing.cast(T, value))
