# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections
import collections.abc
import datetime
import decimal
import json
import re
import typing

import pydantic
import pydantic_core

from ..collection_utils import get_by_path
from ..compat import StrEnum

ConditionValue = typing.Optional[typing.Union[str, bool, int, float, decimal.Decimal, datetime.datetime]]


def _like_matches(pattern: str, text: str) -> bool:
    """Match ``text`` against a SQL ``LIKE`` pattern with Postgres semantics.

    ``%`` matches any run of zero or more characters (newlines included), ``_`` exactly one
    character, and a backslash makes the next character literal (a trailing lone backslash is
    itself literal). Matching is case-sensitive and anchored at both ends.

    This is a two-pointer wildcard matcher rather than a translation to ``re``: with each ``%``
    compiled to ``.*``, a failing match backtracks over every split of the text between
    wildcards, so a dozen ``%`` in a user-authored pattern never finishes. Retrying only from
    the most recent ``%`` is sufficient for ``LIKE`` and bounds the work by
    ``len(text) * len(pattern)``.
    """
    p = 0
    t = 0
    # After a mismatch, resume just past the most recent ``%`` with it absorbing one more character.
    star_p = -1
    star_t = 0

    while t < len(text):
        if p < len(pattern) and pattern[p] == "%":
            p += 1
            star_p = p
            star_t = t
            continue

        if p < len(pattern):
            if pattern[p] == "\\":
                literal = pattern[p + 1] if p + 1 < len(pattern) else "\\"
                width = 2 if p + 1 < len(pattern) else 1
                if text[t] == literal:
                    p += width
                    t += 1
                    continue
            elif pattern[p] == "_" or pattern[p] == text[t]:
                p += 1
                t += 1
                continue

        if star_p < 0:
            return False

        star_t += 1
        p = star_p
        t = star_t

    while p < len(pattern) and pattern[p] == "%":
        p += 1

    return p == len(pattern)


class Comparator(StrEnum):
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
        elif self is Comparator.GreaterThan:
            return ">"
        elif self is Comparator.GreaterThanOrEqual:
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


class FieldTarget(typing.NamedTuple):
    """An immutable field path with an optional resource type hint for query interpretation.

    FieldTarget pairs a field path with an optional resource qualifier to help the query
    system resolve which resource type the field belongs to (dataset, file, topic, or message_path).
    When the resource is omitted, the query context infers it.

    Examples:
        >>> target = FieldTarget("org_id", "dataset")
        >>> target.path
        'org_id'
        >>> target.resource
        'dataset'

        >>> target = FieldTarget("metadata.min", None)
        >>> target.resource is None
        True
    """

    path: str
    """Field path within the target resource, using dot notation for nested fields."""

    resource: typing.Optional[typing.Literal["dataset", "file", "topic", "message_path"]]
    """Optional resource type hint to disambiguate field path interpretation."""


