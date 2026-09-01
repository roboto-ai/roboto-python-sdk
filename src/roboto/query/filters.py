# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Filter controls as a user built them, in a form that survives being saved.

A :class:`SavedFilters` records what someone expressed in a filter UI — which field, which
operator, which values — rather than the query that expression compiles to. Saved Views hold
this, and rebuild an executable query from it on load.

**Why this exists rather than a** :class:`~roboto.query.QuerySpecification`. A query cannot be
stored faithfully today, because :class:`~roboto.query.Comparator` has no way to say "the last
7 days", "between these two dates", or "any of these three". Those get flattened at translation
time — a relative window resolves to fixed instants, a range becomes two comparisons, a
multi-select becomes an OR group — and the flattening has no inverse. A View storing the
translated query would show the week it was saved, forever, presented as though it were live.

**This model is temporary by design.** :class:`FilterOnlyComparator` lists exactly what
``Comparator`` cannot yet express. As that gap closes (ENG-2957), members are deleted from it
one at a time; when it is empty, a saved filter is expressible as a plain ``QuerySpecification``
and this module can be retired in favour of one.

**On the per-variant comparator lists below.** ``roboql.model.core`` declares its own
``*_FIELD_COMPARATORS`` sets over the same ``Comparator`` enum, and four of them
(``STRING_``, ``NUMERIC_``, ``ENUM_``, ``TAG_``) are identical to the sets here. The
overlap is not accidental, but the two are answering different questions: roboql states
what the *query language* supports for a field type, while these state what the *filter
UI* offers, which is deliberately narrower — a date filter presents ``<``, ``>`` and
``BETWEEN`` where ``DATETIME_FIELD_COMPARATORS`` carries all six ordering and equality
operators, and a boolean presents ``EQUALS`` alone. So they are expected to diverge
further, not converge.

They cannot currently be shared in any case: ``roboql`` imports from ``roboto``, so
reusing its constants here would be a cycle. Merging them means moving those constants
into this package, which is tracked as ENG-2982 and is best done alongside ENG-2957 —
that work already has to visit every consumer of ``Comparator``.
"""

import datetime
import enum
import typing

import pydantic

from ..principal import RobotoPrincipalType
from .conditions import Comparator

METRIC_FIELD_PREFIX: typing.Final[str] = "metric."
"""Prefix distinguishing a user-defined metric from an ordinary numeric property.

Metric filters store the prefixed form so that ``field`` means the same thing here as it does
in a :class:`~roboto.query.Condition`, and so the eventual migration to a query copies the
field across rather than special-casing it.
"""

METRIC_FIELD_PATTERN: typing.Final[str] = r"^metric\..+"

MetricField: typing.TypeAlias = typing.Annotated[str, pydantic.StringConstraints(pattern=METRIC_FIELD_PATTERN)]
"""A metric's dot-delimited path, carrying its ``metric.`` prefix."""


class FilterOnlyComparator(enum.StrEnum):
    """Operators a saved filter needs that :class:`~roboto.query.Comparator` cannot express.

    Every member is a gap in the query language, and this enum is the list of them. It is
    deliberately the complement of ``Comparator`` rather than a superset: a member here that
    ``Comparator`` *can* express is a stale entry, and a test asserts the two never overlap.

    The intended lifecycle is deletion. As ``Comparator`` grows to cover these (ENG-2957),
    members are removed one at a time; the wire values are unchanged by that move, so filters
    saved beforehand keep parsing. When this enum is empty, the work is done.
    """

    Between = "BETWEEN"
    """An inclusive range. Translates to ``GTE`` and ``LTE``, which loses the fact that the
    author expressed one range rather than two independent bounds."""

    Today = "TODAY"
    Last7Days = "LAST_7_DAYS"
    Last30Days = "LAST_30_DAYS"
    Last90Days = "LAST_90_DAYS"
    ThisMonth = "THIS_MONTH"
    """Relative windows, resolved against "now" when the filter runs.

    These are the members that matter. The others cost fidelity; these cost correctness — a
    resolved window is wrong the day after it is saved, and nothing about the stored value
    says so.
    """


