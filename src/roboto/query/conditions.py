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
"""Value a condition compares a field with: a string, boolean, number, ``decimal.Decimal``, datetime, or ``None``."""


def _like_matches(pattern: str, text: str) -> bool:
    """Match ``text`` against a SQL ``LIKE`` pattern with Postgres semantics.

    ``%`` matches any run of zero or more characters (newlines included), ``_`` exactly one
    character, and a backslash makes the next character literal (a trailing lone backslash is
    itself literal). Matching is case-sensitive and anchored at both ends.

    The pattern is not translated to a regular expression: with each ``%`` compiled to ``.*``, a
    failing match backtracks over every split of the text between wildcards, so a dozen ``%`` in a
    user-written pattern never finishes. Retrying only from the most recent ``%`` is sufficient for
    ``LIKE`` and bounds the work by ``len(text) * len(pattern)``.
    """
    p = 0
    t = 0
    # After a mismatch, resume just past the most recent `%` with it absorbing one more character.
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
    """Comparator of a condition: how it compares a field's value with the condition's value."""

    Equals = "EQUALS"
    """Field's value equals the condition's value."""

    NotEquals = "NOT_EQUALS"
    """Field's value differs from the condition's value."""

    GreaterThan = "GREATER_THAN"
    """Field's value is greater than the condition's value."""

    GreaterThanOrEqual = "GREATER_THAN_OR_EQUAL"
    """Field's value is greater than or equal to the condition's value."""

    LessThan = "LESS_THAN"
    """Field's value is less than the condition's value."""

    LessThanOrEqual = "LESS_THAN_OR_EQUAL"
    """Field's value is less than or equal to the condition's value."""

    Contains = "CONTAINS"
    """Field's value, a list or string, contains the condition's value."""

    NotContains = "NOT_CONTAINS"
    """Field's value, a list or string, does not contain the condition's value."""

    IsNull = "IS_NULL"
    """Field has no value: it is absent or null."""

    IsNotNull = "IS_NOT_NULL"
    """Field has a value: it is present and not null."""

    Exists = "EXISTS"
    """Field has a value, as with ``IsNotNull``."""

    NotExists = "NOT_EXISTS"
    """Field has no value, as with ``IsNull``."""

    BeginsWith = "BEGINS_WITH"
    """Field's value, a string, begins with the condition's value."""

    Like = "LIKE"
    """Field's value, a string, matches the condition's value as a SQL ``LIKE`` pattern.

    In the pattern, ``%`` matches any run of characters, ``_`` matches one character, and a backslash makes the next
    character literal. Matching is case-sensitive.
    """

    NotLike = "NOT_LIKE"
    """Field's value, a string, does not match the condition's value as a SQL ``LIKE`` pattern."""

    def to_compact_string(self):
        """Render the comparator as its symbol, such as ``>=``, or as its name, such as ``CONTAINS``, if it has none.

        The equality and ordering comparators have symbols: ``=``, ``!=``, ``>``, ``>=``, ``<``, and ``<=``.
        """
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
        """Return the comparator a name, such as ``GREATER_THAN``, or a symbol, such as ``>``, stands for.

        Args:
            value: Comparator name, in any case, or one of the symbols ``=``, ``!=``, ``>``, ``>=``, ``<``, ``<=``.

        Raises:
            ValueError: ``value`` names no comparator.
        """
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
    """A condition's field path, split into the resource it names and the path within that resource.

    ``Field.target`` returns one.
    """

    path: str
    """Path to the field within the resource, with a dot between nested keys, such as ``metadata.foo``."""

    resource: typing.Optional[typing.Literal["dataset", "file", "topic", "message_path"]]
    """Resource the field path names, or ``None`` if it names none.

    A field whose path names no resource is read from the resource the condition is applied to, such as the one a query
    targets.
    """


