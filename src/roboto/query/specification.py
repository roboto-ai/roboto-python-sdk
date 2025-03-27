# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import typing

import pydantic
from pydantic import ConfigDict

from .conditions import Condition, ConditionGroup

MAX_PAGE_SIZE: int = 1000
"""Maximum allowable page size for search."""

DEFAULT_PAGE_SIZE: int = 500
"""Default page size for search."""


class SortDirection(str, enum.Enum):
    """The direction to sort the results of a query."""

    Ascending = "ASC"
    Descending = "DESC"

    @staticmethod
    def from_string(value: str) -> "SortDirection":
        lowered = value.lower()

        if lowered == "asc":
            return SortDirection.Ascending
        elif lowered == "desc":
            return SortDirection.Descending
        else:
            raise ValueError(f"Unrecognized sort direction '{value}'")


class QuerySpecification(pydantic.BaseModel):
    """
    Model for specifying a query to the Roboto Platform.

    Examples:
        Specify a query with a single condition:
            >>> from roboto import query
            >>> query_spec = query.QuerySpecification(
            ...     condition=query.Condition(
            ...         field="name",
            ...         comparator=query.Comparator.Equals,
            ...         value="Roboto"
            ...     )
            ... )

        Specify a query with multiple conditions:
            >>> from roboto import query
            >>> query_spec = query.QuerySpecification(
            ...     condition=query.ConditionGroup(
            ...         operator=query.ConditionOperator.And,
            ...         conditions=[
            ...             query.Condition(
            ...                 field="name",
            ...                 comparator=query.Comparator.Equals,
            ...                 value="Roboto"
            ...             ),
            ...             query.Condition(
            ...                 field="age",
            ...                 comparator=query.Comparator.GreaterThan,
            ...                 value=18
            ...             )
            ...         ]
            ...     )
            ... )

        Arbitrarily nest condition groups:
            >>> from roboto import query
            >>> query_spec = query.QuerySpecification(
            ...     condition=query.ConditionGroup(
            ...         operator=query.ConditionOperator.And,
            ...         conditions=[
            ...             query.Condition(
            ...                 field="name",
            ...                 comparator=query.Comparator.Equals,
            ...                 value="Roboto"
            ...             ),
            ...             query.ConditionGroup(
            ...                 operator=query.ConditionOperator.Or,
            ...                 conditions=[
            ...                     query.Condition(
            ...                         field="age",
            ...                         comparator=query.Comparator.GreaterThan,
            ...                         value=18
            ...                     ),
            ...                     query.Condition(
            ...                         field="age",
            ...                         comparator=query.Comparator.LessThan,
            ...                         value=30
            ...                     )
            ...                 ]
            ...             )
            ...         ]
            ...     )
            ... )
    """

    condition: typing.Optional[typing.Union[Condition, ConditionGroup]] = None
    """
    Query condition(s) to evaluate when looking up Roboto entities.
    """

    limit: int = MAX_PAGE_SIZE
    """
    Page size for returned results. Optional, default is ``MAX_PAGE_SIZE``.
    """

    after: typing.Optional[str] = None
    """
    Encoded next page token. Optional.
    """

    sort_by: typing.Optional[str] = None
    """
    Field to sort results by. Optional, defaults to created date (``created``).
    """

    sort_direction: typing.Optional[SortDirection] = None
    """
    Sort direction for query results. Optional, defaults to "descending".
    """

    model_config = ConfigDict(extra="ignore")

    def fields(self) -> set[str]:
        """Return a set of all fields referenced in the query."""
        fields = set()

        def _iterconditions(
            condition: typing.Optional[typing.Union[Condition, ConditionGroup]]
        ):
            if condition is None:
                return

            if isinstance(condition, Condition):
                fields.add(condition.field)
            else:
                for cond in condition.conditions:
                    _iterconditions(cond)

        _iterconditions(self.condition)
        return fields
