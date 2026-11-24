# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum


def definition_title(board_definition: dict[str, typing.Any]) -> str | None:
    """Return the definition's top-level ``title`` when it is a non-empty string, else ``None``.

    Roboto keeps ``BoardRecord.name`` equal to the title this returns. A title that is ``None`` or ``""`` is stored
    as sent, leaves the name unchanged, and returns ``None`` here. A title of any other type also returns ``None``,
    but ``BoardDefinition`` refuses a definition that has one, so no request can carry it.
    """
    title = board_definition.get("title")
    if isinstance(title, str) and title != "":
        return title
    return None


class BoardAccessibility(StrEnum):
    """Accessibility of a board: who can open and edit it.

    A new board is ``User``. ``Board.share_with_org`` makes it ``Organization``, and no request makes it ``User``
    again. ``BoardRecord.accessibility`` holds a board's value.
    """

    Organization = "organization"
    """Shared with the organization: every member of the organization can open and edit the board."""

    User = "user"
    """Personal to the user who owns the board.

    Only that user and the organization's administrators can open and edit it."""


class BoardRecord(pydantic.BaseModel):
    """Data record of a board, as the Roboto API returns it.

    A board is panels arranged on a canvas, and the stages that provide their data, stored as a named JSON document,
    its definition, which the Roboto web app reads to draw the board. ``Board`` wraps this record with methods that
    act on the board, and exposes it as ``Board.record``.
    """

    board_definition: dict[str, typing.Any]
    """Board definition as a JSON object: panels arranged on a canvas and the stages that provide their data.

    The definition carries its own schema version for the clients that read it. Roboto changes only its top-level
    ``title``, which it keeps equal to ``name`` while the title is a non-empty string. Roboto refuses a request whose
    definition ``BoardDefinition`` refuses at the top level. The panels and stages inside are stored as sent, so one
    that the Roboto web app cannot read comes back unchanged, and a person can fix it in the board's JSON editor.

    Roboto stores the definition as parsed JSON, so it may return keys in a different order, keep only the last of a
    duplicated key, and write a number differently from how it was sent."""

    board_id: str
    """Unique ID of the board, beginning with ``bd_``."""

    created: datetime.datetime
    """Time the board was created."""

    created_by: str
    """ID of the user who created the board.

    It grants no access; ``owner_principal_id`` decides who owns the board."""

    modified: datetime.datetime
    """Time the board was last modified, by a change to its name or definition or by sharing it."""

    modified_by: str
    """ID of the user who last modified the board."""

    name: str
    """Human-readable name of the board, which the board list and board page show.

    Unique among the boards one owner holds in an organization. Boards with different owners may share a name, so two
    boards a user can open may have the same name."""

    org_id: str
    """ID of the organization the board belongs to."""

    owner_principal_id: str
    """Principal that owns the board, as ``<type>:<id>``.

    The value is the string form of :py:class:`~roboto.principal.RobotoPrincipal`: ``org:<org_id>`` for a board
    shared with the organization, ``user:<user_id>`` for a personal board. The owner decides who can open the board,
    as ``BoardAccessibility`` describes.
    """

    revision: int = 0
    """Number of times the board's definition content has been written, ``0`` for a new board.

    Roboto advances it on each write of definition content: a new definition, or a rename that rewrites the
    definition's ``title``. Sharing a board, and renaming one whose definition has no title, leave it unchanged.
    Roboto sets it; no request does. A request that writes definition content sends the revision the caller loaded as
    ``UpdateBoardRequest.base_revision``, so that Roboto refuses a write built on an outdated revision instead of
    erasing someone else's edit. ``Board.update`` sends it for you.
    """

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def accessibility(self) -> BoardAccessibility:
        """Accessibility of the board, derived from ``owner_principal_id``.

        ``BoardAccessibility.Organization`` when the organization owns the board, ``BoardAccessibility.User``
        otherwise."""
        if self.owner_principal_id.startswith("org:"):
            return BoardAccessibility.Organization
        return BoardAccessibility.User
