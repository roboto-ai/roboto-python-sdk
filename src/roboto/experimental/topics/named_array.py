# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import functools
import itertools
import keyword
import operator
import typing


class NamedArray(tuple):
    """Value of an array field whose elements are named, as ``Topic.get_data`` yields it.

    A named array is a ``tuple`` of the array's values, with one subclass per list of names. Everything a tuple does
    works unchanged: indexing by position (``a[5]``) and by slice (``a[2:4]``, which returns a ``tuple`` without the
    names), ``len(a)``, iteration over its values, ``a.index(value)`` and ``a.count(value)``. It compares and hashes as
    a tuple of its values, so it equals a ``tuple`` holding the same values. It can be pickled, and unpickles as a named
    array with the same names.

    It adds the names, with the methods of a ``collections.namedtuple``:

    - ``a["main_gripper"]`` returns the element of that name, for any name; a name the array lacks raises ``KeyError``.
    - ``a.main_gripper`` does too, when the name is a Python identifier, not a keyword, does not start with an
      underscore, and is not already an attribute of a named array (such as ``index`` or ``count``).
    - ``a._fields`` lists the names in element order, and ``a._asdict()`` maps each name to its value.
    - ``a._replace(main_gripper=0.0)`` returns a copy with new values for the elements named, and
      ``type(a)(**a._asdict())`` builds an equal copy; both take any name as a keyword.

    Raises:
        TypeError: Building a named array, or calling ``_replace``, gives too many or too few values, a name the array
            lacks, or a value for one element twice.

    Examples:
        >>> from roboto.experimental.sessions import Session
        >>> topic = Session.from_id("se_abc123").get_topic("action")  # doctest: +SKIP
        >>> timestamp, record = next(topic.get_data())  # doctest: +SKIP
        >>> action = record["action"]  # doctest: +SKIP
        >>> action[5] == action.main_gripper == action["main_gripper"]  # doctest: +SKIP
        True
    """

    __slots__ = ()

    _fields: typing.ClassVar[tuple[str, ...]]
    _index_by_name: typing.ClassVar[dict[str, int]]

    def __new__(cls, /, *values: typing.Any, **values_by_name: typing.Any) -> NamedArray:
        if not values_by_name:
            return cls._make(values)
        if len(values) > len(cls._fields):
            raise TypeError(f"Expected {len(cls._fields)} values, got {len(values)}")
        by_name = dict(zip(cls._fields, values))
        for name, value in values_by_name.items():
            if name not in cls._index_by_name or name in by_name:
                raise TypeError(f"Unexpected or repeated element name {name!r}")
            by_name[name] = value
        missing = [name for name in cls._fields if name not in by_name]
        if missing:
            raise TypeError(f"Missing values for the elements {missing!r}")
        return tuple.__new__(cls, [by_name[name] for name in cls._fields])

    def __getitem__(self, key: typing.Any) -> typing.Any:  # type: ignore[override]
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index_by_name[key])
        return tuple.__getitem__(self, key)

    @classmethod
    def _make(cls, iterable: collections.abc.Iterable[typing.Any]) -> NamedArray:
        values = tuple(iterable)
        if len(values) != len(cls._fields):
            raise TypeError(f"Expected {len(cls._fields)} values, got {len(values)}")
        return tuple.__new__(cls, values)

    def _asdict(self) -> dict[str, typing.Any]:
        return dict(zip(self._fields, self))

    def _replace(self, /, **changes: typing.Any) -> NamedArray:
        return type(self)(**{**self._asdict(), **changes})

    def __repr__(self) -> str:
        values = ", ".join(f"{name}={value!r}" for name, value in zip(self._fields, self))
        return f"NamedArray({values})"

    def __reduce__(self) -> tuple[typing.Any, ...]:
        """Pickle as the element names and values, which unpickling passes to ``named_array_type``.

        Each subclass is built at run time and cannot be imported by name, so pickle cannot restore it by reference.
        """
        return _rebuild, (self._fields, tuple(self))


@functools.cache
def named_array_type(element_names: tuple[str, ...]) -> type[NamedArray]:
    """Return the ``NamedArray`` subclass for ``element_names``, the same class for equal names.

    Args:
        element_names: Name of each element of the array, in element order; at least one, each distinct.
    """
    attributes = {
        name: property(operator.itemgetter(index))
        for index, name in enumerate(element_names)
        if name.isidentifier()
        and not keyword.iskeyword(name)
        and not name.startswith("_")
        and not hasattr(NamedArray, name)
    }
    return type(
        "NamedArray",
        (NamedArray,),
        {
            "__slots__": (),
            "_fields": element_names,
            "_index_by_name": {name: index for index, name in enumerate(element_names)},
            # In a match statement's class pattern, positional sub-pattern i reads the attribute named
            # __match_args__[i]. Listing only the names before the first name without an attribute keeps
            # sub-pattern i on element i.
            "__match_args__": tuple(itertools.takewhile(attributes.__contains__, element_names)),
            **attributes,
        },
    )


def _rebuild(element_names: tuple[str, ...], values: tuple[typing.Any, ...]) -> NamedArray:
    return named_array_type(element_names)._make(values)
