# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from ...compat import StrEnum


class AgentTaskStatus(StrEnum):
    """Status of a task in a thread's task list: whether Roboto's AI has started or completed it."""

    PENDING = "pending"
    """The AI has not started the task."""

    IN_PROGRESS = "in_progress"
    """The AI is working on the task. At most one task in a thread has this status."""

    COMPLETED = "completed"
    """The AI has completed the task and recorded its ``AgentTask.conclusion``."""


class AgentSubtaskStatus(StrEnum):
    """Status of a sub-task: whether Roboto's AI has done it.

    A sub-task has no status for work in progress: the AI works on a task's sub-tasks while the task itself is
    ``AgentTaskStatus.IN_PROGRESS``.
    """

    PENDING = "pending"
    """The AI has not done the sub-task."""

    DONE = "done"
    """The AI has done the sub-task."""


class AgentTaskBoundary(pydantic.BaseModel):
    """Position in a thread of the tool use with which Roboto's AI started or completed a task.

    Carried in ``AgentTask.start`` and ``AgentTask.end``. The messages between a task's start and its end are the
    part of the thread in which the AI worked on the task.
    """

    message_sequence_num: int
    """Index, in the thread's ``messages``, of the assistant message that holds the tool use."""

    content_sequence_num: int
    """Index, in that message's ``content``, of the :py:class:`~roboto.ai.agent_thread.AgentToolUseContent` block."""


class AgentSubtask(pydantic.BaseModel):
    """Sub-task of a task: one step of its work, tracked as a checklist item.

    Carried in ``AgentTask.subtasks``.
    """

    title: str
    """Human-readable title of the sub-task."""

    status: AgentSubtaskStatus
    """Status of the sub-task: whether the AI has done it."""


class AgentTask(pydantic.BaseModel):
    """Task in a thread's task list: a unit of work Roboto's AI plans, such as a question to answer or a deliverable.

    The AI adds tasks as it plans multi-step work, works on one at a time, and records a conclusion as it completes
    each. Carried in :py:attr:`~roboto.ai.agent_thread.AgentThreadRecord.tasks` and
    :py:attr:`~roboto.ai.agent_thread.AgentThreadDelta.tasks`, and returned by
    :py:attr:`~roboto.ai.agent_thread.AgentThread.tasks`.
    """

    task_id: int
    """ID of the task, unique within its thread and never reused.

    Roboto numbers a thread's tasks from 0 in the order the AI adds them, and a fork keeps them.
    """

    position: int
    """Position of the task in the thread's task list, from 0 in the order the AI added the tasks."""

    title: str
    """Short title of the task."""

    status: AgentTaskStatus
    """Status of the task: whether the AI has started or completed it."""

    description: Optional[str] = None
    """Human-readable description of the task's scope and intent, or ``None`` if it has none."""

    conclusion: Optional[str] = None
    """Outcome the AI recorded when it completed the task, or ``None`` until the task is completed."""

    start: Optional[AgentTaskBoundary] = None
    """Position of the tool use with which the AI started the task.

    ``None`` while the task is pending, or when Roboto could not locate that tool use in the thread.
    """

    end: Optional[AgentTaskBoundary] = None
    """Position of the tool use with which the AI completed the task.

    ``None`` until the task is completed, or when Roboto could not locate that tool use in the thread.
    """

    subtasks: list[AgentSubtask] = pydantic.Field(default_factory=list)
    """Sub-tasks of the task, in the order the AI added them. Completing the task marks every sub-task done."""


class AgentTaskMinimal(pydantic.BaseModel):
    """ID and resulting status of a task that one of Roboto's AI task tools changed.

    The ``add_tasks``, ``add_subtasks``, and ``change_task`` tools return it, as a JSON-compatible dictionary, in
    their :py:class:`~roboto.ai.agent_thread.AgentToolResultContent`. The AI receives the full task list separately
    on each turn, so the tool results carry only these two fields.
    """

    task_id: int
    """ID of the task the tool changed."""

    status: AgentTaskStatus
    """Status of the task after the change."""


__all__ = [
    "AgentSubtask",
    "AgentSubtaskStatus",
    "AgentTask",
    "AgentTaskBoundary",
    "AgentTaskMinimal",
    "AgentTaskStatus",
]