class Field(str):
    """A string-like field path that parses resource qualifiers and extracts the target path.

    Field extends str to provide automatic parsing of qualified field paths like
    "dataset.metadata.owner" or "topic.name" into their constituent parts. It identifies
    the target resource type (dataset, file, topic, or message_path) and extracts the
    actual field path within that resource.

    The class supports both qualified paths (e.g., "dataset.org_id") and unqualified paths
    (e.g., "org_id"). For qualified paths, it strips the resource prefix and stores both
    the original fully qualified path and the extracted target information.

    Examples:
        >>> field = Field("dataset.metadata.foo")
        >>> field.target.resource
        'dataset'
        >>> field.target.path
        'metadata.foo'

        >>> field = Field("org_id")
        >>> field.target.resource is None
        True
        >>> field.target.path
        'org_id'
    """

    __MESSAGE_PATH_REGEX: typing.ClassVar[re.Pattern] = re.compile(r"msgpath[.](?P<msgpath_property>.+)")
    __TOPIC_REGEX: typing.ClassVar[re.Pattern] = re.compile(r"(?:msgpath[.])?topic[.](?P<topic_property>.+)")
    __FILE_REGEX: typing.ClassVar[re.Pattern] = re.compile(r"(?:msgpath[.])?(?:topic[.])?file[.](?P<file_property>.+)")
    __DATASET_REGEX: typing.ClassVar[re.Pattern] = re.compile(
        r"(?:msgpath[.])?(?:topic[.])?(?:file[.])?dataset[.](?P<dataset_property>.+)"
    )

    __fully_qualified_path: str
    __target_path: str
    __target_resource: typing.Optional[typing.Literal["dataset", "file", "topic", "message_path"]] = None

    @classmethod
    def wrap(cls, field: typing.Union[str, "Field"]) -> Field:
        if isinstance(field, Field):
            return field
        else:
            return cls(field)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: typing.Any, handler: pydantic.GetCoreSchemaHandler
    ) -> pydantic_core.CoreSchema:
        """Define the Pydantic core schema for validation.

        This follows the pattern from _SecretField in pydantic/types.py:
        (https://github.com/pydantic/pydantic/blob/f42171c760d43b9522fde513ae6e209790f7fefb/pydantic/types.py#L1746C7-L1746C19)
        """

        def get_json_schema(
            _core_schema: pydantic_core.CoreSchema,
            handler: pydantic.GetJsonSchemaHandler,
        ) -> pydantic.json_schema.JsonSchemaValue:
            return handler(pydantic_core.core_schema.str_schema())

        def get_schema(strict: bool) -> pydantic_core.CoreSchema:
            # Create inner schema with strict mode
            inner_schema = {**pydantic_core.core_schema.str_schema(), "strict": strict}

            # JSON schema: validate string, then construct Field instance
            json_schema = pydantic_core.core_schema.no_info_after_validator_function(
                cls,
                inner_schema,  # type: ignore[arg-type]
            )

            return pydantic_core.core_schema.json_or_python_schema(
                python_schema=pydantic_core.core_schema.union_schema(
                    [
                        # Accept existing Field instances
                        pydantic_core.core_schema.is_instance_schema(cls),
                        # Or validate and construct from string
                        json_schema,
                    ],
                    custom_error_type="string_type",
                ),
                json_schema=json_schema,
                serialization=pydantic_core.core_schema.to_string_ser_schema(),
            )

        # Return lax or strict schema based on mode
        return pydantic_core.core_schema.lax_or_strict_schema(
            lax_schema=get_schema(strict=False),
            strict_schema=get_schema(strict=True),
            metadata={"pydantic_js_functions": [get_json_schema]},
        )

    def __init__(self, path: str):
        self.__fully_qualified_path = path
        self.__parse()

    @property
    def target(self) -> FieldTarget:
        return FieldTarget(path=self.__target_path, resource=self.__target_resource)

    def __parse(self) -> None:
        dataset_match = self.__DATASET_REGEX.match(self.__fully_qualified_path)
        if dataset_match:
            self.__target_resource = "dataset"
            self.__target_path = dataset_match.group("dataset_property")
            return

        file_match = self.__FILE_REGEX.match(self.__fully_qualified_path)
        if file_match:
            self.__target_resource = "file"
            self.__target_path = file_match.group("file_property")
            return

        topic_match = self.__TOPIC_REGEX.match(self.__fully_qualified_path)
        if topic_match:
            self.__target_resource = "topic"
            self.__target_path = topic_match.group("topic_property")
            return

        msgpath_match = self.__MESSAGE_PATH_REGEX.match(self.__fully_qualified_path)
        if msgpath_match:
            self.__target_resource = "message_path"
            self.__target_path = msgpath_match.group("msgpath_property")
            return

        self.__target_path = self.__fully_qualified_path


