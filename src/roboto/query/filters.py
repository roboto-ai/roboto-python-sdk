# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ..compat import StrEnum
from ..principal import RobotoPrincipalType
from .conditions import Comparator

CUSTOM_FIELD_PREFIX: typing.Final[str] = "custom."
"""Prefix that names one of the organization's custom fields in a query's field.

``custom.<field_name>`` names the custom field ``<field_name>`` wherever a query takes a field:
:py:attr:`~roboto.query.Condition.field`, :py:attr:`~roboto.query.QuerySpecification.sort_by`,
:py:attr:`~roboto.query.ValueCountsSpec.field`, and a saved filter's ``field``. No SDK method reads it.
"""

METRIC_FIELD_PREFIX: typing.Final[str] = "metric."
"""Prefix that marks a field as a user-defined metric rather than a numeric property of the resource.

A ``MetricFilter`` stores its ``field`` with the prefix, so the field names the metric the same way
:py:attr:`~roboto.query.Condition.field` does, and converting the filter to a query copies it unchanged. No SDK
method reads it.
"""

METRIC_FIELD_PATTERN: typing.Final[str] = r"^metric\..+"
"""Regular expression a metric filter's ``field`` must match.

It matches ``METRIC_FIELD_PREFIX`` followed by the metric's path.
"""

MetricField: typing.TypeAlias = typing.Annotated[str, pydantic.StringConstraints(pattern=METRIC_FIELD_PATTERN)]
"""Field name of a user-defined metric: ``metric.`` followed by the metric's dot-delimited path."""


class FilterOnlyComparator(StrEnum):
    """Operator of a saved filter that :py:class:`~roboto.query.Comparator` cannot express.

    Converting a filter to a query fixes what these operators mean: ``Between`` becomes two comparisons, and a
    relative time window becomes a range between two fixed times. The conversion cannot be undone, so ``SavedFilters``
    stores the operator itself. A window converted when a View was saved would match the wrong records from the next
    day on, with nothing in the stored query to show it.

    Every member but ``Between`` is a time window relative to when the filter runs, and takes no value.
    """

    Between = "BETWEEN"
    """Inclusive range from the filter's first value to its second.

    Converts to :py:attr:`~roboto.query.Comparator.GreaterThanOrEqual` on the first and
    :py:attr:`~roboto.query.Comparator.LessThanOrEqual` on the second.
    """

    Today = "TODAY"
    """Current day."""

    Last3Hours = "LAST_3_HOURS"
    """Last 3 hours."""

    Last8Hours = "LAST_8_HOURS"
    """Last 8 hours."""

    Last24Hours = "LAST_24_HOURS"
    """Last 24 hours."""

    Last7Days = "LAST_7_DAYS"
    """Last 7 days."""

    Last30Days = "LAST_30_DAYS"
    """Last 30 days."""

    Last90Days = "LAST_90_DAYS"
    """Last 90 days."""

    ThisMonth = "THIS_MONTH"
    """Current month."""


class IdentityComparator(StrEnum):
    """Operator of an identity filter: which type of principal the field must name.

    Fields such as ``created_by`` hold a principal as ``<type>:<id>``, such as ``user:<user_id>`` or
    ``device:<device_id>@<org_id>``. Because the operator names the type, a filter control can offer principals of
    that type to pick from. Each :py:class:`~roboto.principal.RobotoPrincipalType` has two members, paired in
    ``IDENTITY_OPERATORS_BY_TYPE``:

    - ``Is<Type>`` takes principals of the type as values and matches any of them.
    - ``IsAny<Type>`` takes no value and matches every principal of the type.

    Unlike ``FilterOnlyComparator``, both convert to a query without loss: ``Is<Type>`` to
    :py:attr:`~roboto.query.Comparator.Equals` on each value, combined with OR, and ``IsAny<Type>`` to
    :py:attr:`~roboto.query.Comparator.Like` with the pattern ``<type>:%``.
    """

    IsUser = "IS_USER"
    IsDevice = "IS_DEVICE"
    IsInvocation = "IS_INVOCATION"
    IsIntegration = "IS_INTEGRATION"
    IsOrg = "IS_ORG"

    IsAnyUser = "IS_ANY_USER"
    IsAnyDevice = "IS_ANY_DEVICE"
    IsAnyInvocation = "IS_ANY_INVOCATION"
    IsAnyIntegration = "IS_ANY_INTEGRATION"
    IsAnyOrg = "IS_ANY_ORG"


