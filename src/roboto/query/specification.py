# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic
from pydantic import ConfigDict

from ..compat import StrEnum
from .conditions import Condition, ConditionGroup

MAX_PAGE_SIZE: int = 1000
"""Maximum number of results in one page of query results."""

DEFAULT_PAGE_SIZE: int = 50
"""Number of results in one page of query results when the caller sets no page size."""


class SortDirection(StrEnum):
    """Direction to sort query results in."""

    Ascending = "ASC"
    """Smallest or earliest value first."""

    Descending = "DESC"
    """Largest or latest value first."""

    @staticmethod
    def from_string(value: str) -> "SortDirection":
        """Return the sort direction that ``"asc"`` or ``"desc"`` names, in any case.

        Args:
            value: ``"asc"`` or ``"desc"``, in any combination of upper and lower case.

        Raises:
            ValueError: ``value`` is neither ``"asc"`` nor ``"desc"``.
        """
        lowered = value.lower()

        if lowered == "asc":
            return SortDirection.Ascending
        elif lowered == "desc":
            return SortDirection.Descending
        else:
            raise ValueError(f"Unrecognized sort direction '{value}'")

    def __str__(self) -> str:
        return self.value


class QuerySpecification(pydantic.BaseModel):
    """A structured query: a condition on the fields of one kind of resource, and how to sort and page its results.

    Run it with :py:class:`~roboto.query.QueryClient` or :py:class:`~roboto.roboto_search.RobotoSearch`, or pass it
    to a method that takes one, such as :py:meth:`~roboto.domain.datasets.Dataset.query`. To combine conditions, set
    ``condition`` to a :py:class:`~roboto.query.ConditionGroup`, whose conditions may themselves be groups. Keys the
    model does not declare are ignored. Building a specification raises ``pydantic.ValidationError`` when
    ``max_results`` is less than 1.
    """

    condition: typing.Optional[typing.Union[Condition, ConditionGroup]] = None
    """Condition the results must match: one comparison, or a group of them. ``None`` matches every resource."""

    limit: int = MAX_PAGE_SIZE
    """Maximum number of results per page.

    Queries run through :py:class:`~roboto.query.QueryClient` or :py:class:`~roboto.roboto_search.RobotoSearch`
    ignore it: their page size is the ``page_size`` given to :py:meth:`~roboto.query.QueryClient.get_query_results`.
    """

    max_results: typing.Optional[int] = pydantic.Field(default=None, ge=1)
    """Maximum number of results across all pages, at least 1. ``None`` returns every result.

    Only queries run through :py:class:`~roboto.query.QueryClient` or :py:class:`~roboto.roboto_search.RobotoSearch`
    honor it. Other methods that take a ``QuerySpecification``, such as
    :py:meth:`~roboto.domain.datasets.Dataset.query`, ignore it and return every result.
    """

    after: typing.Optional[str] = None
    """Token from a previous page's response that resumes the listing after it. ``None`` starts at the first page."""

    sort_by: typing.Optional[str] = None
    """Field to sort results by. ``None`` sorts by a default field that depends on the kind of resource queried."""

    sort_direction: typing.Optional[SortDirection] = None
    """Direction to sort results in. ``None`` uses a default that depends on the kind of resource queried."""

    model_config = ConfigDict(extra="ignore")

    def fields(self) -> set[str]:
        """Return every field the query's conditions compare, including those in nested condition groups."""
        fields = set()

        def _iterconditions(
            condition: typing.Optional[typing.Union[Condition, ConditionGroup]],
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
