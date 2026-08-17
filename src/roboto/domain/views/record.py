# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...query import (
    QueryTarget,
    SortDirection,
)

# Declared as a bare Final so its type narrows to Literal["view_v1"], letting it serve as the
# default for ViewDefinition.scheme without widening that field to str.
VIEW_SCHEME_V1: typing.Final = "view_v1"
"""Identifier for the first version of the View definition schema."""

VIEW_SCHEMA_VERSION_V1: typing.Final[int] = 1
"""Value stored in the ``schema_version`` column for a :data:`VIEW_SCHEME_V1` definition."""


class ViewDisplay(pydantic.BaseModel):
    """How a View presents its results: which columns, in what order, sorted how, how many rows.

    Presentation state only. Nothing here changes which records match.
    """

    visible_columns: list[str] = pydantic.Field(default_factory=list)
    """Columns to show, in display order.

    Visibility and ordering are carried by this one list rather than a visibility map plus a
    separate order: two fields could disagree about a column, and there is no sensible way to
    resolve that. A column absent from the list is hidden. An empty list means the client falls
    back to its own defaults, which is what a View saved before a new column shipped will do.
    """

    sort_by: typing.Optional[str] = None
    """Field to sort results by, or ``None`` to leave the target's default sort in place."""

    sort_direction: typing.Optional[SortDirection] = None
    """Direction to sort in. Only meaningful alongside :attr:`sort_by`."""

    page_size: typing.Optional[int] = pydantic.Field(default=None, gt=0)
    """Rows per page, or ``None`` to accept whatever the client's table would pick on its own."""


class ViewDefinition(pydantic.BaseModel):
    """The saved contents of a View: what its author searched for, and how they were shown it.

    Persisted as JSON in the ``views.definition`` column. That column has no database
    constraint, so this model is the only thing enforcing the shape.

    **A View records intent, not a query.** It holds what the author expressed — filter controls
    or RoboQL text — and the client rebuilds an executable query from that on load. It does not
    hold a ready-made :class:`~roboto.query.QuerySpecification`, because one cannot be stored
    faithfully: ``Comparator`` has no way to say "the last 7 days", so translating a relative
    date filter resolves it to fixed instants. A stored query would show the week the View was
    saved forever after, presented as though it were live.

    The practical consequence is that a structured View is only executable by a client that
    understands ``filters`` — today, the web UI. A RoboQL View is executable anywhere, since its
    text needs no client-side reconstruction. Making structured Views executable server-side
    means first teaching ``Comparator`` about relative dates; a later ``view_v2`` could then
    carry a query that stays correct.

    ``target`` is deliberately absent. It is a column on the ``views`` table, and duplicating
    it here would create two sources of truth that can disagree.
    """

    scheme: typing.Literal["view_v1"] = VIEW_SCHEME_V1
    """Version tag for this definition's shape.

    A future ``view_v2`` becomes a separate model, letting readers dispatch on this field and
    upgrade old rows instead of misreading them as the current version.
    """

    roboql: typing.Optional[str] = None
    """The RoboQL text the author wrote, when the View came from RoboQL rather than filter controls.

    RoboQL has no relative-date syntax, so this text does not go stale — it means the same thing
    whenever it is run, and a backend can execute it directly. ``None`` for Views built from
    structured filters.
    """

    filters: typing.Optional[dict[str, typing.Any]] = None
    """The filter controls the author built, in the client's own representation.

    Serves the same purpose as ``roboql`` for Views built from filter controls rather than typed
    queries: it records what the author expressed, so a client can rebuild the query on load
    rather than replaying a translation that has since gone stale.

    Deliberately untyped, unlike the rest of this model. The shape belongs to the client that
    writes it and no backend code reads it; mirroring it here would create a second definition to
    keep in lockstep with the original, which is the drift this schema exists to avoid. ``None``
    for RoboQL Views.
    """

    display: ViewDisplay = pydantic.Field(default_factory=ViewDisplay)
    """Presentation state to restore when the View is loaded: columns, sort, and page size."""


class ViewRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a View.

    A View is a named, org-scoped, shareable search over one resource type. Who may see or edit
    it is held in the authorization service rather than on this record, so there is no
    accessibility field here.
    """

    view_id: str
    """Unique identifier for the View, and the token that addresses it in a shareable URL."""

    name: str
    """Display name. Not unique — Views are addressed by ``view_id``, never by name."""

    org_id: str
    """Organization that owns the View."""

    target: QueryTarget
    """The resource type this View searches, e.g. datasets or files.

    Fixed at creation: a View's conditions are written against one target's fields.
    """

    definition: ViewDefinition
    """The saved query and presentation state."""

    schema_version: int
    """Version of ``definition``'s shape, mirroring its ``scheme`` so rows can be selected by
    version in SQL without parsing the JSON."""

    created: datetime.datetime
    """When the View was first saved."""

    created_by: str
    """User who created the View. The author, who alone may delete it or change who can see it."""

    modified: datetime.datetime
    """When the View's name or definition last changed. Shown in the picker alongside
    ``modified_by``, so a shared View can be judged on how current it is."""

    modified_by: str
    """User who last changed the View. Surfaced in the picker so a shared View can be judged."""
