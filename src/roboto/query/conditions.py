# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import decimal
import enum
import json
import typing

import pydantic

from ..collection_utils import get_by_path

ConditionValue = typing.Optional[
    typing.Union[str, bool, int, float, decimal.Decimal, datetime.datetime]
]


class Comparator(str, enum.Enum):
    """The comparator to use when comparing a field to a value."""

    Equals = "EQUALS"
    NotEquals = "NOT_EQUALS"
    GreaterThan = "GREATER_THAN"
    GreaterThanOrEqual = "GREATER_THAN_OR_EQUAL"
    LessThan = "LESS_THAN"
    LessThanOrEqual = "LESS_THAN_OR_EQUAL"
    Contains = "CONTAINS"
    NotContains = "NOT_CONTAINS"
    IsNull = "IS_NULL"
    IsNotNull = "IS_NOT_NULL"
    Exists = "EXISTS"
    NotExists = "NOT_EXISTS"
    BeginsWith = "BEGINS_WITH"
    Like = "LIKE"  # SQL Syntax
    NotLike = "NOT_LIKE"  # SQL Syntax

    def to_compact_string(self):
        if self is Comparator.Equals:
            return "="
        elif self is Comparator.NotEquals:
            return "!="
        elif self is Comparator.GreaterThanOrEqual:
            return ">"
        elif self is Comparator.GreaterThan:
            return ">="
        elif self is Comparator.LessThan:
            return "<"
        elif self is Comparator.LessThanOrEqual:
            return "<="
        else:
            return self.value

    @staticmethod
    def from_string(value: str) -> "Comparator":
        as_comparator: typing.Optional[Comparator] = {
            "EQUALS": Comparator.Equals,
            "=": Comparator.Equals,
            "NOT_EQUALS": Comparator.NotEquals,
            "!=": Comparator.NotEquals,
            "GREATER_THAN": Comparator.GreaterThan,
            ">": Comparator.GreaterThan,
            "GREATER_THAN_OR_EQUAL": Comparator.GreaterThanOrEqual,
            ">=": Comparator.GreaterThanOrEqual,
            "LESS_THAN": Comparator.LessThan,
            "<": Comparator.LessThan,
            "LESS_THAN_OR_EQUAL": Comparator.LessThanOrEqual,
            "<=": Comparator.LessThanOrEqual,
            "CONTAINS": Comparator.Contains,
            "NOT_CONTAINS": Comparator.NotContains,
            "IS_NULL": Comparator.IsNull,
            "IS_NOT_NULL": Comparator.IsNotNull,
            "EXISTS": Comparator.Exists,
            "NOT_EXISTS": Comparator.NotExists,
            "BEGINS_WITH": Comparator.BeginsWith,
            "LIKE": Comparator.Like,
            "NOT_LIKE": Comparator.NotLike,
        }.get(value.upper())

        if as_comparator is None:
            raise ValueError(f"Unrecognized comparator {value}")

        return as_comparator


class Condition(pydantic.BaseModel):
    """A filter for any arbitrary attribute for a Roboto resource."""

    field: str
    comparator: Comparator
    value: ConditionValue = None

    def matches(self, target: dict) -> bool:
        value = get_by_path(target, self.field.split("."))

        if self.comparator in [Comparator.NotExists, Comparator.IsNull]:
            return value is None

        if self.comparator in [Comparator.Exists, Comparator.IsNotNull]:
            return value is not None

        # We need the value for everything else
        if value is None:
            return False

        if isinstance(value, str) and not isinstance(self.value, str):
            if isinstance(self.value, int):
                value = int(value)
            elif isinstance(self.value, float):
                value = float(value)
            elif isinstance(self.value, bool):
                value = value.lower() == "true"
            elif isinstance(self.value, decimal.Decimal):
                value = decimal.Decimal.from_float(float(value))
            elif isinstance(self.value, datetime.datetime):
                value = datetime.datetime.fromisoformat(value)

        if self.comparator is Comparator.Equals:
            return value == self.value

        if self.comparator is Comparator.NotEquals:
            return value != self.value

        if self.comparator is Comparator.GreaterThan:
            return value > self.value

        if self.comparator is Comparator.GreaterThanOrEqual:
            return value >= self.value

        if self.comparator is Comparator.LessThan:
            return value < self.value

        if self.comparator is Comparator.LessThanOrEqual:
            return value <= self.value

        if self.comparator is Comparator.Contains:
            return isinstance(value, list) and self.value in value

        if self.comparator is Comparator.NotContains:
            return isinstance(value, list) and self.value not in value

        if self.comparator is Comparator.BeginsWith:
            if not isinstance(value, str) or not isinstance(self.value, str):
                return False

            return value.startswith(self.value)

        return False

    def __str__(self):
        base_condition = f"{self.field} {self.comparator.to_compact_string()}"
        if self.value is None:
            return base_condition

        if isinstance(self.value, datetime.datetime):
            return f"{base_condition} {self.value.isoformat()}"

        return f"{base_condition} {json.dumps(self.value)}"

    def __repr__(self):
        return self.model_dump_json()

    @classmethod
    def equals_cond(cls, field: str, value: ConditionValue) -> "Condition":
        return cls(field=field, comparator=Comparator.Equals, value=value)


class ConditionOperator(str, enum.Enum):
    """The operator to use when combining multiple conditions."""

    And = "AND"
    Or = "OR"
    Not = "NOT"

    @staticmethod
    def from_string(value: str) -> "ConditionOperator":
        if value.lower() == "and":
            return ConditionOperator.And
        elif value.lower() == "or":
            return ConditionOperator.Or
        elif value.lower() == "not":
            return ConditionOperator.Not

        raise ValueError(f"Unrecognized Operator {value}")


class ConditionGroup(pydantic.BaseModel):
    """A group of conditions that are combined together."""

    operator: ConditionOperator
    conditions: collections.abc.Sequence[typing.Union[Condition, "ConditionGroup"]]

    def matches(self, target: dict):
        inner_matches = map(lambda x: x.matches(target), self.conditions)

        if self.operator is ConditionOperator.And:
            return all(inner_matches)

        if self.operator is ConditionOperator.Or:
            return any(inner_matches)

        if self.operator is ConditionOperator.Not:
            return not any(inner_matches)

        return False

    @staticmethod
    def or_group(
        *conditions: typing.Union[Condition, "ConditionGroup"]
    ) -> "ConditionGroup":
        return ConditionGroup(operator=ConditionOperator.Or, conditions=conditions)

    @staticmethod
    def and_group(
        *conditions: typing.Union[Condition, "ConditionGroup"]
    ) -> "ConditionGroup":
        return ConditionGroup(operator=ConditionOperator.And, conditions=conditions)

    @pydantic.field_validator("conditions")
    def validate_conditions(
        cls, v: collections.abc.Sequence[typing.Union[Condition, "ConditionGroup"]]
    ):
        if len(v) == 0:
            raise ValueError(
                "At least one condition must be provided to a ConditionGroup, got 0!"
            )

        return v

    def __str__(self):
        return (
            "("
            + f" {self.operator.value} ".join(
                [str(condition) for condition in self.conditions]
            )
            + ")"
        )

    def __repr__(self):
        return self.model_dump_json()


ConditionType = typing.Union[Condition, ConditionGroup]
