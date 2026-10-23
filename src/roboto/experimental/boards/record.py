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

    :py:attr:`BoardRecord.name` is kept equal to the title this returns. A ``null`` or empty title is stored as
    sent, leaves the name alone, and reads here as ``None``. A request whose title is any other kind of value is
    refused.
    """
    title = board_definition.get("title")
    if isinstance(title, str) and title != "":
        return title
    return None


class BoardAccessibility(StrEnum):
    """
    Who can open a board.

    A new board is ``user``: only the user who created it and the organization's admins can open it. Sharing it with
    :py:class:`~roboto.experimental.boards.UpdateBoardAccessRequest` makes it ``organization``, for good: every member
    of the organization can then open and edit it. :py:attr:`BoardRecord.accessibility` says which applies to a
    board.
    """

    Organization = "organization"
    """Every member of the organization that owns the board can open and edit it."""

    User = "user"
    """Only the user who owns the board, and the organization's admins, can open it."""


class BoardRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a board."""

    board_definition: dict[str, typing.Any]
    """The board definition as a JSON object, describing panels arranged on a canvas and the stages that provide
    their data.

    The definition carries its own schema version for the clients that read it. The platform writes only its
    top-level ``title``, which is kept equal to :py:attr:`name` while it is a non-empty string. A request is
    refused when :py:class:`~roboto.experimental.boards.BoardDefinition` refuses its definition's top level. The
    panels and stages inside are stored as sent, so a panel or stage that a client cannot parse comes back unchanged,
    and a person can fix it in the board's JSON editor.

    The platform stores the definition as parsed JSON, so it may return keys in a different order, keep only the
    last of a duplicated key, and write a number differently from how it was sent."""

    board_id: str
    """Unique identifier for the board."""

    created: datetime.datetime
    """Timestamp when the board was created."""

    created_by: str
    """User ID of the board's creator. Audit metadata only; ownership is carried by
    :py:attr:`owner_principal_id`."""

    modified: datetime.datetime
    """Timestamp when the board was last modified."""

    modified_by: str
    """User ID of the last user to modify the board."""

    name: str
    """Human-readable name for the board, which the board list and board page show. Unique per
    owner within an organization; boards with different owners may share a name, so by-name
    lookups can match more than one board."""

    org_id: str
    """Organization ID that owns the board."""

    owner_principal_id: str
    """Principal that owns the board, serialized in the
    :py:class:`~roboto.principal.RobotoPrincipal` ``ptype:id`` format.

    ``org:<org_id>`` for a board shared with the organization, ``user:<user_id>`` for a personal board. The owner
    alone decides who can open the board: any member of the organization for a shared board, the owning user or an
    org admin for a personal one. Board names are unique per owner within an organization.
    """

    revision: int = 0
    """How many times the board's definition content has been written, starting at 0.

    The server advances it on each write of definition content: a new definition, or a rename that rewrites the
    definition's ``title``. Sharing a board, and renaming one whose definition has no title, leave it unchanged.
    Clients never set it. They send the value they loaded back as ``base_revision`` when writing definition
    content, so the server can reject a write built on an outdated revision instead of erasing someone else's edit.
    """

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def accessibility(self) -> BoardAccessibility:
        """Computed from :py:attr:`owner_principal_id`: ``organization`` when the org principal owns the board,
        ``user`` otherwise."""
        if self.owner_principal_id.startswith("org:"):
            return BoardAccessibility.Organization
        return BoardAccessibility.User
