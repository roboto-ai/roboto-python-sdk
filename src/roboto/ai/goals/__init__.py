# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Goals: structured outcomes attached to a turn of a thread, which Roboto's AI must achieve before the turn completes.

Pass goals such as :py:class:`~roboto.ai.goals.DatasetTriageGoal` or :py:class:`~roboto.ai.goals.CreateEventsGoal` to
:py:meth:`~roboto.ai.agent_thread.AgentThread.start` or :py:meth:`~roboto.ai.agent_thread.AgentThread.send` to have the
AI summarize a dataset or session, tag it with the labels that fit, or create events on it. Each goal in
:py:attr:`~roboto.ai.agent_thread.AgentThread.goals` gives its status and its :py:const:`~roboto.ai.goals.GoalResult`,
such as the AI's decision on each label or the events it created. When the AI cannot achieve every goal of a turn,
:py:meth:`~roboto.ai.agent_thread.AgentThread.run` raises
:py:class:`~roboto.ai.agent_thread.RobotoAgentGoalsFailedException`.
"""

from .achieve_inputs import (
    CreateEventsAchieveInput,
    DatasetSummaryAchieveInput,
    DatasetTriageAchieveInput,
    EventSpec,
    EventSpecBase,
    LabelDecision,
    SessionCreateEventsAchieveInput,
    SessionEventSpec,
    SessionSummaryAchieveInput,
    SessionTriageAchieveInput,
)
from .results import (
    CreateEventsGoalResult,
    DatasetSummaryGoalResult,
    DatasetTriageGoalResult,
    GoalResult,
    GoalResultBase,
    SessionCreateEventsGoalResult,
    SessionSummaryGoalResult,
    SessionTriageGoalResult,
)
from .types import (
    AgentGoal,
    AgentGoalStatus,
    CreateEventsGoal,
    DatasetSummaryAgentGoal,
    DatasetTriageGoal,
    GoalType,
    SessionCreateEventsGoal,
    SessionSummaryAgentGoal,
    SessionTriageGoal,
)

__all__ = [
    "AgentGoal",
    "AgentGoalStatus",
    "CreateEventsAchieveInput",
    "CreateEventsGoal",
    "CreateEventsGoalResult",
    "DatasetSummaryAchieveInput",
    "DatasetSummaryAgentGoal",
    "DatasetSummaryGoalResult",
    "DatasetTriageAchieveInput",
    "DatasetTriageGoal",
    "DatasetTriageGoalResult",
    "EventSpec",
    "EventSpecBase",
    "GoalResult",
    "GoalResultBase",
    "GoalType",
    "LabelDecision",
    "SessionCreateEventsAchieveInput",
    "SessionCreateEventsGoal",
    "SessionCreateEventsGoalResult",
    "SessionEventSpec",
    "SessionSummaryAchieveInput",
    "SessionSummaryAgentGoal",
    "SessionSummaryGoalResult",
    "SessionTriageAchieveInput",
    "SessionTriageGoal",
    "SessionTriageGoalResult",
]
