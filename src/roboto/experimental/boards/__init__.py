# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Boards a person builds on the Roboto platform and opens again from anywhere.

A board is a named JSON document, stored on the platform, describing panels arranged on a canvas and the stages
that provide their data. A board is either personal to the user who owns it or shared with every member of its
organization.
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
    "BoardValueControlBody",
    "BoardValueControlDomain",
    "CreateBoardRequest",
    "UpdateBoardAccessRequest",
    "UpdateBoardRequest",
    "definition_title",
]
