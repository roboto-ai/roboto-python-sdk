# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Annotated, Any, Literal, Union

import pydantic

from ...pydantic import ValidatedAgainst
from ...sentinels import NotSet, NotSetType
from .definition import BoardDefinition, check_definition_top_level
from .record import (
    BoardAccessibility,
    definition_title,
)


class CreateBoardRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/boards/create``.

    The board is personal: the caller owns it. :py:class:`UpdateBoardAccessRequest` shares it with the
    organization.
    """

    board_definition: Annotated[dict[str, Any], ValidatedAgainst(BoardDefinition)]
    """The board definition as a JSON object, stored as
    :py:attr:`~roboto.experimental.boards.BoardRecord.board_definition` describes. A top-level ``title`` that is a
    non-empty string must equal ``name``, and a request in which they differ fails validation. A definition with
    no title is stored without one.

    A definition whose top level :py:class:`~roboto.experimental.boards.BoardDefinition` refuses fails validation:
    for example, one with an unknown top-level key, a missing ``time_range`` or ``panels``, a ``panels`` that is not a
    list, a ``stages`` that is neither a list nor null, a ``title`` that is neither a string nor null, or a malformed
    section or selection. The panels and stages in it are not checked and are stored as given, so the web app can
    show a broken one beside the rest of the board."""

    name: str = pydantic.Field(min_length=1, max_length=120)
    """The name the board list and board page show. Must not be empty: an empty name shows nothing in the board
    list, and the platform keeps a name equal to a definition ``title`` only while the title is a non-empty
    string."""

    @pydantic.field_validator("board_definition")
    @classmethod
    def validate_definition_top_level(cls, board_definition: dict[str, Any]) -> dict[str, Any]:
        """Reject a definition whose top level :py:class:`~roboto.experimental.boards.BoardDefinition` refuses."""
        check_definition_top_level(board_definition)
        return board_definition

    @pydantic.model_validator(mode="after")
    def validate_name_and_title_agree(self) -> "CreateBoardRequest":
        """Reject a ``name`` that differs from the definition's non-empty ``title``."""
        title = definition_title(self.board_definition)
        if title is not None and title != self.name:
            raise ValueError("The board name and its definition title must match")
        return self


class UpdateBoardRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/boards/id/<board_id>``.

    Carries a new name, new definition content, or both. :py:class:`UpdateBoardAccessRequest` changes who can
    open a board.
    """

    board_definition: Union[Annotated[dict[str, Any], ValidatedAgainst(BoardDefinition)], NotSetType] = NotSet
    """The board definition as a JSON object, replacing the stored one whole. A top-level ``title`` that is a
    non-empty string is kept equal to the board's name: with no ``name`` in the request, the board takes the title
    as its name. A definition with no title leaves the name alone, and the platform never adds a title.

    A definition whose top level :py:class:`~roboto.experimental.boards.BoardDefinition` refuses fails validation:
    for example, one with an unknown top-level key, a missing ``time_range`` or ``panels``, a ``panels`` that is not a
    list, a ``stages`` that is neither a list nor null, a ``title`` that is neither a string nor null, or a malformed
    section or selection. The panels and stages in it are not checked and are stored as given, so the web app can
    show a broken one beside the rest of the board."""

    base_revision: Union[Annotated[int, pydantic.Field(ge=0)], NotSetType] = NotSet
    """The revision you loaded (:py:attr:`~roboto.experimental.boards.BoardRecord.revision`), not the revision you want.

    Required whenever the request writes definition content: a ``board_definition`` replacement, or a ``name``
    for a board whose stored definition has a ``title`` that is a non-empty string, since keeping the two equal
    rewrites that title. The record you loaded shows which case applies.

    The server compares a supplied base revision with the stored revision, on a rename that writes no definition
    content as well, and rejects a mismatch with
    :py:class:`~roboto.exceptions.RobotoBoardRevisionConflictException`, so a save built on an outdated revision
    cannot erase someone else's edit."""

    name: Union[Annotated[str, pydantic.StringConstraints(min_length=1, max_length=120)], NotSetType] = NotSet
    """The name of the board. Rewrites a ``title`` the stored definition already has, and never adds one.

    Must not be empty: the platform keeps the name equal to a definition ``title`` only while the title is a
    non-empty string, so an empty name written into the title would leave the two unequal, and no later rename
    could make them equal again. To keep the name, omit the field."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.field_validator("board_definition")
    @classmethod
    def validate_definition_top_level(
        cls, board_definition: Union[dict[str, Any], NotSetType]
    ) -> Union[dict[str, Any], NotSetType]:
        """Reject a definition whose top level :py:class:`~roboto.experimental.boards.BoardDefinition` refuses."""
        if isinstance(board_definition, NotSetType):
            return board_definition
        check_definition_top_level(board_definition)
        return board_definition

    @pydantic.model_validator(mode="after")
    def validate_at_least_one_change(self) -> "UpdateBoardRequest":
        """Reject a request with neither ``name`` nor ``board_definition``, which would change nothing."""
        if isinstance(self.name, NotSetType) and isinstance(self.board_definition, NotSetType):
            raise ValueError("A board update must supply name, board_definition, or both")
        return self

    @pydantic.model_validator(mode="after")
    def validate_base_revision_with_definition(self) -> "UpdateBoardRequest":
        """Require ``base_revision`` with a ``board_definition``.

        A rename of a board whose stored definition has a title needs one too. The server enforces that case,
        since only the stored board shows whether the title is there.
        """
        if isinstance(self.board_definition, NotSetType):
            return self
        if isinstance(self.base_revision, NotSetType):
            raise ValueError("base_revision must be provided when updating board_definition")
        return self

    @pydantic.model_validator(mode="after")
    def validate_name_and_title_agree(self) -> "UpdateBoardRequest":
        """Reject a request whose ``name`` differs from its definition's non-empty ``title``.

        The platform keeps the two equal, and such a request gives it no basis for choosing between them.
        """
        if isinstance(self.name, NotSetType) or isinstance(self.board_definition, NotSetType):
            return self

        title = definition_title(self.board_definition)
        if title is not None and title != self.name:
            raise ValueError(
                f"This request names the board '{self.name}' and titles its definition '{title}'. "
                "Supply one name, or supply matching values."
            )
        return self


class UpdateBoardAccessRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/boards/id/<board_id>/access``.

    Shares a board with the organization, permanently: ownership moves to the org principal. The
    definition and revision stay unchanged. No request makes a shared board personal again; to get
    a personal board, create a new board from a copy of this board's definition.
    """

    accessibility: Literal[BoardAccessibility.Organization]
    """Must be ``organization``, which moves ownership to the org principal. A request for ``user``
    accessibility fails validation."""