class IdentityOperators(typing.NamedTuple):
    """Pair of identity operators for one principal type.

    ``IDENTITY_OPERATORS_BY_TYPE`` holds one for each type.
    """

    comparator: IdentityComparator
    """Operator that matches the principals in a filter's values, ``Is<Type>``."""

    preset: IdentityComparator
    """Operator that matches every principal of the type and takes no value, ``IsAny<Type>``."""


IDENTITY_OPERATORS_BY_TYPE: typing.Final[dict[RobotoPrincipalType, IdentityOperators]] = {
    RobotoPrincipalType.User: IdentityOperators(IdentityComparator.IsUser, IdentityComparator.IsAnyUser),
    RobotoPrincipalType.Device: IdentityOperators(IdentityComparator.IsDevice, IdentityComparator.IsAnyDevice),
    RobotoPrincipalType.Invocation: IdentityOperators(
        IdentityComparator.IsInvocation, IdentityComparator.IsAnyInvocation
    ),
    RobotoPrincipalType.Integration: IdentityOperators(
        IdentityComparator.IsIntegration, IdentityComparator.IsAnyIntegration
    ),
    RobotoPrincipalType.Org: IdentityOperators(IdentityComparator.IsOrg, IdentityComparator.IsAnyOrg),
}
"""Identity operators of each principal type.

Covers every :py:class:`~roboto.principal.RobotoPrincipalType`, not only the types that ``created_by`` values hold,
so a filter can match any type of principal.
"""

IDENTITY_TYPES_BY_COMPARATOR: typing.Final[dict[IdentityComparator, RobotoPrincipalType]] = {
    operator: principal_type
    for principal_type, operators in IDENTITY_OPERATORS_BY_TYPE.items()
    for operator in (operators.comparator, operators.preset)
}
"""Principal type each identity operator matches.

Derived from ``IDENTITY_OPERATORS_BY_TYPE``.
"""

IDENTITY_PRESET_COMPARATORS: typing.Final[frozenset[IdentityComparator]] = frozenset(
    operators.preset for operators in IDENTITY_OPERATORS_BY_TYPE.values()
)
"""Identity operators that take no value: the ``IsAny<Type>`` operator of each principal type."""


class FilterMatchMode(StrEnum):
    """Match mode of a ``SavedFilters``: how its filters combine."""

    And = "AND"
    """Every filter must match."""

    Or = "OR"
    """At least one filter must match."""


PRESET_COMPARATORS: typing.Final[frozenset[FilterOnlyComparator]] = frozenset(
    {
        FilterOnlyComparator.Today,
        FilterOnlyComparator.Last3Hours,
        FilterOnlyComparator.Last8Hours,
        FilterOnlyComparator.Last24Hours,
        FilterOnlyComparator.Last7Days,
        FilterOnlyComparator.Last30Days,
        FilterOnlyComparator.Last90Days,
        FilterOnlyComparator.ThisMonth,
    }
)
"""Relative time windows: the date operators that take no value."""

PRESENCE_COMPARATORS: typing.Final[frozenset[Comparator]] = frozenset({Comparator.IsNull, Comparator.IsNotNull})
"""Operators that test whether a field is set, and take no value."""


def _utc_designator_as_offset(value: str) -> str:
    """Rewrite the UTC designator ``Z`` as ``+00:00``, which ``datetime.fromisoformat`` accepts before Python 3.11.

    The SDK supports Python 3.10, and most dates the Roboto web app saves end in ``Z``, as JavaScript's
    ``toISOString()`` writes them. Kept separate so a test can check the rewrite directly, since the tests run on a
    Python version that parses ``Z`` without it. :py:meth:`~roboto.query.Condition.matches` makes the same rewrite.
    """
    return value.replace("Z", "+00:00")


