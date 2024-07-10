# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pytest

from roboto.updates import MetadataChangeset


@pytest.mark.parametrize(
    ["existing_metadata", "put_fields", "remove_fields", "expected"],
    [
        # Add to and remove from nested obj
        (
            {"a": 1, "b": {"c": 2, "d": 3}},
            {"a": 2, "b.c": 3, "b.e": 4},
            ["b.d"],
            {"a": 2, "b": {"c": 3, "e": 4}},
        ),
        # Add to nested obj
        (
            {"a": 1, "b": {"c": 2, "d": 3}},
            {"a": 2, "b.c": 3, "b.e": 4},
            None,
            {"a": 2, "b": {"c": 3, "d": 3, "e": 4}},
        ),
        # Remove from nested obj
        (
            {"a": 1, "b": {"c": 2, "d": 3}},
            None,
            ["b.d"],
            {"a": 1, "b": {"c": 2}},
        ),
        # Removes empty containers
        (
            {"a": 1, "b": {"c": 2}},
            None,
            ["b.c"],
            {"a": 1},
        ),
        (
            {"a": 1, "b": {"c": [2], "d": 3}},
            None,
            ["b.c.0"],
            {"a": 1, "b": {"d": 3}},
        ),
        # No changes
        (
            {"a": 1, "b": {"c": 2, "d": 3}},
            None,
            None,
            {"a": 1, "b": {"c": 2, "d": 3}},
        ),
        (
            {"a": 1, "b": {"c": 2, "d": 3}},
            None,
            ["nonexistent"],
            {"a": 1, "b": {"c": 2, "d": 3}},
        ),
        # Put items into existing list at index
        (
            {"a": 1, "b": {"c": [1, 2, 3]}},
            {"b.c.1": 4},
            None,
            {"a": 1, "b": {"c": [1, 4, 2, 3]}},
        ),
        # Remove items from existing lists at index
        (
            {"a": 1, "b": {"c": [1, 2, 3]}},
            None,
            ["b.c.1"],
            {"a": 1, "b": {"c": [1, 3]}},
        ),
        # Bools and zeros
        (
            {"a": True},
            {"a": False, "b": 0},
            None,
            {"a": False, "b": 0},
        ),
    ],
)
def test_apply_field_updates(existing_metadata, put_fields, remove_fields, expected):
    # Arrange
    changeset = MetadataChangeset(put_fields=put_fields, remove_fields=remove_fields)

    # Act
    actual = changeset.apply_field_updates(existing_metadata)

    # Assert
    assert actual == expected


@pytest.mark.parametrize(
    ["existing_tags", "put_tags", "remove_tags", "expected"],
    [
        # Add to and remove from list
        (["a", "b", "c"], ["d", "e"], ["b", "c"], ["a", "d", "e"]),
        # Add to list
        (["a", "b", "c"], ["d", "e"], None, ["a", "b", "c", "d", "e"]),
        # Remove from list
        (["a", "b", "c"], None, ["b", "c"], ["a"]),
        # No changes
        (["a", "b", "c"], None, None, ["a", "b", "c"]),
        (["a", "b", "c"], None, ["nonexistent"], ["a", "b", "c"]),
        (["a", "b", "c"], ["a", "b", "c"], None, ["a", "b", "c"]),
    ],
)
def test_apply_tag_updates(existing_tags, put_tags, remove_tags, expected):
    # Arrange
    changeset = MetadataChangeset(put_tags=put_tags, remove_tags=remove_tags)

    # Act
    actual = changeset.apply_tag_updates(existing_tags)

    # Assert
    assert actual == expected