class IdentityComparator(enum.StrEnum):
    """Operators over a principal-valued field, where the operator names a principal type.

    An audit column such as ``created_by`` stores a fully-qualified principal —
    ``user:<user_id>``, ``device:<device_id>@<org_id>``, ``invocation:<invocation_id>`` — so
    "created by a user" is a question about the type prefix and "created by *this* user" a
    question about the whole value. Putting the type in the operator is what lets a filter UI
    offer the matching directory to pick from, instead of asking for a hand-typed prefix.

    Each type contributes two operators (see :data:`IDENTITY_OPERATORS_BY_TYPE`): a
    value-bearing ``IS_<TYPE>`` and a valueless ``IS_ANY_<TYPE>``.

    Separate from :class:`FilterOnlyComparator` because these are not gaps in the query
    language. Both halves are expressible today — ``IS_<TYPE>`` as ``EQUALS`` against each
    picked principal, ``IS_ANY_<TYPE>`` as ``LIKE '<type>:%'`` — so ENG-2957 will never delete
    them. They are a filter-UI affordance, and they outlive the gap enum.
    """

    # Value-bearing: match specific principals of the type. The values are principals of that
    # type, and several of them are alternatives — a client fans them out to an OR of EQUALS.
    IsUser = "IS_USER"
    IsDevice = "IS_DEVICE"
    IsInvocation = "IS_INVOCATION"
    IsIntegration = "IS_INTEGRATION"
    IsOrg = "IS_ORG"

    # Valueless: the type carried by the operator is the entire predicate, expanded by a
    # client to a `<type>:%` prefix match.
    IsAnyUser = "IS_ANY_USER"
    IsAnyDevice = "IS_ANY_DEVICE"
    IsAnyInvocation = "IS_ANY_INVOCATION"
    IsAnyIntegration = "IS_ANY_INTEGRATION"
    IsAnyOrg = "IS_ANY_ORG"


class IdentityOperators(typing.NamedTuple):
    """The operator pair one principal type contributes to an identity field's menu."""

    comparator: IdentityComparator
    """The value-bearing ``IS_<TYPE>``."""

    preset: IdentityComparator
    """The valueless ``IS_ANY_<TYPE>``."""


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
"""Which operators each principal type contributes, and the only statement of that pairing.

Exhaustive over :class:`~roboto.principal.RobotoPrincipalType` rather than listing the types an
audit column happens to hold today, so a new platform principal type is filterable as soon as it
exists instead of being silently unaddressable. A test pins that.
"""

IDENTITY_TYPES_BY_COMPARATOR: typing.Final[dict[IdentityComparator, RobotoPrincipalType]] = {
    operator: principal_type
    for principal_type, operators in IDENTITY_OPERATORS_BY_TYPE.items()
    for operator in (operators.comparator, operators.preset)
}
"""The principal type each identity operator addresses. Derived from the pairing above."""

IDENTITY_PRESET_COMPARATORS: typing.Final[frozenset[IdentityComparator]] = frozenset(
    operators.preset for operators in IDENTITY_OPERATORS_BY_TYPE.values()
)
"""The ``IS_ANY_<TYPE>`` half. Valueless: the comparator alone carries the predicate."""


class FilterMatchMode(enum.StrEnum):
    """How separate filters combine."""

    And = "AND"
    """Every filter must match."""

    Or = "OR"
    """At least one filter must match."""


PRESET_COMPARATORS: typing.Final[frozenset[FilterOnlyComparator]] = frozenset(
    {
        FilterOnlyComparator.Today,
        FilterOnlyComparator.Last7Days,
        FilterOnlyComparator.Last30Days,
        FilterOnlyComparator.Last90Days,
        FilterOnlyComparator.ThisMonth,
    }
)
"""Relative windows. Valueless: the comparator alone carries the range."""

PRESENCE_COMPARATORS: typing.Final[frozenset[Comparator]] = frozenset({Comparator.IsNull, Comparator.IsNotNull})
"""Null checks. Valueless: the comparator alone carries the question."""


def _utc_designator_as_offset(value: str) -> str:
    """Rewrite a trailing ``Z`` as ``+00:00``.

    ``datetime.fromisoformat`` only learned to accept the UTC designator in Python 3.11, and
    this SDK supports 3.10 (``requires-python = ">=3.10,<4"``). ``Z`` is also the common case
    rather than an exotic one — it is what ``toISOString()`` emits, so it is the shape most
    values arriving from the web UI take.

    Tests run on 3.13 only, where the rewrite is redundant, so this is separated out and
    asserted directly: a version-dependent failure is otherwise invisible to CI.

    Mirrors the same rewrite in ``conditions.py``.
    """
    return value.replace("Z", "+00:00")


