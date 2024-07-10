# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import decimal

import pytest

from roboto.query import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionOperator,
    QuerySpecification,
)


@pytest.mark.parametrize(
    ["spec"],
    [
        (
            {
                "condition": {"field": "name", "comparator": "EQUALS", "value": "test"},
                "limit": 10,
                "after": "page_token",
                "sort_by": "name",
                "sort_direction": "ASC",
            },
        ),
        (
            {
                "condition": {"field": "name", "comparator": "EQUALS", "value": "test"},
            },
        ),
        (
            {
                "condition": {"field": "name", "comparator": "EQUALS", "value": 20},
            },
        ),
        (
            {
                "condition": {"field": "name", "comparator": "EQUALS", "value": 20.20},
            },
        ),
        (
            {
                "condition": {
                    "field": "name",
                    "comparator": "EQUALS",
                    "value": decimal.Decimal("20.20"),
                },
            },
        ),
        (
            {
                "condition": {"field": "name", "comparator": "EQUALS", "value": False},
            },
        ),
        (
            {
                "condition": {
                    "operator": "AND",
                    "conditions": [
                        {"field": "name", "comparator": "EQUALS", "value": "test"},
                        {
                            "field": "not_name",
                            "comparator": "EQUALS",
                            "value": "not_test",
                        },
                    ],
                },
            },
        ),
    ],
)
def test_query_specification_parsing(spec: dict):
    # Arrange / Act / Assert
    # This test only tests that the parsing does not raise an exception
    QuerySpecification.model_validate(spec)


NOMINAL_TEST_CONDITION_MATCH_TARGET = {
    "basicint": 50,
    "basicstr": "hello",
    "basicarray": ["one", "two", "three"],
    "nested": {"basicstr": "hello_nested", "basicarray": ["one", "two", "three"]},
}


@pytest.mark.parametrize(
    ["condition", "target", "expected"],
    [
        # Basic Operations
        (
            Condition(field="does_not_exist", comparator=Comparator.Exists),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="does_not_exist", comparator=Comparator.NotExists),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="does_not_exist", comparator=Comparator.IsNotNull),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="does_not_exist", comparator=Comparator.IsNull),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="basicstr", comparator=Comparator.Exists),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="basicstr", comparator=Comparator.NotExists),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicstr", comparator=Comparator.IsNotNull),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="basicstr", comparator=Comparator.IsNull),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="notfound", comparator=Comparator.Equals, value=50),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.Equals, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.Equals, value=50),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="notfound", comparator=Comparator.NotEquals, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.NotEquals, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="basicint", comparator=Comparator.NotEquals, value=50),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="notfound", comparator=Comparator.GreaterThan, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.GreaterThan, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="basicint", comparator=Comparator.GreaterThan, value=50),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.GreaterThan, value=51),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(
                field="notfound", comparator=Comparator.GreaterThanOrEqual, value=49
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(
                field="basicint", comparator=Comparator.GreaterThanOrEqual, value=49
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(
                field="basicint", comparator=Comparator.GreaterThanOrEqual, value=50
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(
                field="basicint", comparator=Comparator.GreaterThanOrEqual, value=51
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="notfound", comparator=Comparator.LessThan, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.LessThan, value=49),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.LessThan, value=50),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.LessThan, value=51),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(
                field="notfound", comparator=Comparator.LessThanOrEqual, value=49
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(
                field="basicint", comparator=Comparator.LessThanOrEqual, value=49
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(
                field="basicint", comparator=Comparator.LessThanOrEqual, value=50
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(
                field="basicint", comparator=Comparator.LessThanOrEqual, value=51
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        # String Operations
        (
            Condition(field="notfound", comparator=Comparator.BeginsWith, value="he"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.BeginsWith, value="he"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicstr", comparator=Comparator.BeginsWith, value="he"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(field="basicstr", comparator=Comparator.BeginsWith, value="llo"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        # Array Operations
        (
            Condition(field="notfound", comparator=Comparator.Contains, value="one"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicint", comparator=Comparator.Contains, value="one"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(field="basicarray", comparator=Comparator.Contains, value="one"),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(
                field="basicarray", comparator=Comparator.Contains, value="not_one"
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        # Nested Access Works (With Base Cases)
        (
            Condition(field="nested.notfound", comparator=Comparator.Exists),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            Condition(
                field="nested.basicstr",
                comparator=Comparator.Equals,
                value="hello_nested",
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            Condition(
                field="nested.basicarray", comparator=Comparator.Contains, value="one"
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
    ],
)
def test_condition_match(condition, target, expected):
    assert condition.matches(target) == expected


@pytest.mark.parametrize(
    ["condition_group", "target", "expected"],
    [
        (
            ConditionGroup(
                operator=ConditionOperator.Not,
                conditions=[Condition(field="basicstr", comparator=Comparator.Exists)],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            ConditionGroup(
                operator=ConditionOperator.Not,
                conditions=[Condition(field="not_found", comparator=Comparator.Exists)],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            ConditionGroup(
                operator=ConditionOperator.And,
                conditions=[
                    Condition(field="basicstr", comparator=Comparator.Exists),
                    Condition(field="basicint", comparator=Comparator.Exists),
                ],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            ConditionGroup(
                operator=ConditionOperator.And,
                conditions=[
                    Condition(field="basicstr", comparator=Comparator.Exists),
                    Condition(field="notfound", comparator=Comparator.Exists),
                ],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            ConditionGroup(
                operator=ConditionOperator.Or,
                conditions=[
                    Condition(field="basicstr", comparator=Comparator.Exists),
                    Condition(field="notfound", comparator=Comparator.Exists),
                ],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
        (
            ConditionGroup(
                operator=ConditionOperator.Or,
                conditions=[
                    Condition(field="alsonotfound", comparator=Comparator.Exists),
                    Condition(field="notfound", comparator=Comparator.Exists),
                ],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            False,
        ),
        (
            ConditionGroup(
                operator=ConditionOperator.And,
                conditions=[
                    ConditionGroup(
                        operator=ConditionOperator.Or,
                        conditions=[
                            Condition(field="basicstr", comparator=Comparator.Exists),
                            Condition(field="notfound", comparator=Comparator.Exists),
                        ],
                    ),
                    Condition(field="basicarray", comparator=Comparator.Exists),
                ],
            ),
            NOMINAL_TEST_CONDITION_MATCH_TARGET,
            True,
        ),
    ],
)
def test_condition_group_match(condition_group, target, expected):
    assert condition_group.matches(target) == expected
