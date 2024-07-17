# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import functools
import typing


def get_by_path(
    target: collections.abc.Mapping[typing.Any, typing.Any],
    key_path: collections.abc.Iterable[typing.Any],
) -> typing.Any:
    """
    Access a key path in a mapping.
    Returns `None` if any part of the path is not found or traverses through an object that is not a mapping.
    """
    try:
        return functools.reduce(lambda d, key: d.get(key, None), key_path, target)
    except (TypeError, AttributeError):
        return None
