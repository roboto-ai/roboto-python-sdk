# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from ...compat import StrEnum


class AgentTaskStatus(StrEnum):
    """Lifecycle state of a top-level agent task."""

    PENDING = "pending"
    """Not started yet."""

    IN_PROGRESS = "in_progress"
    """The single active task. At most one task per thread is in this state."""

    COMPLETED = "completed"
    """Finished; carries a :attr:`AgentTask.conclusion`."""


class AgentSubtaskStatus(StrEnum):
    """Lifecycle state of a sub-task.

    Sub-tasks are never activated independently — they are implicitly active
    with their parent task — so they have no ``in_progress`` state.
    """

    PENDING = "pending"
    """Not done yet."""

    DONE = "done"
    """Completed."""


class AgentTaskBoundary(pydantic.BaseModel):
    """Position in the conversation where a top-level task's active span begins or ends.

    Identifies the assistant message and the content block within it whose
    tool call drove the transition, so callers can anchor a task to the part of
    the thread that worked on it.
    """

    message_sequence_num: int
    """Index of the assistant message whose tool call stamped this boundary."""

    content_sequence_num: int
    """Index of the tool-call content block within that message."""


class AgentSubtask(pydantic.BaseModel):
    """A lightweight checklist item under a top-level task."""

    title: str
    """Human-readable description of the sub-task."""

    status: AgentSubtaskStatus
    """Whether the sub-task is done."""


class AgentTask(pydantic.BaseModel):
    """A top-level task the agent is tracking within a thread."""

    task_id: int
    """Thread-monotonic id, stable for the life of the thread. The model
    references this id to start or complete the task."""

    position: int
    """Display order among the thread's top-level tasks."""

    title: str
    """Short title of the task."""

    status: AgentTaskStatus
    """Current lifecycle state."""

    description: Optional[str] = None
    """Longer description delimiting the task's scope and intent."""

    conclusion: Optional[str] = None
    """Outcome recorded when the task was completed. ``None`` until then."""

    start: Optional[AgentTaskBoundary] = None
    """Where the task most recently became ``in_progress``. ``None`` if never started."""

    end: Optional[AgentTaskBoundary] = None
    """Where the task was completed. ``None`` until then."""

    subtasks: list[AgentSubtask] = pydantic.Field(default_factory=list)
    """Ordered sub-tasks. A task cannot be completed until all of these are done."""


class AgentTaskMinimal(pydantic.BaseModel):
    """Minimal acknowledgement returned by the task mutation tools.

    The full list reaches the model through the per-turn injected context, so
    the mutation tools echo only the affected task's id and resulting status.
    """

    task_id: int
    """Id of the affected task."""

    status: AgentTaskStatus
    """Resulting status of the affected task."""


__all__ = [
    "AgentSubtask",
    "AgentSubtaskStatus",
    "AgentTask",
    "AgentTaskBoundary",
    "AgentTaskMinimal",
    "AgentTaskStatus",
]
