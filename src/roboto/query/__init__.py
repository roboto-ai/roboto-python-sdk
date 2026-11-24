# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Queries that find Roboto resources, such as datasets, files, topics, and events, by the values of their fields.

Write a query as a RoboQL string or a :py:class:`~roboto.query.QuerySpecification` and run it with
:py:class:`~roboto.query.QueryClient`, which yields each result as a dictionary, or with
:py:class:`~roboto.roboto_search.RobotoSearch`, which has a method for each kind of resource and yields SDK objects
such as :py:class:`~roboto.domain.datasets.Dataset`.
"""

from .api import (
    MAX_VALUE_COUNTS_LIMIT,
    QualifiedRoboqlQuery,
    QueryContentMode,
    QueryContext,
    QueryRecord,
    QueryScheme,
    QueryStatus,
    QueryStorageContext,
    QueryStorageScheme,
    QueryTarget,
    SubmitRoboqlQueryRequest,
    SubmitStructuredQueryRequest,
    SubmitTermQueryRequest,
    ValueCount,
    ValueCounts,
    ValueCountsSpec,
)
from .client import Query, QueryClient
from .conditions import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionOperator,
    ConditionType,
    ConditionValue,
    Field,
)
from .filters import (
    CUSTOM_FIELD_PREFIX,
    METRIC_FIELD_PATTERN,
    METRIC_FIELD_PREFIX,
    BooleanFilter,
    DateFilter,
    EnumFilter,
    Filter,
    FilterMatchMode,
    FilterOnlyComparator,
    IdentityComparator,
    IdentityFilter,
    LabeledOption,
    MetricFilter,
    NumericFilter,
    SavedFilters,
    SetFilter,
    StringFilter,
)
from .specification import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    QuerySpecification,
    SortDirection,
)
from .visitor import BaseVisitor, ConditionVisitor

__all__ = (
    "BaseVisitor",
    "BooleanFilter",
    "CUSTOM_FIELD_PREFIX",
    "Comparator",
    "Condition",
    "ConditionGroup",
    "ConditionOperator",
    "ConditionType",
    "ConditionValue",
    "ConditionVisitor",
    "DEFAULT_PAGE_SIZE",
    "DateFilter",
    "EnumFilter",
    "Field",
    "Filter",
    "FilterMatchMode",
    "FilterOnlyComparator",
    "IdentityComparator",
    "IdentityFilter",
    "LabeledOption",
    "MAX_PAGE_SIZE",
    "MAX_VALUE_COUNTS_LIMIT",
    "METRIC_FIELD_PATTERN",
    "METRIC_FIELD_PREFIX",
    "MetricFilter",
    "NumericFilter",
    "QualifiedRoboqlQuery",
    "Query",
    "QueryClient",
    "QueryContentMode",
    "QueryContext",
    "QueryRecord",
    "QueryScheme",
    "QuerySpecification",
    "QueryStatus",
    "QueryStorageContext",
    "QueryStorageScheme",
    "QueryTarget",
    "SavedFilters",
    "SetFilter",
    "SortDirection",
    "StringFilter",
    "SubmitRoboqlQueryRequest",
    "SubmitStructuredQueryRequest",
    "SubmitTermQueryRequest",
    "ValueCount",
    "ValueCounts",
    "ValueCountsSpec",
)