def _as_instant(value: str) -> datetime.datetime:
    """Parse an ISO 8601 date value, reading one with no UTC offset as UTC.

    Filters store date values as the caller wrote them, so a View the Roboto web app saved reads back unchanged.
    Validation parses them only to check them:

    - A value that does not parse would otherwise be stored, and fail each time the View loads.
    - ``Between`` bounds compared as strings are misordered when they use different offsets or precisions.

    A value with no offset is read as UTC because comparing it with one that has an offset raises ``TypeError``.

    Raises:
        ValueError: ``value`` is not an ISO 8601 date.
    """
    try:
        parsed = datetime.datetime.fromisoformat(_utc_designator_as_offset(value))
    except ValueError:
        raise ValueError(f"{value!r} is not an ISO 8601 date")
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.timezone.utc)


def _is_valueless(comparator: typing.Any) -> bool:
    """Whether ``comparator`` takes no value: a presence check, a relative time window, or ``IsAny<Type>``."""
    return (
        comparator in PRESENCE_COMPARATORS
        or comparator in PRESET_COMPARATORS
        or comparator in IDENTITY_PRESET_COMPARATORS
    )


def _principal_type(value: str) -> typing.Optional[RobotoPrincipalType]:
    """Return the principal type a ``<type>:<id>`` string names, or ``None`` if it names none.

    Does not call :py:meth:`~roboto.principal.RobotoPrincipal.from_string`, which raises ``IndexError`` for a principal
    type with no colon after it, such as ``user``. Raised inside a validator, that error would escape as itself
    instead of becoming a ``pydantic.ValidationError``.
    """
    principal_type, separator, identifier = value.partition(":")
    if not separator or not identifier:
        return None
    try:
        return RobotoPrincipalType(principal_type)
    except ValueError:
        return None


class _FilterBase(pydantic.BaseModel):
    """Fields and checks every filter type shares. Each subclass narrows ``comparator`` to the operators it offers."""

    model_config = pydantic.ConfigDict(extra="forbid")

    field: str
    """Field to filter on, named as :py:attr:`~roboto.query.Condition.field` names it."""

    def _require_values(self, minimum: int = 1) -> None:
        values = typing.cast(list, self.values)  # type: ignore[attr-defined]
        if _is_valueless(self.comparator):  # type: ignore[attr-defined]
            return
        if len(values) < minimum:
            raise ValueError(f"comparator {self.comparator} requires a value")  # type: ignore[attr-defined]


