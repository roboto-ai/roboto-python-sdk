# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...query import QueryTarget
from ...sentinels import (
    NotSet,
    NotSetType,
)
from .record import (
    ViewDefinition,
    ViewVisibility,
)

MAX_VIEW_NAME_LENGTH: typing.Final[int] = 120
"""Maximum length of a View's name, in characters."""


class CreateViewRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/views/create``.

    Also the optional body of ``POST /v1/views/id/{view_id}/duplicate``, which uses only ``name`` and ``definition``:
    the copy keeps the source View's target and is private.

    Building the request raises ``pydantic.ValidationError`` for a ``name`` that is empty or longer than 120
    characters.
    """

    name: str = pydantic.Field(min_length=1, max_length=MAX_VIEW_NAME_LENGTH)
    """Human-readable name of the View.

    From 1 to 120 characters (:py:const:`~roboto.domain.views.MAX_VIEW_NAME_LENGTH`). Names need not be unique.
    """

    target: QueryTarget
    """Resource type the View searches, such as datasets or files. It cannot be changed after the View is created."""

    definition: ViewDefinition
    """Query and presentation state to save.

    Roboto rejects a definition written in RoboQL, with ``RobotoInvalidRequestException``, when ``target`` is not in
    :py:const:`~roboto.domain.views.ROBOQL_VIEW_TARGETS`.
    """

    visibility: ViewVisibility = ViewVisibility.Private
    """Who can see the View once it is created, :py:attr:`~roboto.domain.views.ViewVisibility.Private` by default.

    Afterwards, only the View's author or an admin or owner of its organization can change it, through
    ``PUT /v1/views/id/{view_id}/access``. That endpoint also grants access to individual users, which this field
    cannot.
    """


class UpdateViewRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/views/id/{view_id}``.

    A field left unset (``NotSet``) is unchanged, and fields this model does not declare are ignored. A View's target
    cannot be changed, because its filters are written against that target's fields; create a new View instead.
    Change who can see a View through ``PUT /v1/views/id/{view_id}/access``.

    Building the request raises ``pydantic.ValidationError`` for a ``name`` that is empty or longer than 120
    characters.
    """

    name: typing.Union[str, NotSetType] = pydantic.Field(
        default=NotSet,
        min_length=1,
        max_length=MAX_VIEW_NAME_LENGTH,
    )
    """New human-readable name, from 1 to 120 characters (:py:const:`~roboto.domain.views.MAX_VIEW_NAME_LENGTH`)."""

    definition: typing.Union[ViewDefinition, NotSetType] = NotSet
    """New query and presentation state, which replaces the stored definition whole.

    To change one filter, send the full definition with that filter changed. Roboto rejects a definition written in
    RoboQL, with ``RobotoInvalidRequestException``, when the View's target is not in
    :py:const:`~roboto.domain.views.ROBOQL_VIEW_TARGETS`.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)
