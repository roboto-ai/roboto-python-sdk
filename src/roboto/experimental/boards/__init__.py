# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Boards: panels arranged on a canvas, and the stages that provide their data, stored as a named JSON document.

A new board is personal to the user who created it, and sharing it with its organization, which cannot be undone,
lets every member open and edit it. Use ``Board`` to create, list, update, and share boards, and ``BoardDefinition``
to build a definition whose outline is checked as it is built.
"""

from .board import Board
from .definition import (
    BoardCalendar,
    BoardColumnControlDomain,
    BoardControlFilterBody,
    BoardControlOption,
    BoardDefinition,
    BoardEntityFieldControlDomain,
    BoardFieldControlBody,
    BoardFieldControlOption,
    BoardPanel,
    BoardPanelBinding,
    BoardSection,
    BoardSelection,
    BoardStage,
    BoardStageBody,
    BoardStaticControlDomain,
    BoardTopicFieldPath,
    BoardValueControlBody,
    BoardValueControlDomain,
)
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

__all__ = [
    "Board",
    "BoardAccessibility",
    "BoardCalendar",
    "BoardColumnControlDomain",
    "BoardControlFilterBody",
    "BoardControlOption",
    "BoardDefinition",
    "BoardEntityFieldControlDomain",
    "BoardFieldControlBody",
    "BoardFieldControlOption",
    "BoardPanel",
    "BoardPanelBinding",
    "BoardRecord",
    "BoardSection",
    "BoardSelection",
    "BoardStage",
    "BoardStageBody",
    "BoardStaticControlDomain",
    "BoardTopicFieldPath",
    "BoardValueControlBody",
    "BoardValueControlDomain",
    "CreateBoardRequest",
    "UpdateBoardAccessRequest",
    "UpdateBoardRequest",
    "definition_title",
]
