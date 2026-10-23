# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import copy
import datetime
import typing

from ...exceptions import RobotoIllegalArgumentException
from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType, remove_not_set
from .definition import BoardDefinition
from .operations import (
    CreateBoardRequest,
    UpdateBoardAccessRequest,
    UpdateBoardRequest,
)
from .record import (
    BoardAccessibility,
    BoardRecord,
    definition_title,
)


class Board:
    """A board: panels arranged on a canvas, and the stages that provide their data.

    A board is stored on the platform as a named JSON document, its definition, which the Roboto web app reads to
    draw the board. A board is created personal to its creator, and :py:meth:`share_with_org` shares it with every
    member of its organization. Sharing a board does not share data: each viewer sees only the data they could
    already reach.

    A definition is given either as a :py:class:`BoardDefinition`, which checks the definition's outline as it is
    built, or as a ``dict``. A ``dict`` is refused before any request is made if :py:class:`BoardDefinition` refuses
    its top level. The panels and stages in a definition are stored as given.

    Each write of a board's definition advances its :py:attr:`revision`. :py:meth:`update` sends the revision this
    instance last read, so a change made from an outdated copy of the board is refused instead of replacing
    someone else's edit.
    """

    __record: BoardRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        definition: typing.Union[BoardDefinition, dict[str, typing.Any]],
        name: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Board":
        """Create a board that is personal to the caller.

        Args:
            definition: The board's definition.
            name: The name the board list and board page show. Defaults to the definition's ``title``. When both
                are given they must match.
            caller_org_id: Organization to create the board in. Required when the caller belongs to more than one.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Returns:
            The board.

        Raises:
            RobotoIllegalArgumentException: No name is given and the definition has no title to take one from.
                Raised before any request is made.
            pydantic.ValidationError: ``name`` is empty, is longer than 120 characters, or differs from the
                definition's title, or :py:class:`BoardDefinition` refuses the definition's top level. Raised before
                any request is made.
            RobotoConflictException: The caller already owns a board with this name in the organization.
            RobotoFeatureNotAvailableException: Boards are not available to the caller.

        Examples:
            Check a definition's outline, then save it as a board named after its title:

            >>> from roboto.experimental.boards import Board, BoardDefinition
            >>> definition = BoardDefinition.model_validate(
            ...     {
            ...         "schema_version": 1,
            ...         "title": "Event overview",
            ...         "time_range": "90d",
            ...         "stages": [
            ...             {
            ...                 "id": "stage-event-counts",
            ...                 "name": "EventCounts",
            ...                 "body": {
            ...                     "kind": "entity.query",
            ...                     "target": "events",
            ...                     "aggregate": {"op": "count", "groupBy": "name"},
            ...                 },
            ...             }
            ...         ],
            ...         "panels": [
            ...             {
            ...                 "kind": "table",
            ...                 "id": "event-counts-table",
            ...                 "bindings": [{"name": "event_counts", "stage": "stage-event-counts"}],
            ...             }
            ...         ],
            ...     }
            ... )
            >>> board = Board.create(definition)
            >>> board.name
            'Event overview'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        board_definition = _as_json_object(definition)
        board_name = name if name is not None else definition_title(board_definition)
        if board_name is None:
            raise RobotoIllegalArgumentException("Give the board a name, or give its definition a title")

        # A retried create whose first attempt succeeded would be refused as a duplicate name.
        record = roboto_client.post(
            "v1/boards/create",
            data=CreateBoardRequest(board_definition=board_definition, name=board_name),
            caller_org_id=caller_org_id,
            idempotent=False,
        ).to_record(BoardRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls,
        org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Board", None, None]:
        """List an organization's shared boards and the caller's own personal boards, ordered by name.

        Another member's personal board is never listed. An admin of the organization can still load one with
        :py:meth:`from_id`.

        Args:
            org_id: Organization whose boards to list. Required when the caller belongs to more than one.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Yields:
            Each of those boards.

        Raises:
            RobotoFeatureNotAvailableException: Boards are not available to the caller.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> for board in Board.for_org():
            ...     print(board.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token

            results = roboto_client.get(
                "v1/boards",
                caller_org_id=org_id,
                query=query,
            ).to_paginated_list(BoardRecord)

            for item in results.items:
                yield cls(record=item, roboto_client=roboto_client)

            next_token = results.next_token
            if not next_token:
                break

    @classmethod
    def from_id(
        cls,
        board_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Board":
        """Load a board by ID.

        Args:
            board_id: Unique identifier of the board.
            roboto_client: Roboto client instance. Uses the default if omitted.

        Returns:
            The board.

        Raises:
            RobotoNotFoundException: No board with this ID exists, or the caller cannot open it.
            RobotoFeatureNotAvailableException: Boards are not available to the caller.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_abc123")
            >>> board.name
            'Event overview'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/boards/id/{board_id}",
        ).to_record(BoardRecord)
        return cls(record=record, roboto_client=roboto_client)

    def __init__(
        self,
        record: BoardRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def accessibility(self) -> BoardAccessibility:
        """Who can open this board: only its owner and the organization's admins, or every member."""
        return self.__record.accessibility

    @property
    def board_id(self) -> str:
        """Unique identifier of this board."""
        return self.__record.board_id

    @property
    def created(self) -> datetime.datetime:
        """Timestamp when this board was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """User ID of this board's creator."""
        return self.__record.created_by

    @property
    def definition(self) -> dict[str, typing.Any]:
        """This board's definition as a JSON object.

        The object is a copy, so changing it does not change this board. Pass a changed copy to :py:meth:`update`
        to save it.
        """
        return copy.deepcopy(self.__record.board_definition)

    @property
    def modified(self) -> datetime.datetime:
        """Timestamp when this board was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """User ID of the last user to modify this board."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """The name the board list and board page show."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns this board."""
        return self.__record.org_id

    @property
    def owner_principal_id(self) -> str:
        """Principal that owns this board: ``org:<org_id>`` for a shared board, ``user:<user_id>`` for a
        personal one."""
        return self.__record.owner_principal_id

    @property
    def record(self) -> BoardRecord:
        """The wire-transmissible representation of this board."""
        return self.__record

    @property
    def revision(self) -> int:
        """How many times this board's definition had been written when this instance last read it."""
        return self.__record.revision

    def delete(self) -> None:
        """Delete this board.

        Raises:
            RobotoNotFoundException: The board no longer exists.
            RobotoUnauthorizedException: The caller is not an admin of the board's organization, and the board is
                shared or is another member's personal board.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> Board.from_id("bd_abc123").delete()
        """
        # A retried delete whose first attempt succeeded would be refused as not found.
        self.__roboto_client.delete(
            f"v1/boards/id/{self.board_id}",
            caller_org_id=self.org_id,
            idempotent=False,
        )

    def refresh(self) -> "Board":
        """Re-read this board from the platform, replacing every property backed by its record.

        Call it when something other than this instance may have changed the board, for example before retrying
        an :py:meth:`update` that was refused because the board had changed.

        Returns:
            This board.

        Raises:
            RobotoNotFoundException: The board no longer exists, or the caller can no longer open it.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_abc123")
            >>> board.refresh().revision
            4
        """
        self.__record = self.__roboto_client.get(
            f"v1/boards/id/{self.board_id}",
        ).to_record(BoardRecord)
        return self

    def share_with_org(self) -> "Board":
        """Share this board with every member of its organization, permanently.

        Ownership moves to the organization, and no request makes a shared board personal again. From then on
        every member can open and change the board, and only an admin of the organization can delete it. The
        definition and the revision stay as they are.

        Returns:
            This board.

        Raises:
            RobotoConflictException: The organization already has a shared board with this name.
            RobotoNotFoundException: The board no longer exists.
            RobotoUnauthorizedException: The board is personal, and the caller is neither its owner nor an admin
                of its organization.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_abc123").share_with_org()
            >>> board.accessibility
            <BoardAccessibility.Organization: 'organization'>
        """
        self.__record = self.__roboto_client.put(
            f"v1/boards/id/{self.board_id}/access",
            data=UpdateBoardAccessRequest(accessibility=BoardAccessibility.Organization),
            caller_org_id=self.org_id,
        ).to_record(BoardRecord)
        return self

    def update(
        self,
        definition: typing.Union[BoardDefinition, dict[str, typing.Any], NotSetType] = NotSet,
        name: typing.Union[str, NotSetType] = NotSet,
    ) -> "Board":
        """Replace this board's definition, rename it, or both.

        The change is made only if the board is still at the :py:attr:`revision` this instance last read.
        Otherwise it is refused with :py:class:`~roboto.exceptions.RobotoBoardRevisionConflictException`, whose
        ``current_board`` holds the stored board's record as a JSON object. Call :py:meth:`refresh`, apply the
        change to the refreshed definition, and update again.

        Args:
            definition: The definition that replaces the stored one whole. When it has a ``title`` and no ``name``
                is given, the board takes the title as its name.
            name: The board's new name. A ``title`` the stored definition already has is rewritten to match. When
                a definition with a title is also given, the two must match.

        Returns:
            This board.

        Raises:
            pydantic.ValidationError: Neither a definition nor a name is given, ``name`` is empty or longer than
                120 characters, ``name`` differs from the given definition's title, or :py:class:`BoardDefinition`
                refuses the definition's top level. Raised before any request is made.
            RobotoBoardRevisionConflictException: The board's definition was written after this instance last
                read it.
            RobotoConflictException: The board's owner already has another board with this name.
            RobotoNotFoundException: The board no longer exists.
            RobotoUnauthorizedException: The board is personal, and the caller is neither its owner nor an admin
                of its organization.

        Examples:
            Change the time range a board opens with:

            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_abc123")
            >>> definition = board.definition
            >>> definition["time_range"] = "30d"
            >>> board = board.update(definition=definition)
        """
        request = remove_not_set(
            UpdateBoardRequest(
                base_revision=self.revision,
                board_definition=definition if isinstance(definition, NotSetType) else _as_json_object(definition),
                name=name,
            )
        )
        # A retried update whose first attempt wrote the definition would carry an outdated revision and be refused.
        self.__record = self.__roboto_client.put(
            f"v1/boards/id/{self.board_id}",
            data=request,
            caller_org_id=self.org_id,
            idempotent=False,
        ).to_record(BoardRecord)
        return self


def _as_json_object(definition: typing.Union[BoardDefinition, dict[str, typing.Any]]) -> dict[str, typing.Any]:
    if isinstance(definition, BoardDefinition):
        return definition.model_dump(mode="json")
    return definition
