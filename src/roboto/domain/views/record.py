# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...exceptions import RobotoInvalidRequestException
from ...query import (
    QueryTarget,
    SavedFilters,
    SortDirection,
)

VIEW_SCHEME_V1: typing.Final = "view_v1"
"""Value of ``ViewDefinition.scheme`` for the first shape of a View's definition.

That shape states the display's sort in three fields, ``sort_by``, ``sort_direction`` and ``unsorted``.
``ViewDefinition`` reads a definition in it as ``VIEW_SCHEME_V2``, so no definition the SDK builds carries this value.
"""

# A bare Final infers Literal["view_v2"], so this can be the default of ViewDefinition.scheme, which only accepts
# that literal.
VIEW_SCHEME_V2: typing.Final = "view_v2"
"""Value of ``ViewDefinition.scheme`` for the current shape of a View's definition.

That shape states the display's sort in one field, ``ViewDisplay.sort``.
"""

VIEW_SCHEMA_VERSION_V1: typing.Final[int] = 1
"""Value of ``ViewRecord.schema_version`` for a ``"view_v1"`` definition.

No SDK method reads it.
"""

VIEW_SCHEMA_VERSION_V2: typing.Final[int] = 2
"""Value of ``ViewRecord.schema_version`` for a ``"view_v2"`` definition.

No SDK method reads it.
"""


class ViewVisibility(StrEnum):
    """Visibility of a View: who can see it, chosen when the View is created and reported when it is read.

    Visibility decides only who can read a View. Whatever its visibility, a View can be edited only by its author,
    users and groups granted ``editor`` on it, and admins and owners of its organization.
    """

    Private = "private"
    """Visible to the View's author, users and groups granted access to it, and admins and owners of its
    organization."""

    Organization = "organization"
    """Visible to every member of the organization that owns the View."""


class DefaultSort(pydantic.BaseModel):
    """Sort that shows a View's results in the order its target's list shows when no sort is chosen.

    Constructing one raises ``pydantic.ValidationError`` for a ``kind`` other than ``"default"``.

    Carried in ``ViewDisplay.sort``.
    """

    kind: typing.Literal["default"] = "default"
    """Kind of sort, always ``"default"``."""


class NoSort(pydantic.BaseModel):
    """Sort that shows a View's results in no particular order.

    A View saved from a table whose sort was cleared stores this, so the table reopens unsorted; ``DefaultSort``
    would reopen it in the target's default order.

    Constructing one raises ``pydantic.ValidationError`` for a ``kind`` other than ``"unsorted"``.

    Carried in ``ViewDisplay.sort``.
    """

    kind: typing.Literal["unsorted"] = "unsorted"
    """Kind of sort, always ``"unsorted"``."""


class ColumnSort(pydantic.BaseModel):
    """Sort that orders a View's results by one field.

    Constructing one raises ``pydantic.ValidationError`` for a ``kind`` other than ``"column"``.

    Carried in ``ViewDisplay.sort``.
    """

    kind: typing.Literal["column"] = "column"
    """Kind of sort, always ``"column"``."""

    by: str
    """Field to sort by, such as ``"created"``."""

    direction: SortDirection = SortDirection.Ascending
    """Direction to sort in, :py:attr:`~roboto.query.SortDirection.Ascending` by default."""


ViewSort = typing.Annotated[typing.Union[DefaultSort, NoSort, ColumnSort], pydantic.Field(discriminator="kind")]
"""Sort of any kind: one of the sort models, told apart by ``kind``.

The models are ``DefaultSort``, ``NoSort`` and ``ColumnSort``.
"""