def _as_instant(value: str) -> datetime.datetime:
    """Parse an ISO 8601 date value, reading a bare date as UTC.

    Date values are stored as the caller wrote them, so a View saved by the web UI round
    trips byte-identical rather than being renormalized underneath it. They are parsed here
    only to be checked: an unparseable value would be stored happily and fail whenever the
    View was next loaded, and ordering ``BETWEEN`` bounds by their spelling misjudges any
    pair written in different offsets or precisions.

    The web UI emits ``toISOString()`` throughout, so its own lexical comparison is sound.
    Nothing constrains an SDK, CLI, or agent caller the same way.

    A value with no offset is read as UTC, matching how relative windows already resolve.
    Comparing a naive against an aware datetime would otherwise raise, and refusing the pair
    would reject something unambiguous in practice.
    """
    try:
        parsed = datetime.datetime.fromisoformat(_utc_designator_as_offset(value))
    except ValueError:
        raise ValueError(f"{value!r} is not an ISO 8601 date")
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.timezone.utc)


def _is_valueless(comparator: typing.Any) -> bool:
    """Whether a comparator carries its own meaning and needs no operand."""
    return (
        comparator in PRESENCE_COMPARATORS
        or comparator in PRESET_COMPARATORS
        or comparator in IDENTITY_PRESET_COMPARATORS
    )


def _principal_type(value: str) -> typing.Optional[RobotoPrincipalType]:
    """The principal type a ``<type>:<id>`` string names, or ``None`` if it names none.

    Deliberately not :py:meth:`roboto.principal.RobotoPrincipal.from_string`, which indexes
    into the split and raises ``IndexError`` for a value carrying no colon. Inside a validator
    that would surface as a 500 rather than the rejection it is.
    """
    principal_type, separator, identifier = value.partition(":")
    if not separator or not identifier:
        return None
    try:
        return RobotoPrincipalType(principal_type)
    except ValueError:
        return None


class _FilterBase(pydantic.BaseModel):
    """Shared shape. Each subclass narrows ``comparator`` to the operators its type offers."""

    model_config = pydantic.ConfigDict(extra="forbid")

    field: str
    """The field being filtered, as the query layer addresses it."""

    def _require_values(self, minimum: int = 1) -> None:
        values = typing.cast(list, self.values)  # type: ignore[attr-defined]
        if _is_valueless(self.comparator):  # type: ignore[attr-defined]
            return
        if len(values) < minimum:
            raise ValueError(f"comparator {self.comparator} requires a value")  # type: ignore[attr-defined]


class StringFilter(_FilterBase):
    """Text matching."""

    type: typing.Literal["string"] = "string"
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
    values: list[str] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "StringFilter":
        if _is_valueless(self.comparator):
            return self
        if not any(value.strip() for value in self.values):
            raise ValueError(f"comparator {self.comparator} requires a non-blank value")
        return self


class NumericFilter(_FilterBase):
    """Ordering and equality over a numeric property."""

    type: typing.Literal["numeric"] = "numeric"
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
    values: list[float] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "NumericFilter":
        self._require_values()
        return self


