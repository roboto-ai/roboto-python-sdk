# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pytest

from roboto.serde import safe_dict_drill


@pytest.mark.parametrize(
    "target,keys,expected",
    [
        ({}, ["key"], None),
        ({"key": "value"}, ["key"], "value"),
        ({"key": "value"}, ["key", "inner"], None),
        ({"topKey": {"innerKey": "value"}}, ["topKey", "innerKey"], "value"),
    ],
)
def test_safe_dict_drill(target, keys, expected):
    assert safe_dict_drill(target, keys) == expected
