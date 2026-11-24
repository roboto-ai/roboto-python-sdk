# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing
from typing import Optional

from ...exceptions import RobotoInvalidRequestException
from ...templating import PLACEHOLDER_RE
from ..agent_thread.record import StartAgentThreadRequest
from ..goals.types import (
    AgentGoal,
    CreateEventsGoal,
    DatasetSummaryAgentGoal,
    DatasetTriageGoal,
    SessionCreateEventsGoal,
    SessionSummaryAgentGoal,
    SessionTriageGoal,
)
from .record import AgentSubject, TemplateVariable, TemplateVariableType

_SUBJECT_VARIABLE_TYPES: dict[AgentSubject, TemplateVariableType] = {
    AgentSubject.DATASET: TemplateVariableType.DATASET_ID,
    AgentSubject.SESSION: TemplateVariableType.SESSION_ID,
}

_SUBJECT_ID_FIELDS: dict[AgentSubject, str] = {
    AgentSubject.DATASET: "dataset_id",
    AgentSubject.SESSION: "session_id",
}


def infer_agent_subject(
    request_template: StartAgentThreadRequest,
    variables: collections.abc.Sequence[TemplateVariable],
) -> Optional[AgentSubject]:
    """Return the kind of resource an agent is launched on, worked out from its goals and variables.

    Roboto calls this when it returns an agent, and sets :py:attr:`~roboto.ai.agent.AgentRecord.subject` to the result.

    An agent with goals takes the subject of its first goal: every goal acts on a dataset or on a session, and
    ``validate_agent_subject`` rejects an agent whose goals disagree. An agent without goals is launched on a dataset
    when one of its variables has type :py:attr:`~roboto.ai.agent.TemplateVariableType.DATASET_ID` and none has type
    ``SESSION_ID``, and on a session in the reverse case.

    Args:
        request_template: Request that starts each of the agent's threads.
        variables: Variables of the agent.

    Returns:
        Subject of the agent, or ``None`` when it has none: the agent has no goals, and its variables include both a
        dataset ID and a session ID, or neither.

    Examples:
        >>> from roboto.ai.agent import TemplateVariable, TemplateVariableType, infer_agent_subject
        >>> from roboto.ai.agent_thread import StartAgentThreadRequest
        >>> from roboto.ai.goals import SessionSummaryAgentGoal
        >>> template = StartAgentThreadRequest(goals=[SessionSummaryAgentGoal(session_id="{{session.id}}")])
        >>> variables = [TemplateVariable(name="session.id", type=TemplateVariableType.SESSION_ID)]
        >>> infer_agent_subject(template, variables)
        <AgentSubject.SESSION: 'session'>
    """
    if request_template.goals:
        subject, _ = goal_subject(request_template.goals[0])
        return subject

    variable_types = {variable.type for variable in variables}
    subjects = [
        subject for subject, variable_type in _SUBJECT_VARIABLE_TYPES.items() if variable_type in variable_types
    ]
    return subjects[0] if len(subjects) == 1 else None


def validate_agent_subject(
    request_template: StartAgentThreadRequest,
    variables: collections.abc.Sequence[TemplateVariable],
) -> None:
    """Reject an agent whose goals mix datasets and sessions, or whose goal IDs name the wrong kind of variable.

    Roboto calls this when an agent is created or updated. An agent is launched on either a dataset or a session, so
    all of its goals must act on the same kind of resource. A goal's ``dataset_id`` or ``session_id`` must be a
    literal ID, which pins the agent to one dataset or session, or exactly one ``{{name}}`` placeholder naming a
    variable of the matching type: :py:attr:`~roboto.ai.agent.TemplateVariableType.DATASET_ID` or ``SESSION_ID``. A
    placeholder that names no variable of the agent passes this check; building
    :py:class:`~roboto.ai.agent.AgentRecord` rejects it.

    Args:
        request_template: Request that starts each of the agent's threads.
        variables: Variables of the agent.

    Raises:
        RobotoInvalidRequestException: The goals act on both datasets and sessions, or a goal's ``dataset_id`` or
            ``session_id`` embeds a placeholder in other text or names a variable of the wrong type.
    """
    variable_types = {variable.name: variable.type for variable in variables}
    first_subject: Optional[tuple[int, AgentGoal, AgentSubject]] = None
    for index, goal in enumerate(request_template.goals or []):
        subject, subject_id = goal_subject(goal)
        if first_subject is None:
            first_subject = (index, goal, subject)
        elif subject is not first_subject[2]:
            first_index, first_goal, first_goal_subject = first_subject
            raise RobotoInvalidRequestException(
                f"goals[{index}] ({goal.goal_type}) acts on a {subject}, but goals[{first_index}] "
                f"({first_goal.goal_type}) acts on a {first_goal_subject}. An agent is launched on either a "
                f"dataset or a session, so all of its goals must act on the same kind of entity: remove "
                f"goals[{index}] or move it to another agent."
            )
        _check_subject_id_binding(index, goal, subject, subject_id, variable_types)


def _check_subject_id_binding(
    index: int,
    goal: AgentGoal,
    subject: AgentSubject,
    subject_id: str,
    variable_types: dict[str, TemplateVariableType],
) -> None:
    if PLACEHOLDER_RE.search(subject_id) is None:
        return

    field = _SUBJECT_ID_FIELDS[subject]
    expected_type = _SUBJECT_VARIABLE_TYPES[subject]
    placeholder = PLACEHOLDER_RE.fullmatch(subject_id)
    if placeholder is None:
        raise RobotoInvalidRequestException(
            f"goals[{index}] ({goal.goal_type}) sets {field} to {subject_id!r}, which embeds a placeholder in "
            f"other text. Set {field} to exactly one placeholder of a variable of type {expected_type.value!r}, "
            f"such as '{{{{{subject}.id}}}}', or to a literal {subject} ID."
        )

    name = placeholder.group(1)
    variable_type = variable_types.get(name)
    if variable_type is not None and variable_type is not expected_type:
        raise RobotoInvalidRequestException(
            f"goals[{index}] ({goal.goal_type}) binds {field} to variable {name!r}, whose type is "
            f"{variable_type.value!r}. Change the type of {name!r} to {expected_type.value!r}, or bind {field} to a "
            f"variable of type {expected_type.value!r}."
        )


def goal_subject(goal: AgentGoal) -> tuple[AgentSubject, str]:
    """Return the kind of resource ``goal`` acts on and the ID of that resource, as the goal writes it.

    Roboto calls this when a thread receives goals, to record the dataset or session each goal acts on. The ID is the
    goal's ``dataset_id`` or ``session_id`` as written, so in an agent's request template it may be a ``{{name}}``
    placeholder.

    Args:
        goal: Goal of any type in :py:const:`~roboto.ai.goals.AgentGoal`.

    Returns:
        ``(subject, subject_id)``: the kind of resource the goal acts on and the goal's ``dataset_id`` or
        ``session_id``.
    """
    match goal:
        case DatasetSummaryAgentGoal() | DatasetTriageGoal() | CreateEventsGoal():
            return AgentSubject.DATASET, goal.dataset_id
        case SessionSummaryAgentGoal() | SessionTriageGoal() | SessionCreateEventsGoal():
            return AgentSubject.SESSION, goal.session_id
        case _:
            # mypy fails here when a goal type joins the AgentGoal union without a case above.
            typing.assert_never(goal)


__all__ = [
    "goal_subject",
    "infer_agent_subject",
    "validate_agent_subject",
]