class Field(str):
    """A condition's field path, as a string that also holds the resource the path names.

    A path that starts with ``dataset.``, ``file.``, ``topic.`` or ``msgpath.`` names that resource, and the rest of
    the path is the field within it: ``dataset.metadata.foo`` is the dataset field ``metadata.foo``. These prefixes
    chain from a message path to its topic, file, and dataset, and the last prefix in the chain names the resource:
    ``msgpath.topic.name`` is the topic field ``name``. A path with none of these prefixes, such as ``org_id``, names no
    resource. The string's value is the path as written, prefixes included.

    Args:
        path: Field path, optionally starting with a resource prefix.
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
        """Return ``field`` unchanged if it is a ``Field`` already, or parse it into one.

        Args:
            field: Field path to wrap.
        """
        if isinstance(field, Field):
            return field
        else:
            return cls(field)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: typing.Any, handler: pydantic.GetCoreSchemaHandler
    ) -> pydantic_core.CoreSchema:
        """Build the pydantic schema that validates a field path into a ``Field``.

        From Python it accepts a ``Field`` or a string, and from JSON a string. It serializes a ``Field`` as its string
        and describes it in JSON Schema as a string.
        """

        def get_json_schema(
            _core_schema: pydantic_core.CoreSchema,
            handler: pydantic.GetJsonSchemaHandler,
        ) -> pydantic.json_schema.JsonSchemaValue:
            return handler(pydantic_core.core_schema.str_schema())

        def get_schema(strict: bool) -> pydantic_core.CoreSchema:
            inner_schema = {**pydantic_core.core_schema.str_schema(), "strict": strict}

            # Validates a string, then parses it into a Field.
            json_schema = pydantic_core.core_schema.no_info_after_validator_function(
                cls,
                inner_schema,  # type: ignore[arg-type]
            )

            return pydantic_core.core_schema.json_or_python_schema(
                python_schema=pydantic_core.core_schema.union_schema(
                    [
                        pydantic_core.core_schema.is_instance_schema(cls),
                        json_schema,
                    ],
                    custom_error_type="string_type",
                ),
                json_schema=json_schema,
                serialization=pydantic_core.core_schema.to_string_ser_schema(),
            )

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
        """Resource the path names, and the path to the field within that resource."""
        return FieldTarget(path=self.__target_path, resource=self.__target_resource)

    def __parse(self) -> None:
        # Try the resources from dataset to message path, so that in a chain of prefixes such as topic.file.name
        # the last prefix names the resource.
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
    """A comparison of one field of a resource with a value, the smallest part of a query's or trigger's condition.

    Combine conditions with ``ConditionGroup``.
    """

    field: typing.Annotated[str, Field]
    """Path of the field to compare, such as ``name`` or ``dataset.metadata.foo``.

    See ``Field`` for the resource prefixes a path can start with.
    """

    comparator: Comparator
    """How to compare the field's value with ``value``."""

    value: ConditionValue = None
    """Value to compare the field's value with.

    Comparators that test only whether the field has a value, such as ``Comparator.Exists``, ignore it.
    """

    @classmethod
    def equals_cond(cls, field: str, value: ConditionValue) -> "Condition":
        """Build a condition that holds when a field's value equals ``value``.

        Args:
            field: Path of the field to compare.
            value: Value the field's value must equal.
        """
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
        """Return whether the condition holds for a record, evaluated without a request to Roboto.

        The field's value is read from ``target`` at the field's path within its resource, with any resource prefix
        removed: ``dataset.metadata.foo`` reads ``target["metadata"]["foo"]``. Before comparing:

        - A missing or ``None`` value makes every comparator false except those that test for no value, such as
          ``Comparator.IsNull``. So ``NotEquals`` does not match a record that lacks the field.
        - A string value is converted to the type of the condition's ``value`` when that is not a string: a number, a
          ``decimal.Decimal``, or a datetime from an ISO 8601 string, which may end in ``Z``.
        - A datetime value compared with a string ``value`` parses ``value`` as ISO 8601. The condition is false when
          ``value`` does not parse, or when only one of the two datetimes has a time zone.

        ``Contains`` and ``NotContains`` are false when the value is not a collection, and ``BeginsWith``,
        ``Like`` and ``NotLike`` are false unless both the value and ``value`` are strings.

        Args:
            target: Record of the resource to evaluate, as a dictionary, such as a dataset record from ``model_dump()``.

        Raises:
            ValueError: A string value cannot be converted to the type of ``value``, such as ``"abc"`` compared with a
                number.
            TypeError: An ordering comparator compares values that cannot be ordered, such as a number and a string.
        """
        field = Field.wrap(self.field)
        target_value = get_by_path(target, field.target.path.split("."))
        my_value = self.value

        if self.comparator in [Comparator.NotExists, Comparator.IsNull]:
            return target_value is None

        if self.comparator in [Comparator.Exists, Comparator.IsNotNull]:
            return target_value is not None

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
        """Return whether the condition's field path names no resource, as ``org_id`` does."""
        return Field.wrap(self.field).target.resource is None

    def targets_dataset(self) -> bool:
        """Return whether the condition's field path names a dataset, as ``dataset.name`` does."""
        return Field.wrap(self.field).target.resource == "dataset"

    def targets_file(self) -> bool:
        """Return whether the condition's field path names a file, as ``file.relative_path`` does."""
        return Field.wrap(self.field).target.resource == "file"

    def targets_topic(self) -> bool:
        """Return whether the condition's field path names a topic, as ``topic.name`` does."""
        return Field.wrap(self.field).target.resource == "topic"

    def targets_message_path(self) -> bool:
        """Return whether the condition's field path names a message path, as ``msgpath.data_type`` does."""
        return Field.wrap(self.field).target.resource == "message_path"