class ViewDisplay(pydantic.BaseModel):
    """How a View shows its results: which columns, in what order, sorted how, and how many rows per page.

    None of these settings changes which records match. Constructing a display raises ``pydantic.ValidationError``
    for a ``page_size`` below 1.

    A display may also state its sort as a ``"view_v1"`` definition does, in ``sort_by``, ``sort_direction`` and
    ``unsorted``, and is read into ``sort``: ``unsorted`` set to ``True`` gives ``NoSort``, otherwise ``sort_by``
    gives ``ColumnSort``, ascending unless ``sort_direction`` says otherwise, and neither gives ``DefaultSort``. A
    ``sort`` given beside those fields wins.

    Carried in ``ViewDefinition.display``.
    """

    visible_columns: list[str] = pydantic.Field(default_factory=list)
    """Columns to show, in display order.

    A column not in the list is hidden. An empty list leaves the choice of columns to the client's defaults.
    """

    sort: ViewSort = pydantic.Field(default_factory=DefaultSort)
    """Order to show results in, ``DefaultSort`` unless set."""

    page_size: typing.Optional[int] = pydantic.Field(default=None, gt=0)
    """Rows per page, greater than zero, or ``None`` to leave the page size to the client."""

    @pydantic.model_validator(mode="before")
    @classmethod
    def __read_a_sort_stated_as_three_fields(cls, data: typing.Any) -> typing.Any:
        """Fold ``sort_by``, ``sort_direction`` and ``unsorted``, the sort of a ``view_v1`` display, into ``sort``.

        Roboto does not rewrite Views saved as ``view_v1``, and SDK versions built for that shape still send it.
        """
        if not isinstance(data, dict):
            return data
        older = {key: data[key] for key in ("sort_by", "sort_direction", "unsorted") if key in data}
        if not older:
            return data
        data = {key: value for key, value in data.items() if key not in older}
        if "sort" in data:
            return data
        if older.get("unsorted"):
            data["sort"] = {"kind": "unsorted"}
        elif older.get("sort_by"):
            data["sort"] = {
                "kind": "column",
                "by": older["sort_by"],
                "direction": older.get("sort_direction") or SortDirection.Ascending,
            }
        else:
            data["sort"] = {"kind": "default"}
        return data


class ViewDefinition(pydantic.BaseModel):
    """Saved contents of a View: the search its author made, and how its results are shown.

    A definition records what the author entered, RoboQL text or filter controls, and the client builds a query from
    it each time the View loads. It does not store a :py:class:`~roboto.query.QuerySpecification`, because a query
    specification cannot express a relative date such as "the last 7 days": converting the filter fixes its dates,
    and the View would show the week it was saved in from then on.

    Filter controls are recorded as :py:class:`~roboto.query.SavedFilters`, so any caller can build a View's filters.
    The Roboto web app converts them to a query when the View loads; RoboQL text runs as written.

    At most one of ``roboql`` and ``filters`` is set, and a definition with neither filters nothing. Constructing a
    definition raises ``pydantic.ValidationError`` when it sets both, or when its ``scheme`` is neither ``"view_v1"``
    nor ``"view_v2"``. The View's target is not part of its definition; ``ViewRecord.target`` holds it.

    Carried in ``ViewRecord.definition``, :py:attr:`~roboto.domain.views.CreateViewRequest.definition` and
    :py:attr:`~roboto.domain.views.UpdateViewRequest.definition`.
    """

    scheme: typing.Literal["view_v2"] = VIEW_SCHEME_V2
    """Version of the definition's shape, always ``"view_v2"``.

    A definition saved as ``"view_v1"`` is read as this shape, since the two differ only in how the display states its
    sort. A definition saved in a later shape fails validation instead of being read as this one.
    """

    roboql: typing.Optional[str] = None
    """RoboQL text the author wrote, or ``None`` when the View uses filter controls or filters nothing.

    RoboQL has no relative-date syntax, so the text means the same thing whenever it runs. Only Views on the targets
    in ``ROBOQL_VIEW_TARGETS`` can use RoboQL.
    """

    filters: typing.Optional[SavedFilters] = None
    """Filter controls the author set, or ``None`` when the View uses RoboQL or filters nothing.

    A View with neither ``roboql`` nor ``filters`` saves a column layout and sort over the unfiltered list, so
    ``None`` here does not mean the View uses RoboQL.
    """

    display: ViewDisplay = pydantic.Field(default_factory=ViewDisplay)
    """Columns, sort, and page size to restore when the View loads."""

    @pydantic.model_validator(mode="after")
    def __one_form_of_intent_at_most(self) -> "ViewDefinition":
        """Reject a definition that sets both ``roboql`` and ``filters``.

        Each records the whole search, so a client given both would have to pick one, and two clients could pick
        differently.
        """
        if self.roboql is not None and self.filters is not None:
            raise ValueError("a View records either RoboQL text or structured filters, not both")
        return self

    @pydantic.model_validator(mode="before")
    @classmethod
    def __read_view_v1_as_this_shape(cls, data: typing.Any) -> typing.Any:
        if isinstance(data, dict) and data.get("scheme") == VIEW_SCHEME_V1:
            return {**data, "scheme": VIEW_SCHEME_V2}
        return data