class MetricFilter(_FilterBase):
    """Ordering and equality over a user-defined metric.

    Numeric in every respect except that ``field`` is a metric path. Kept a distinct variant
    so a client restoring a View knows to reopen the metric picker rather than the property
    form, which it cannot infer from the field name alone.

    Carries the presence pair like any other scalar type. A session may simply have no such
    metric recorded, and the session query path answers that directly — it maps ``IS_NULL``
    to a ``NOT EXISTS`` over the metrics table.
    """

    type: typing.Literal["metric"] = "metric"
    field: MetricField

    unit: typing.Optional[str] = None
    """The metric's unit, copied from its definition when the filter was built.

    Denormalized for display: the filter chip renders it beside the value ("path_deviation >
    1.5 m") without looking the definition up. ``None`` when the definition declares no unit.

    Being a copy, it goes stale if the definition's unit later changes — a saved View would
    render the old one. Tolerable while it is only a label, and an argument for ``view_v2``
    resolving it from the definition rather than storing it. See ENG-2957.
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
    values: list[float] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "MetricFilter":
        self._require_values()
        return self


class DateFilter(_FilterBase):
    """Instants and ranges. Values are ISO 8601 strings.

    The only variant offering relative windows, which is where the fidelity problem this whole
    model exists for actually bites.
    """

    type: typing.Literal["date"] = "date"
    comparator: typing.Literal[
        Comparator.LessThan,
        Comparator.GreaterThan,
        Comparator.IsNull,
        Comparator.IsNotNull,
        FilterOnlyComparator.Between,
        FilterOnlyComparator.Today,
        FilterOnlyComparator.Last7Days,
        FilterOnlyComparator.Last30Days,
        FilterOnlyComparator.Last90Days,
        FilterOnlyComparator.ThisMonth,
    ]
    values: list[str] = pydantic.Field(default_factory=list)

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


class BooleanFilter(_FilterBase):
    """True or false, or unset."""

    type: typing.Literal["boolean"] = "boolean"
    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    values: list[bool] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "BooleanFilter":
        if _is_valueless(self.comparator):
            return self
        if len(self.values) != 1:
            raise ValueError("a boolean filter carries exactly one value")
        return self


class SetFilter(_FilterBase):
    """Membership in a collection-valued field, such as tags.

    Has no presence axis: an empty collection is not the same as an absent one, and the UI
    offers no null check here.
    """

    type: typing.Literal["set"] = "set"
    comparator: typing.Literal[Comparator.Contains, Comparator.NotContains]
    values: list[str] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "SetFilter":
        if not self.values:
            raise ValueError("a set filter requires at least one value")
        return self


class EnumFilter(_FilterBase):
    """Equality against a closed set of options."""

    type: typing.Literal["enum"] = "enum"
    comparator: typing.Literal[
        Comparator.Equals,
        Comparator.NotEquals,
        Comparator.IsNull,
        Comparator.IsNotNull,
    ]
    values: list[str] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_values(self) -> "EnumFilter":
        self._require_values()
        return self


class LabeledOption(pydantic.BaseModel):
    """One option as it was picked: the value a query is built from, plus what the picker showed.

    Both halves are stored because the label cannot be recovered later. An opaque value —
    ``user:usr_01J...``, a tag id — renders as itself, and resolving it on load would mean a
    directory lookup per chip, against an org that whoever opens a shared View may not be able
    to read. Only ``value`` ever reaches a query.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    value: str
    """What the query is built from. A fully-qualified principal, for an identity filter."""

    label: str
    """What the picker displayed when the author chose this option. Display only, never queried."""


class IdentityFilter(_FilterBase):
    """A principal-valued field, filtered by principal type.

    Audit columns (``created_by``, ``modified_by``) hold a fully-qualified principal string, so
    the operator names the type (:class:`IdentityComparator`) and any values it takes are
    principals of that type — an ``IS_USER`` filter carrying a ``device:`` value is rejected,
    since it records an intent the picker cannot express and a query cannot satisfy.

    Values are labeled options rather than bare strings: a principal id is not a name a reader
    can place, so the directory's display name is captured alongside it at pick time.

    Has no presence axis. Every write path stamps an audit principal, so the column is never
    null and a null check would be an operator that always answers the same way.
    """

    type: typing.Literal["identity"] = "identity"
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
    values: list[LabeledOption] = pydantic.Field(default_factory=list)

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
"""One filter row. ``type`` selects the variant, and with it the operators on offer."""


class SavedFilters(pydantic.BaseModel):
    """A complete set of filter controls, as saved."""

    model_config = pydantic.ConfigDict(extra="forbid")

    filters: list[Filter] = pydantic.Field(default_factory=list)
    """The rows, in the order the author added them."""

    match_mode: FilterMatchMode = FilterMatchMode.And
    """Whether the rows are combined with AND or OR.

    Deliberately a single flag rather than a nested boolean expression. A
    :class:`~roboto.query.Condition` can express arbitrary nesting, but a filter UI cannot
    build one legibly, so this records the shape the UI actually offers.
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
"""Every filter variant, keyed by its ``type`` discriminant."""


def comparators_by_type() -> dict[str, list[str]]:
    """The operators each filter type offers, as wire values.

    Derived from the models rather than restated, so it cannot fall out of step with what
    they actually accept. Two callers: anything building a filter that needs to know what is
    valid for a field type, and the drift check against the filter UI's own copy of this
    vocabulary — there is no code generation between the two, so a test compares them.
    """
    return {
        name: sorted(
            str(comparator.value) for comparator in typing.get_args(model.model_fields["comparator"].annotation)
        )
        for name, model in FILTER_VARIANTS.items()
    }
