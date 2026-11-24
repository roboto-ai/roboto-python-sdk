# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Any

import pydantic

from ..goals.results import GoalResult
from ..goals.types import AgentGoal
from .record import (
    AgentGoalStatus,
    AgentMessage,
    AgentThreadGoalRecord,
    AgentToolResultContent,
    AgentToolUseContent,
)

# Built once per process: building a TypeAdapter compiles the schema of the whole GoalResult union, which would
# dominate the cost of every result read. It holds nothing but that schema, so all views share it.
_GOAL_RESULT_ADAPTER: pydantic.TypeAdapter[GoalResult] = pydantic.TypeAdapter(GoalResult)


class AgentThreadGoalView:
    """Goal declared on a turn of a thread, with the result the AI submitted for it found in the thread's messages.

    :py:attr:`~roboto.ai.agent_thread.AgentThread.goals` returns these; you do not build one directly. A view reads its
    fields from a :py:class:`~roboto.ai.agent_thread.AgentThreadGoalRecord`, and finds the goal's tool use and tool
    result among the messages of the thread that returned it by the record's ``achieve_tool_use_id``. The first read of
    ``achieve_tool_use``, ``achieve_tool_result`` or ``result`` searches the messages once for all three.
    """

    def __init__(self, record: AgentThreadGoalRecord, messages: list[AgentMessage]) -> None:
        self._record = record
        self._messages = messages
        # The (tool_use, tool_result) pair found in the messages, keyed on id(self._messages). None means the
        # messages have not been searched yet; a cached pair, even (None, None), is returned without searching
        # again. Nothing reassigns self._messages, and AgentThread.refresh changes that list in place, so the
        # key never changes: a view keeps the pair it found first, even after the messages gain the tool use or result.
        self._resolved_pair_cache: (
            tuple[int, tuple[AgentToolUseContent | None, AgentToolResultContent | None]] | None
        ) = None

    @property
    def record(self) -> AgentThreadGoalRecord:
        """Record of the goal that this instance holds."""
        return self._record

    @property
    def goal_type(self) -> str:
        """Kind of goal, such as ``"dataset_summary"``, which selects the model ``goal_data`` follows."""
        return self._record.goal_type

    @property
    def goal_data(self) -> dict[str, Any]:
        """:py:const:`~roboto.ai.goals.AgentGoal` as a JSON-compatible dictionary.

        ``to_agent_goal`` builds the typed goal from it.
        """
        return self._record.goal_data

    @property
    def status(self) -> AgentGoalStatus:
        """Status of the goal."""
        return self._record.status

    @property
    def message_sequence_num(self) -> int:
        """Index, in the thread's ``messages``, of the user message that declared the goal."""
        return self._record.message_sequence_num

    @property
    def created(self) -> datetime.datetime:
        """Time the goal was declared."""
        return self._record.created

    @property
    def concluded_at(self) -> datetime.datetime | None:
        """Time the goal was achieved or failed, or ``None`` while it is pending."""
        return self._record.concluded_at

    @property
    def achieve_tool_use_id(self) -> str | None:
        """ID of the tool use in which the AI submitted the goal's result.

        :py:attr:`~roboto.ai.agent_thread.AgentThreadGoalRecord.achieve_tool_use_id` says which attempt it names for
        each status, and when it is ``None``.
        """
        return self._record.achieve_tool_use_id

    def to_agent_goal(self) -> AgentGoal:
        """Build the typed goal from ``goal_data``.

        Returns:
            The goal as the :py:const:`~roboto.ai.goals.AgentGoal` member ``goal_type`` selects, such as
            :py:class:`~roboto.ai.goals.DatasetSummaryAgentGoal` for ``"dataset_summary"``.
        """
        return self._record.to_agent_goal()

    def _resolve_pair(
        self,
    ) -> tuple[AgentToolUseContent | None, AgentToolResultContent | None]:
        """Locate the (tool_use, tool_result) pair for this goal in one pass.

        Shared by ``achieve_tool_use``, ``achieve_tool_result``, and ``result`` so the three accessors together make one
        pass over the messages list, not three. It caches the pair keyed on the identity of the messages list. Nothing
        replaces that list, and ``AgentThread.refresh`` changes it in place, so later calls return the first pair found
        for the life of this view.
        """
        target_id = self._record.achieve_tool_use_id
        if target_id is None:
            return None, None

        messages_id = id(self._messages)
        cached = self._resolved_pair_cache
        if cached is not None and cached[0] == messages_id:
            return cached[1]

        use: AgentToolUseContent | None = None
        result: AgentToolResultContent | None = None
        for message in self._messages:
            for block in message.content:
                if use is None and isinstance(block, AgentToolUseContent) and block.tool_use_id == target_id:
                    use = block
                elif result is None and isinstance(block, AgentToolResultContent) and block.tool_use_id == target_id:
                    result = block
                if use is not None and result is not None:
                    break
            if use is not None and result is not None:
                break

        pair: tuple[AgentToolUseContent | None, AgentToolResultContent | None] = (use, result)
        self._resolved_pair_cache = (messages_id, pair)
        return pair

    @property
    def achieve_tool_use(self) -> AgentToolUseContent | None:
        """Tool use in which the AI submitted the goal's result, found in the thread's messages.

        ``None`` when ``achieve_tool_use_id`` is ``None``, or when the thread's messages do not include the tool use,
        as when the thread was fetched before Roboto recorded it.
        """
        use, _ = self._resolve_pair()
        return use

    @property
    def achieve_tool_result(self) -> AgentToolResultContent | None:
        """Tool result that answers ``achieve_tool_use``, found in the thread's messages.

        ``None`` when ``achieve_tool_use_id`` is ``None``, or when the thread's messages hold no result for it. A
        failed goal whose last attempt errored before Roboto recorded its result has a tool use and no tool result.
        """
        _, result = self._resolve_pair()
        return result

    @property
    def result(self) -> GoalResult | None:
        """Result the AI submitted for the goal, built from ``achieve_tool_use``.

        It is the :py:const:`~roboto.ai.goals.GoalResult` member ``goal_type`` selects, such as a
        :py:class:`~roboto.ai.goals.DatasetSummaryGoalResult` for a ``"dataset_summary"`` goal. It holds the
        fields the AI submitted in ``achieve_tool_use``, that tool use, ``achieve_tool_result``, and the goal's
        ``status``. A pending goal can already have a result from the AI's latest attempt, with
        :py:attr:`~roboto.ai.goals.AgentGoalStatus.PENDING` as its status, so check ``status`` before relying on it.

        ``None`` when ``achieve_tool_use`` is ``None``, or when the submitted fields fail validation against the
        result model, as fields submitted under an earlier version of the goal's schema can. ``achieve_tool_use``
        still holds those fields.
        """
        tool_use, tool_result = self._resolve_pair()
        if tool_use is None:
            return None
        # A result model holds the tool use's input fields at its top level, beside the fields set below. goal_type
        # selects which model of the GoalResult union validates the payload.
        payload: dict[str, Any] = dict(tool_use.input or {})
        payload.update(
            {
                "goal_type": self._record.goal_type,
                "status": self._record.status,
                "achieve_tool_use": tool_use,
                "achieve_tool_result": tool_result,
            }
        )
        try:
            return _GOAL_RESULT_ADAPTER.validate_python(payload)
        except pydantic.ValidationError:
            return None