# Keep in step with the Roboto web app: a target belongs here exactly when its list page passes a roboql config to its
# filter bar.
ROBOQL_VIEW_TARGETS: typing.Final[frozenset[QueryTarget]] = frozenset(
    {QueryTarget.Datasets, QueryTarget.Files, QueryTarget.Events}
)
"""Targets whose Views can be written in RoboQL: datasets, files, and events.

The list pages for the other targets, such as sessions, devices, and collections, have filter controls only, so
Roboto rejects a RoboQL View on them.
"""


def ensure_definition_renders_for(target: QueryTarget, definition: ViewDefinition) -> None:
    """Reject a definition written in RoboQL for a target whose list page has no RoboQL mode.

    Roboto calls this when a View is created and when its definition is updated, so calling it first only reports
    the rejection sooner. A definition that uses filter controls, or filters nothing, passes for every target.

    Args:
        target: Resource type the View searches.
        definition: Definition the View would store.

    Raises:
        RobotoInvalidRequestException: ``definition`` sets ``roboql`` and ``target`` is not in ``ROBOQL_VIEW_TARGETS``.
    """
    if definition.roboql is None or target in ROBOQL_VIEW_TARGETS:
        return
    supported = ", ".join(sorted(candidate.value for candidate in ROBOQL_VIEW_TARGETS))
    raise RobotoInvalidRequestException(
        f"A View on {target.value} cannot be defined with RoboQL, because that table has no RoboQL mode. "
        f"Define it with structured filters instead. RoboQL Views are supported on: {supported}."
    )


class ViewRecord(pydantic.BaseModel):
    """Data record of a View, as ``GET /v1/views/id/{view_id}`` returns it.

    ``POST /v1/views/create``, ``PUT /v1/views/id/{view_id}``, ``POST /v1/views/id/{view_id}/duplicate`` and
    ``GET /v1/views/`` return it too.

    A View is a named, shareable search over one resource type, saved with the columns, sort, and page size its author
    chose, so the author or a teammate can return to it without rebuilding it. The record carries one part of who can
    access the View, its ``visibility``, so a client can tell a caller's own Views from those shared with the
    organization without a request per View. Individual grants are listed by ``GET /v1/views/id/{view_id}/access``.
    """

    view_id: str
    """Unique ID of the View, beginning with ``vw_``. Shareable URLs address a View by this ID."""

    name: str
    """Human-readable name of the View. Names are not unique."""

    org_id: str
    """ID of the organization that owns the View."""

    target: QueryTarget
    """Resource type the View searches, such as datasets or files.

    Fixed when the View is created, because the View's filters are written against that target's fields.
    """

    definition: ViewDefinition
    """Saved search and presentation settings."""

    schema_version: int
    """Version of the shape ``definition`` was saved in.

    One of ``VIEW_SCHEMA_VERSION_V1`` and ``VIEW_SCHEMA_VERSION_V2``. ``definition`` is always read in the current
    shape, so a View saved as ``"view_v1"`` reports ``1`` here beside a ``"view_v2"`` definition. Updating the View's
    definition saves it in the current shape and sets this to ``2``.
    """

    created: datetime.datetime
    """Time the View was created."""

    created_by: str
    """ID of the user who created the View, its author.

    Only the author and owners of the View's organization can delete it or change who can see it.
    """

    modified: datetime.datetime
    """Time the View's name or definition was last modified."""

    modified_by: str
    """ID of the user who last modified the View's name or definition."""

    visibility: typing.Optional[ViewVisibility] = None
    """Who can see the View, or ``None`` when it was not looked up.

    Roboto sets it on the View it returns from fetching, listing, creating, or duplicating Views, but not from an
    update. ``None`` does not mean ``ViewVisibility.Private``.
    """