class ConditionOperator(StrEnum):
    """Operator of a condition group: how it combines the group's conditions."""

    And = "AND"
    """Every condition holds."""

    Or = "OR"
    """At least one condition holds."""

    Not = "NOT"
    """No condition holds."""

    @staticmethod
    def from_string(value: str) -> "ConditionOperator":
        """Return the operator a name, such as ``AND``, stands for.

        Args:
            value: ``AND``, ``OR``, or ``NOT``, in any case.

        Raises:
            ValueError: ``value`` names no operator.
        """
        if value.lower() == "and":
            return ConditionOperator.And
        elif value.lower() == "or":
            return ConditionOperator.Or
        elif value.lower() == "not":
            return ConditionOperator.Not

        raise ValueError(f"Unrecognized Operator {value}")


class ConditionGroup(pydantic.BaseModel):
    """A group of conditions combined by one operator, which can hold other groups.

    Building a group raises ``pydantic.ValidationError`` when ``conditions`` is empty.
    """

    operator: ConditionOperator
    """How the group combines ``conditions``."""

    conditions: collections.abc.Sequence[ConditionType]
    """Conditions and nested groups to combine; at least one."""

    def matches(self, target: dict | typing.Callable[[ConditionType], bool]):
        """Return whether the group holds for a record, evaluated without a request to Roboto.

        Every condition in the group is evaluated, then combined by ``operator``.

        Args:
            target: Record of the resource to evaluate each condition against, as a dictionary, with the same meaning
                as in ``Condition.matches``. Or a function that takes each of the group's conditions and returns whether
                it holds, to evaluate them some other way.
        """
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
        """Build a group that holds when at least one of ``conditions`` holds.

        Args:
            conditions: Conditions and nested groups to combine; at least one.
        """
        return ConditionGroup(operator=ConditionOperator.Or, conditions=conditions)

    @staticmethod
    def and_group(*conditions: ConditionType) -> "ConditionGroup":
        """Build a group that holds when every one of ``conditions`` holds.

        Args:
            conditions: Conditions and nested groups to combine; at least one.
        """
        return ConditionGroup(operator=ConditionOperator.And, conditions=conditions)

    @pydantic.field_validator("conditions")
    def validate_conditions(cls, v: collections.abc.Sequence[ConditionType]):
        """Reject a group with no conditions."""
        if len(v) == 0:
            raise ValueError("At least one condition must be provided to a ConditionGroup, got 0!")

        return v

    def __str__(self):
        return "(" + f" {self.operator.value} ".join([str(condition) for condition in self.conditions]) + ")"

    def __repr__(self):
        return self.model_dump_json()


ConditionType = typing.Union[Condition, ConditionGroup]
"""Condition of any kind: one of ``Condition`` and ``ConditionGroup``."""
