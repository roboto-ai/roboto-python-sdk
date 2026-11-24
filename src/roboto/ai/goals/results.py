# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Annotated, Literal, Optional, Union

import pydantic

# Imported from core.content, not core.record: core.record imports this package, so importing it here would be
# circular.
from ..core.content import (
    AgentToolResultContent,
    AgentToolUseContent,
)
from .achieve_inputs import (
    CreateEventsAchieveInput,
    DatasetSummaryAchieveInput,
    DatasetTriageAchieveInput,
    SessionCreateEventsAchieveInput,
    SessionSummaryAchieveInput,
    SessionTriageAchieveInput,
    TriageAchieveInput,
)
from .types import AgentGoalStatus, GoalType


class GoalResultBase(pydantic.BaseModel):
    """Base of every goal result: the goal's status and the tool use in which the AI submitted the result.

    Roboto subclasses it once per goal type, together with the model of the fields the AI submits for that type, such
    as :py:class:`~roboto.ai.goals.DatasetSummaryAchieveInput`. Each subclass is a member of ``GoalResult``.
    """

    status: AgentGoalStatus
    """Status of the goal when the thread was fetched.

    While it is :py:attr:`~roboto.ai.goals.AgentGoalStatus.PENDING`, the result comes from the AI's latest attempt, and
    a later attempt can replace it.
    """

    achieve_tool_use: AgentToolUseContent
    """Tool use in which the AI submitted the result.

    Its ``input`` holds the submitted fields as a dictionary; the subclass's own fields, such as ``summary``, are built
    from it.
    """

    achieve_tool_result: Optional[AgentToolResultContent] = None
    """Tool result that answers ``achieve_tool_use``, or ``None`` when the thread's messages hold none.

    A failed goal whose last attempt errored before Roboto recorded its result has a tool use and no tool result.
    """


class DatasetSummaryGoalResult(GoalResultBase, DatasetSummaryAchieveInput):
    """Result of a dataset summary goal: the summary the AI wrote for the dataset, in ``summary``.

    The goal is a :py:class:`~roboto.ai.goals.DatasetSummaryAgentGoal`.
    """

    goal_type: Literal[GoalType.DATASET_SUMMARY] = GoalType.DATASET_SUMMARY
    """Kind of goal, always :py:attr:`~roboto.ai.goals.GoalType.DATASET_SUMMARY`."""


class TriageGoalResultBase(GoalResultBase, TriageAchieveInput):
    """Base of ``DatasetTriageGoalResult`` and ``SessionTriageGoalResult``: the AI's decision on each label of a goal.

    ``label_decisions`` holds one decision for each label in the goal's vocabulary, and ``applied_labels`` the labels
    that apply.
    """

    @property
    def applied_labels(self) -> list[str]:
        """Labels the AI decided apply, in the order of ``label_decisions``.

        When the goal is achieved, these are the labels Roboto added as tags to the dataset or session. Tags have no
        order; ``sorted(result.applied_labels)`` gives a stable one.
        """
        return [d.label for d in self.label_decisions if d.applies]


class DatasetTriageGoalResult(TriageGoalResultBase, DatasetTriageAchieveInput):
    """Result of a dataset triage goal: the AI's decision on each label, and the labels it tagged the dataset with.

    The goal is a :py:class:`~roboto.ai.goals.DatasetTriageGoal`.
    """

    goal_type: Literal[GoalType.DATASET_TRIAGE] = GoalType.DATASET_TRIAGE
    """Kind of goal, always :py:attr:`~roboto.ai.goals.GoalType.DATASET_TRIAGE`."""


class CreateEventsGoalResult(GoalResultBase, CreateEventsAchieveInput):
    """Result of a dataset events goal: the events the AI submitted for the dataset, in ``events``.

    The goal is a :py:class:`~roboto.ai.goals.CreateEventsGoal`. The result does not hold the IDs of the events Roboto
    created; to find them, list the dataset's events with :py:meth:`~roboto.domain.events.Event.get_by_dataset` and
    match their names and time ranges.
    """

    goal_type: Literal[GoalType.CREATE_EVENTS] = GoalType.CREATE_EVENTS
    """Kind of goal, always :py:attr:`~roboto.ai.goals.GoalType.CREATE_EVENTS`."""


class SessionSummaryGoalResult(GoalResultBase, SessionSummaryAchieveInput):
    """Result of a session summary goal: the summary the AI wrote for the session, in ``summary``.

    The goal is a :py:class:`~roboto.ai.goals.SessionSummaryAgentGoal`.
    """

    goal_type: Literal[GoalType.SESSION_SUMMARY] = GoalType.SESSION_SUMMARY
    """Kind of goal, always :py:attr:`~roboto.ai.goals.GoalType.SESSION_SUMMARY`."""


class SessionTriageGoalResult(TriageGoalResultBase, SessionTriageAchieveInput):
    """Result of a session triage goal: the AI's decision on each label, and the labels it tagged the session with.

    The goal is a :py:class:`~roboto.ai.goals.SessionTriageGoal`.
    """

    goal_type: Literal[GoalType.SESSION_TRIAGE] = GoalType.SESSION_TRIAGE
    """Kind of goal, always :py:attr:`~roboto.ai.goals.GoalType.SESSION_TRIAGE`."""


class SessionCreateEventsGoalResult(GoalResultBase, SessionCreateEventsAchieveInput):
    """Result of a session events goal: the events the AI submitted for the session, in ``events``.

    The goal is a :py:class:`~roboto.ai.goals.SessionCreateEventsGoal`. The result does not hold the IDs of the events
    Roboto created; to find them, list the session's events with
    :py:meth:`~roboto.experimental.sessions.Session.list_events`.
    """

    goal_type: Literal[GoalType.SESSION_CREATE_EVENTS] = GoalType.SESSION_CREATE_EVENTS
    """Kind of goal, always :py:attr:`~roboto.ai.goals.GoalType.SESSION_CREATE_EVENTS`."""


# In the SDK, adding a goal type takes:
# 1. A GoalType member, and an AgentGoal subclass in types.py, added to the AgentGoal union.
# 2. A model of the fields the AI submits, in achieve_inputs.py.
# 3. A subclass here of GoalResultBase and that model, which declares goal_type as a Literal of the new member, added
#    to the GoalResult union.
GoalResult = Annotated[
    Union[
        DatasetSummaryGoalResult,
        DatasetTriageGoalResult,
        CreateEventsGoalResult,
        SessionSummaryGoalResult,
        SessionTriageGoalResult,
        SessionCreateEventsGoalResult,
    ],
    pydantic.Field(discriminator="goal_type"),
]
"""Result of a goal of any type, as :py:attr:`~roboto.ai.agent_thread.AgentThreadGoalView.result` returns it.

One of ``DatasetSummaryGoalResult``, ``DatasetTriageGoalResult``, ``CreateEventsGoalResult``,
``SessionSummaryGoalResult``, ``SessionTriageGoalResult`` or ``SessionCreateEventsGoalResult``, whichever the goal's
``goal_type`` selects.
"""
