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

    Roboto stores a board as a named JSON document, its definition, which the Roboto web app reads to draw the board.
    A new board is personal to its creator, and ``share_with_org`` shares it with every member of its organization.
    Sharing a board does not share data: each viewer sees only the data they could already reach.

    ``create`` and ``update`` take a definition either as a ``BoardDefinition``, which checks the definition's outline
    as it is built, or as a JSON object. Either way, a definition whose top level ``BoardDefinition`` refuses raises
    ``pydantic.ValidationError`` before any request is made, and Roboto stores the panels and stages as given.

    Get a ``Board`` from ``create``, ``for_org`` or ``from_id``. To wrap a ``BoardRecord`` already fetched from
    Roboto, build a ``Board`` from it directly. Each instance holds a copy of the board's record: ``update`` and
    ``share_with_org`` update that copy from Roboto's response, and ``refresh`` fetches changes made elsewhere.

    Args:
        record: Record of the board.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
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
            definition: Board definition, as a ``BoardDefinition`` or a JSON object.
            name: Human-readable name of the board, from 1 to 120 characters, which the board list and board page
                show. ``None`` takes the definition's ``title``. When both are given, they must match.
            caller_org_id: Organization to create the board in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new board.

        Raises:
            RobotoIllegalArgumentException: ``name`` is ``None`` and the definition has no non-empty ``title`` to
                take one from. Raised before any request is made.
            pydantic.ValidationError: ``name`` is empty, is longer than 120 characters, or differs from the
                definition's ``title``, or ``BoardDefinition`` refuses the definition's top level. Raised before any
                request is made.
            RobotoConflictException: The caller already owns a board with this name in the organization.
            RobotoFeatureNotAvailableException: Boards are not enabled for the caller.

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

        Another member's personal board is never listed, even for an organization administrator, who can still
        fetch it with ``from_id``. Boards are fetched a page at a time as iteration proceeds.

        Args:
            org_id: Organization whose boards to list. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Each listed board.

        Raises:
            RobotoFeatureNotAvailableException: Boards are not enabled for the caller. It surfaces on the first
                iteration.

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
        """Fetch a board by ID.

        Any member of the board's organization can fetch a shared board. Only its owner and organization
        administrators can fetch a personal board.

        Args:
            board_id: Unique ID of the board.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No board has this ID, or the caller cannot open it.
            RobotoFeatureNotAvailableException: Boards are not enabled for the caller.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_12345")
            >>> print(board.name)
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
        """Accessibility of the board, from ``owner_principal_id``.

        ``BoardAccessibility.Organization`` when the organization owns the board, ``BoardAccessibility.User``
        otherwise. ``BoardAccessibility`` describes who can open and edit the board at each value.
        """
        return self.__record.accessibility

    @property
    def board_id(self) -> str:
        """Unique ID of the board, beginning with ``bd_``."""
        return self.__record.board_id

    @property
    def created(self) -> datetime.datetime:
        """Time the board was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the board.

        ``BoardRecord.created_by`` describes how it differs from ``owner_principal_id``.
        """
        return self.__record.created_by

    @property
    def definition(self) -> dict[str, typing.Any]:
        """Board definition as a JSON object.

        Each read returns a new copy, so changing it changes neither this instance nor the board. Pass a changed copy
        to ``update`` to save it. ``BoardRecord.board_definition`` describes how Roboto stores the definition.
        """
        return copy.deepcopy(self.__record.board_definition)

    @property
    def modified(self) -> datetime.datetime:
        """Time the board was last modified, by a change to its name or definition or by sharing it."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the board."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Human-readable name of the board, which the board list and board page show.

        ``BoardRecord.name`` describes which names must be unique.
        """
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization the board belongs to."""
        return self.__record.org_id

    @property
    def owner_principal_id(self) -> str:
        """Principal that owns the board, as ``<type>:<id>``.

        The string form of :py:class:`~roboto.principal.RobotoPrincipal`. ``BoardRecord.owner_principal_id``
        describes the values it takes.
        """
        return self.__record.owner_principal_id

    @property
    def record(self) -> BoardRecord:
        """Record of the board that this instance holds.

        ``refresh`` replaces it with the current one.
        """
        return self.__record

    @property
    def revision(self) -> int:
        """Number of times the board's definition content has been written, ``0`` for a new board.

        ``BoardRecord.revision`` describes which writes advance it and how ``update`` uses it.
        """
        return self.__record.revision

    def delete(self) -> None:
        """Delete the board. This cannot be undone.

        Only the board's owner and organization administrators can delete it. The organization owns a shared board, so
        only an organization administrator can delete one.

        Raises:
            RobotoNotFoundException: The board no longer exists.
            RobotoUnauthorizedException: The caller is neither the board's owner nor an administrator of its
                organization.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> Board.from_id("bd_12345").delete()
        """
        # A retried delete whose first attempt succeeded would be refused as not found.
        self.__roboto_client.delete(
            f"v1/boards/id/{self.board_id}",
            caller_org_id=self.org_id,
            idempotent=False,
        )

    def refresh(self) -> "Board":
        """Replace this instance's record with the board's current record from Roboto.

        Use it to see changes made elsewhere, such as before retrying an ``update`` that Roboto refused because the
        board had changed.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The board no longer exists, or the caller can no longer open it.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_12345")
            >>> print(board.refresh().revision)
        """
        self.__record = self.__roboto_client.get(
            f"v1/boards/id/{self.board_id}",
        ).to_record(BoardRecord)
        return self

    def share_with_org(self) -> "Board":
        """Share the board with every member of its organization, permanently.

        The organization becomes the board's owner. From then on every member can open and edit the board, and only an
        organization administrator can delete it. The definition and revision stay unchanged. No request makes a
        shared board personal again; to get a personal board, create a new board from a copy of this board's
        ``definition``. Only the board's owner and organization administrators can share a personal board.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoConflictException: The organization already has a shared board with this name.
            RobotoNotFoundException: The board no longer exists.
            RobotoUnauthorizedException: The board is personal, and the caller is neither its owner nor an
                administrator of its organization.

        Examples:
            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_12345").share_with_org()
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
        """Replace the board's definition, rename it, or both.

        Roboto makes the change only if the board is still at the ``revision`` this instance holds, so a change built
        on an outdated copy cannot erase someone else's edit. Otherwise it raises
        :py:class:`~roboto.exceptions.RobotoBoardRevisionConflictException`, whose ``current_board`` holds the stored
        board's record as a JSON object. To retry:

        1. Call ``refresh``.
        2. Apply the change to the refreshed ``definition``.
        3. Call ``update`` again.

        Any member of the board's organization can update a shared board. Only its owner and organization
        administrators can update a personal board.

        Args:
            definition: Board definition that replaces the stored one whole, as a ``BoardDefinition`` or a JSON
                object. When it has a non-empty ``title`` and ``name`` is not given, the board takes the title as its
                name. Left unset, the definition is unchanged.
            name: New human-readable name of the board, from 1 to 120 characters. Rewrites a ``title`` the stored
                definition already has, and never adds one. When ``definition`` has a non-empty ``title`` too, the
                two must match. Left unset, the name is unchanged unless ``definition`` renames the board.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            pydantic.ValidationError: Neither ``definition`` nor ``name`` is given, ``name`` is empty or longer than
                120 characters, ``name`` differs from the given definition's ``title``, or ``BoardDefinition``
                refuses the definition's top level. Raised before any request is made.
            RobotoBoardRevisionConflictException: The board's definition was written after this instance read it.
            RobotoConflictException: The board's owner already has another board with this name.
            RobotoNotFoundException: The board no longer exists.
            RobotoUnauthorizedException: The board is personal, and the caller is neither its owner nor an
                administrator of its organization.

        Examples:
            Change the time range a board opens with:

            >>> from roboto.experimental.boards import Board
            >>> board = Board.from_id("bd_12345")
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