class _EqualityFilterBase(_FilterBase):
    """Fields and checks of the filter types that offer ``Equals`` and ``NotEquals``."""

    or_null: bool = False
    """Whether the filter also matches records where the field is not set.

    :py:attr:`~roboto.query.Comparator.Equals` with several values matches a record whose field holds any of them,
    and :py:attr:`~roboto.query.Comparator.NotEquals` one whose field holds none of them, but neither matches a
    record where the field is not set. Setting this matches those records too: "a, b, or not set", or "neither a nor
    b, or not set". Allowed only with ``Equals`` and ``NotEquals``.

    Left out of the serialized filter while ``False``, so SDK versions that predate the field can read a filter that
    does not use it.
    """

    @pydantic.model_validator(mode="after")
    def _or_null_only_on_equality(self) -> "_EqualityFilterBase":
        comparator = self.comparator  # type: ignore[attr-defined]
        if self.or_null and comparator not in (Comparator.Equals, Comparator.NotEquals):
            raise ValueError(f"or_null applies only to EQUALS and NOT_EQUALS, not {comparator}")
        return self

    @pydantic.model_serializer(mode="wrap")
    def _omit_or_null_unless_set(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        serialized = handler(self)
        if not self.or_null:
            serialized.pop("or_null", None)
        return serialized


class StringFilter(_EqualityFilterBase):
    """Filter on a text field.

    Building one raises ``pydantic.ValidationError`` when ``comparator`` is an operator the filter does not offer,
    when ``comparator`` takes a value and ``values`` holds no non-blank string, or when ``or_null`` is set with a
    comparator other than the two it allows.
    """

    type: typing.Literal["string"] = "string"
    """Kind of filter, always ``"string"``."""

    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.NotEquals,
        Comparator.Contains,
        Comparator.NotContains,
        Comparator.Like,
        Comparator.NotLike,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    """Operator the filter applies."""

    values: list[str] = pydantic.Field(default_factory=list)
    """Values to compare the field with, empty when ``comparator`` takes none."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "StringFilter":
        if _is_valueless(self.comparator):
            return self
        if not any(value.strip() for value in self.values):
            raise ValueError(f"comparator {self.comparator} requires a non-blank value")
        return self


class NumericFilter(_EqualityFilterBase):
    """Filter on a numeric field, by order or equality.

    Building one raises ``pydantic.ValidationError`` when ``comparator`` is an operator the filter does not offer,
    when ``comparator`` takes a value and ``values`` is empty, or when ``or_null`` is set with a comparator other
    than the two it allows.
    """

    type: typing.Literal["numeric"] = "numeric"
    """Kind of filter, always ``"numeric"``."""

    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.NotEquals,
        Comparator.GreaterThan,
        Comparator.LessThan,
        Comparator.GreaterThanOrEqual,
        Comparator.LessThanOrEqual,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    """Operator the filter applies."""

    values: list[float] = pydantic.Field(default_factory=list)
    """Values to compare the field with, empty when ``comparator`` takes none."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "NumericFilter":
        self._require_values()
        return self


class MetricFilter(_EqualityFilterBase):
    """Filter on a user-defined metric, by order or equality.

    Offers the same operators and values as ``NumericFilter``, but ``field`` names a metric, so a client that loads
    the filter knows to show its metric picker rather than its property controls.
    :py:attr:`~roboto.query.Comparator.IsNull` matches a resource, such as a session, with no value recorded for the
    metric.

    Building one raises ``pydantic.ValidationError`` when ``field`` does not match ``METRIC_FIELD_PATTERN``, when
    ``comparator`` is an operator the filter does not offer, when ``comparator`` takes a value and ``values`` is
    empty, or when ``or_null`` is set with a comparator other than the two it allows.
    """

    type: typing.Literal["metric"] = "metric"
    """Kind of filter, always ``"metric"``."""

    field: MetricField
    """Name of the metric: ``metric.`` followed by its dot-delimited path."""

    unit: typing.Optional[str] = None
    """Unit of the metric, or ``None`` if the metric's definition declares none.

    Copied from the definition when the filter was built. A client shows it beside the value, as in
    ``path_deviation > 1.5 m``, without fetching the definition. A later change to the definition's unit does not
    change it.
    """

    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.NotEquals,
        Comparator.GreaterThan,
        Comparator.LessThan,
        Comparator.GreaterThanOrEqual,
        Comparator.LessThanOrEqual,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    """Operator the filter applies."""

    values: list[float] = pydantic.Field(default_factory=list)
    """Values to compare the metric with, empty when ``comparator`` takes none."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "MetricFilter":
        self._require_values()
        return self


class DateFilter(_FilterBase):
    """Filter on a date field, by a time, a range, or a time window relative to when the filter runs.

    Building one raises ``pydantic.ValidationError`` when:

    - ``comparator`` is an operator the filter does not offer.
    - ``comparator`` is ``FilterOnlyComparator.Between`` and ``values`` does not hold exactly two non-blank ISO 8601
      dates, or the second is before the first.
    - ``comparator`` is :py:attr:`~roboto.query.Comparator.LessThan` or
      :py:attr:`~roboto.query.Comparator.GreaterThan` and the first value is missing, blank, or not an ISO 8601 date.
    """

    type: typing.Literal["date"] = "date"
    """Kind of filter, always ``"date"``."""

    comparator: typing.Literal[
        Comparator.LessThan,
        Comparator.GreaterThan,
        Comparator.IsNull,
        Comparator.IsNotNull,
        FilterOnlyComparator.Between,
        FilterOnlyComparator.Today,
        FilterOnlyComparator.Last3Hours,
        FilterOnlyComparator.Last8Hours,
        FilterOnlyComparator.Last24Hours,
        FilterOnlyComparator.Last7Days,
        FilterOnlyComparator.Last30Days,
        FilterOnlyComparator.Last90Days,
        FilterOnlyComparator.ThisMonth,
    ]
    """Operator the filter applies."""

    values: list[str] = pydantic.Field(default_factory=list)
    """Dates to compare the field with, as ISO 8601 strings, empty when ``comparator`` takes none.

    Stored as written. A date with no UTC offset is read as UTC when two are compared.
    """

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "DateFilter":
        if _is_valueless(self.comparator):
            return self

        if self.comparator is FilterOnlyComparator.Between:
            if len(self.values) != 2 or not all(value.strip() for value in self.values):
                raise ValueError("BETWEEN requires a start and an end")
            start, end = (_as_instant(value) for value in self.values)
            if start > end:
                raise ValueError("BETWEEN requires end to be on or after start")
            return self

        if not self.values or not self.values[0].strip():
            raise ValueError(f"comparator {self.comparator} requires a value")
        _as_instant(self.values[0])
        return self


class BooleanFilter(_EqualityFilterBase):
    """Filter on a true-or-false field.

    Building one raises ``pydantic.ValidationError`` when ``comparator`` is an operator the filter does not offer,
    when ``comparator`` is :py:attr:`~roboto.query.Comparator.Equals` and ``values`` holds no value or more than two,
    or when ``or_null`` is set with any other comparator.
    """

    type: typing.Literal["boolean"] = "boolean"
    """Kind of filter, always ``"boolean"``."""

    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    """Operator the filter applies."""

    values: list[bool] = pydantic.Field(default_factory=list)
    """Values the field may equal, one or both of ``True`` and ``False``; empty when ``comparator`` takes none."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "BooleanFilter":
        if _is_valueless(self.comparator):
            return self
        if len(self.values) not in (1, 2):
            raise ValueError("a boolean filter carries no more than 2 values")
        return self


class SetFilter(_FilterBase):
    """Filter on a field that holds a collection, such as tags, by whether the collection contains values.

    Offers no :py:attr:`~roboto.query.Comparator.IsNull` or ``IsNotNull``. Building one raises
    ``pydantic.ValidationError`` when ``comparator`` is an operator the filter does not offer, or when ``values`` is
    empty.
    """

    type: typing.Literal["set"] = "set"
    """Kind of filter, always ``"set"``."""

    comparator: typing.Literal[Comparator.Contains, Comparator.NotContains]
    """Operator the filter applies."""

    values: list[str] = pydantic.Field(default_factory=list)
    """Values to look for in the collection."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "SetFilter":
        if not self.values:
            raise ValueError("a set filter requires at least one value")
        return self


class EnumFilter(_EqualityFilterBase):
    """Filter on a field whose values come from a fixed set of options, by equality.

    Building one raises ``pydantic.ValidationError`` when ``comparator`` is an operator the filter does not offer,
    when ``comparator`` takes a value and ``values`` is empty, or when ``or_null`` is set with a comparator other
    than the two it allows.
    """

    type: typing.Literal["enum"] = "enum"
    """Kind of filter, always ``"enum"``."""

    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.NotEquals,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    """Operator the filter applies."""

    values: list[str] = pydantic.Field(default_factory=list)
    """Options to compare the field with, empty when ``comparator`` takes none."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "EnumFilter":
        self._require_values()
        return self


class LabeledOption(pydantic.BaseModel):
    """Option picked for an ``IdentityFilter``: the value a query uses and the label shown.

    The label is stored because it cannot be recovered when the filter loads. Without it, a value such as
    ``user:<user_id>`` would show as itself, or need one lookup per value, which a user opening a shared View may not
    have permission to make. Only ``value`` goes into a query.

    Carried in ``IdentityFilter.values``.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    value: str
    """Principal the option stands for, as ``<type>:<id>``."""

    label: str
    """Text the picker showed when the author chose the option, never used in a query."""


class IdentityFilter(_FilterBase):
    """Filter on a field that holds a principal, such as ``created_by`` or ``modified_by``, by the principal's type.

    The operator, an ``IdentityComparator``, names the type, and any values are principals of that type, each stored
    with the label the picker showed. Offers no :py:attr:`~roboto.query.Comparator.IsNull` or ``IsNotNull``, because
    Roboto records a principal in these fields whenever it creates or changes a resource.

    Building one raises ``pydantic.ValidationError`` when ``comparator`` is not an ``IdentityComparator``, when an
    ``Is<Type>`` comparator has no values, or when a value is not of the form ``<type>:<id>`` or names a principal of
    a type other than the comparator's.
    """

    type: typing.Literal["identity"] = "identity"
    """Kind of filter, always ``"identity"``."""

    comparator: typing.Literal[
        IdentityComparator.IsUser,
        IdentityComparator.IsDevice,
        IdentityComparator.IsInvocation,
        IdentityComparator.IsIntegration,
        IdentityComparator.IsOrg,
        IdentityComparator.IsAnyUser,
        IdentityComparator.IsAnyDevice,
        IdentityComparator.IsAnyInvocation,
        IdentityComparator.IsAnyIntegration,
        IdentityComparator.IsAnyOrg,
    ]
    """Operator the filter applies, which names the principal type to match."""

    values: list[LabeledOption] = pydantic.Field(default_factory=list)
    """Principals to match, with the labels the picker showed; empty for an ``IsAny<Type>`` comparator."""

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "IdentityFilter":
        self._require_values()
        if _is_valueless(self.comparator):
            return self

        expected_type = IDENTITY_TYPES_BY_COMPARATOR[self.comparator]
        for option in self.values:
            principal_type = _principal_type(option.value)
            if principal_type is None:
                raise ValueError(f"{option.value!r} is not a qualified principal; expected '<type>:<id>'")
            if principal_type is not expected_type:
                raise ValueError(
                    f"comparator {self.comparator} matches {expected_type} principals, "
                    f"but {option.value!r} is a {principal_type} principal"
                )
        return self


Filter: typing.TypeAlias = typing.Annotated[
    typing.Union[
        StringFilter,
        NumericFilter,
        MetricFilter,
        DateFilter,
        BooleanFilter,
        SetFilter,
        EnumFilter,
        IdentityFilter,
    ],
    pydantic.Field(discriminator="type"),
]
"""Filter of any type, told apart by ``type``.

One of ``StringFilter``, ``NumericFilter``, ``MetricFilter``, ``DateFilter``, ``BooleanFilter``, ``SetFilter``,
``EnumFilter`` or ``IdentityFilter``.

Each type's ``comparator`` accepts only the operators the Roboto web app's filter controls offer for that kind of
field, which can be fewer than a query accepts for it. Of the :py:class:`~roboto.query.Comparator` members, a date
filter offers ``LessThan`` but not ``LessThanOrEqual``, and a boolean filter offers ``Equals`` but not ``NotEquals``.
``comparators_by_type`` lists each type's operators.
"""


class SavedFilters(pydantic.BaseModel):
    """Filter controls as their author set them: the field, operator and values of each filter, and how they combine.

    Records the operator the author chose, such as "the last 7 days", rather than the query it converts to.
    Converting fixes a relative window's dates and splits a range into two comparisons, and cannot be undone;
    ``FilterOnlyComparator`` lists the operators a :py:class:`~roboto.query.QuerySpecification` cannot express.
    Building one raises ``pydantic.ValidationError`` when a filter's ``type`` is not a filter type, or when a filter
    fails its own type's checks.

    Carried in :py:attr:`~roboto.domain.views.ViewDefinition.filters`.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    filters: list[Filter] = pydantic.Field(default_factory=list)
    """Filters, in the order the author added them."""

    match_mode: FilterMatchMode = FilterMatchMode.And
    """How the filters combine: every one must match, or at least one.

    One mode applies to every filter. Unlike a :py:class:`~roboto.query.ConditionGroup`, saved filters cannot nest,
    since the filter controls give an author no way to build nested groups.
    """


FILTER_VARIANTS: typing.Final[dict[str, type[pydantic.BaseModel]]] = {
    "string": StringFilter,
    "numeric": NumericFilter,
    "metric": MetricFilter,
    "date": DateFilter,
    "boolean": BooleanFilter,
    "set": SetFilter,
    "enum": EnumFilter,
    "identity": IdentityFilter,
}
"""Each filter type's model, keyed by the value of its ``type`` field."""


def comparators_by_type() -> dict[str, list[str]]:
    """Return the wire values of the operators each filter type accepts, keyed by the filter's ``type``.

    Read from the filter models' ``comparator`` fields, so it lists exactly what they accept. Each list is sorted.

    Examples:
        >>> comparators_by_type()["boolean"]
        ['EQUALS', 'IS_NOT_NULL', 'IS_NULL']
    """
    return {
        name: sorted(
            str(comparator.value) for comparator in typing.get_args(model.model_fields["comparator"].annotation)
        )
        for name, model in FILTER_VARIANTS.items()
    }