class Condition(pydantic.BaseModel):
    """A filter for any arbitrary attribute for a Roboto resource."""

    field: typing.Annotated[str, Field]
    comparator: Comparator
    value: ConditionValue = None

    @classmethod
    def equals_cond(cls, field: str, value: ConditionValue) -> "Condition":
        return cls(field=field, comparator=Comparator.Equals, value=value)

    def __str__(self):
        base_condition = f"{self.field} {self.comparator.to_compact_string()}"
        if self.value is None:
            return base_condition

        if isinstance(self.value, datetime.datetime):
            return f"{base_condition} {self.value.isoformat()}"

        return f"{base_condition} {json.dumps(self.value)}"

    def __repr__(self):
        return self.model_dump_json()

    def matches(self, target: dict) -> bool:
        field = Field.wrap(self.field)
        target_value = get_by_path(target, field.target.path.split("."))
        my_value = self.value

        if self.comparator in [Comparator.NotExists, Comparator.IsNull]:
            return target_value is None

        if self.comparator in [Comparator.Exists, Comparator.IsNotNull]:
            return target_value is not None

        # We need the value for everything else
        if target_value is None:
            return False

        if isinstance(target_value, str) and not isinstance(my_value, str):
            if isinstance(my_value, int):
                target_value = int(target_value)
            elif isinstance(my_value, float):
                target_value = float(target_value)
            elif isinstance(my_value, bool):
                target_value = target_value.lower() == "true"
            elif isinstance(my_value, decimal.Decimal):
                target_value = decimal.Decimal.from_float(float(target_value))
            elif isinstance(my_value, datetime.datetime):
                target_value = datetime.datetime.fromisoformat(target_value.replace("Z", "+00:00"))

        if isinstance(target_value, datetime.datetime) and isinstance(my_value, str):
            try:
                my_value = datetime.datetime.fromisoformat(my_value.replace("Z", "+00:00"))
            except ValueError:
                return False

            # Comparing naive and aware datetimes raises TypeError for ordering ops.
            if (target_value.tzinfo is None) != (my_value.tzinfo is None):
                return False

        if self.comparator is Comparator.Equals:
            return target_value == my_value

        if self.comparator is Comparator.NotEquals:
            return target_value != my_value

        if self.comparator is Comparator.GreaterThan:
            return target_value > my_value

        if self.comparator is Comparator.GreaterThanOrEqual:
            return target_value >= my_value

        if self.comparator is Comparator.LessThan:
            return target_value < my_value

        if self.comparator is Comparator.LessThanOrEqual:
            return target_value <= my_value

        if self.comparator is Comparator.Contains:
            return isinstance(target_value, collections.abc.Collection) and my_value in target_value

        if self.comparator is Comparator.NotContains:
            return isinstance(target_value, collections.abc.Collection) and my_value not in target_value

        if self.comparator is Comparator.BeginsWith:
            if not isinstance(target_value, str) or not isinstance(my_value, str):
                return False

            return target_value.startswith(my_value)

        if self.comparator in [Comparator.Like, Comparator.NotLike]:
            if not isinstance(target_value, str) or not isinstance(my_value, str):
                return False

            is_like = _like_matches(my_value, target_value)
            return is_like if self.comparator is Comparator.Like else not is_like

        return False

    def target_unspecified(self) -> bool:
        """Is the target resource of this query condition unspecified?"""
        return Field.wrap(self.field).target.resource is None

    def targets_dataset(self) -> bool:
        """Does this query condition target a dataset?"""
        return Field.wrap(self.field).target.resource == "dataset"

    def targets_file(self) -> bool:
        """Does this query condition target a file?"""
        return Field.wrap(self.field).target.resource == "file"

    def targets_topic(self) -> bool:
        """Does this query condition target a topic?"""
        return Field.wrap(self.field).target.resource == "topic"

    def targets_message_path(self) -> bool:
        """Does this query condition target a message path?"""
        return Field.wrap(self.field).target.resource == "message_path"


class ConditionOperator(StrEnum):
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
    conditions: collections.abc.Sequence[ConditionType]

    def matches(self, target: dict | typing.Callable[[ConditionType], bool]):
        if callable(target):
            conditions_match = [target(condition) for condition in self.conditions]
        else:
            conditions_match = [condition.matches(target) for condition in self.conditions]

        if self.operator is ConditionOperator.And:
            return all(conditions_match)

        if self.operator is ConditionOperator.Or:
            return any(conditions_match)

        if self.operator is ConditionOperator.Not:
            return not any(conditions_match)

        return False

    @staticmethod
    def or_group(*conditions: ConditionType) -> "ConditionGroup":
        return ConditionGroup(operator=ConditionOperator.Or, conditions=conditions)

    @staticmethod
    def and_group(*conditions: ConditionType) -> "ConditionGroup":
        return ConditionGroup(operator=ConditionOperator.And, conditions=conditions)

    @pydantic.field_validator("conditions")
    def validate_conditions(cls, v: collections.abc.Sequence[ConditionType]):
        if len(v) == 0:
            raise ValueError("At least one condition must be provided to a ConditionGroup, got 0!")

        return v

    def __str__(self):
        return "(" + f" {self.operator.value} ".join([str(condition) for condition in self.conditions]) + ")"

    def __repr__(self):
        return self.model_dump_json()


ConditionType = typing.Union[Condition, ConditionGroup]
