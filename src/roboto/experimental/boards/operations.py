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
    """Request body for ``Board.create``, which creates a board that is personal to the caller.

    ``UpdateBoardAccessRequest`` shares the board with its organization. Building it raises
    ``pydantic.ValidationError`` when:

    - ``name`` is empty or longer than 120 characters.
    - ``BoardDefinition`` refuses the top level of ``board_definition``.
    - ``name`` differs from the definition's ``title``, when the title is a non-empty string.
    """

    board_definition: Annotated[dict[str, Any], ValidatedAgainst(BoardDefinition)]
    """Board definition as a JSON object, stored as ``BoardRecord.board_definition`` describes.

    A top-level ``title`` that is a non-empty string must equal ``name``. A definition with no title is stored
    without one."""

    name: str = pydantic.Field(min_length=1, max_length=120)
    """Human-readable name of the board, from 1 to 120 characters, which the board list and board page show.

    Names are unique per owner within an organization, so a name the caller already uses for another of their
    boards raises ``RobotoConflictException``."""

    @pydantic.field_validator("board_definition")
    @classmethod
    def validate_definition_top_level(cls, board_definition: dict[str, Any]) -> dict[str, Any]:
        """Reject a definition whose top level ``BoardDefinition`` refuses, without checking its panels and stages."""
        check_definition_top_level(board_definition)
        return board_definition

    @pydantic.model_validator(mode="after")
    def validate_name_and_title_agree(self) -> "CreateBoardRequest":
        """Reject a ``name`` that differs from the definition's ``title``, when the title is a non-empty string."""
        title = definition_title(self.board_definition)
        if title is not None and title != self.name:
            raise ValueError("The board name and its definition title must match")
        return self


class UpdateBoardRequest(pydantic.BaseModel):
    """Request body for ``Board.update``, which renames a board, replaces its definition, or both.

    A ``name`` or ``board_definition`` left unset (``NotSet``) is unchanged, except that a definition's ``title``
    renames the board. Any member of the organization may send it for a shared board; only the owner and
    organization administrators may send it for a personal board. ``UpdateBoardAccessRequest`` changes who can open
    a board.

    Building it raises ``pydantic.ValidationError`` when:

    - Neither ``name`` nor ``board_definition`` is set.
    - ``board_definition`` is set and ``base_revision`` is not.
    - ``base_revision`` is negative.
    - ``name`` is empty or longer than 120 characters.
    - ``BoardDefinition`` refuses the top level of ``board_definition``.
    - ``name`` differs from the definition's ``title``, when both are set and the title is a non-empty string.
    """

    board_definition: Union[Annotated[dict[str, Any], ValidatedAgainst(BoardDefinition)], NotSetType] = NotSet
    """Board definition as a JSON object, which replaces the stored one whole.

    The definition is stored as ``BoardRecord.board_definition`` describes.

    A top-level ``title`` that is a non-empty string is kept equal to the board's name: with no ``name`` in the
    request, the board takes the title as its name. A definition with no title leaves the name alone, and Roboto
    never adds a title."""

    base_revision: Union[Annotated[int, pydantic.Field(ge=0)], NotSetType] = NotSet
    """Revision the change was built on: the ``BoardRecord.revision`` you loaded, not the revision you want.

    Required whenever the request writes definition content: a ``board_definition``, or a ``name`` for a board whose
    stored definition has a ``title`` that is a non-empty string, since keeping the two equal rewrites that title.
    The record you loaded shows which case applies; a rename that rewrites a title and sends no base revision raises
    ``RobotoInvalidRequestException``.

    Roboto compares a supplied base revision with the stored revision, on a rename that writes no definition content
    as well. A mismatch raises :py:class:`~roboto.exceptions.RobotoBoardRevisionConflictException`, so a change built
    on an outdated revision cannot replace someone else's edit."""

    name: Union[Annotated[str, pydantic.StringConstraints(min_length=1, max_length=120)], NotSetType] = NotSet
    """New human-readable name of the board, from 1 to 120 characters.

    Rewrites a ``title`` the stored definition already has, and never adds one. A name the board's owner already
    uses for another board raises ``RobotoConflictException``."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)

    @pydantic.field_validator("board_definition")
    @classmethod
    def validate_definition_top_level(
        cls, board_definition: Union[dict[str, Any], NotSetType]
    ) -> Union[dict[str, Any], NotSetType]:
        """Reject a definition whose top level ``BoardDefinition`` refuses, without checking its panels and stages."""
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
        """Reject a ``board_definition`` sent without ``base_revision``.

        Roboto rejects a rename that rewrites the stored definition's title without one, since only the stored board
        shows whether it has a title.
        """
        if isinstance(self.board_definition, NotSetType):
            return self
        if isinstance(self.base_revision, NotSetType):
            raise ValueError("base_revision must be provided when updating board_definition")
        return self

    @pydantic.model_validator(mode="after")
    def validate_name_and_title_agree(self) -> "UpdateBoardRequest":
        """Reject a ``name`` that differs from the definition's ``title``, when the title is a non-empty string.

        Roboto keeps the two equal, and such a request does not say which one to keep.
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
    """Request body for ``Board.share_with_org``, which shares a board with its organization permanently.

    The organization becomes the board's owner, and the definition and revision stay unchanged. No request makes a
    shared board personal again; to get a personal board, create a new board from a copy of this board's definition.
    Only the board's owner and organization administrators may share a personal board. Building it raises
    ``pydantic.ValidationError`` when ``accessibility`` is anything but ``BoardAccessibility.Organization``.
    """

    accessibility: Literal[BoardAccessibility.Organization]
    """Accessibility to give the board, always ``BoardAccessibility.Organization``."""
