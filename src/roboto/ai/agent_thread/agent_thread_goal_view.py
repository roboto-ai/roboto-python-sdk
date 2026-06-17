# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SDK wrapper that resolves an :class:`AgentThreadGoalRecord` against the
parent thread's message stream.

``AgentThreadGoalView`` is the read shape ``AgentThread.goals`` returns. It
delegates field reads to the underlying record and adds three resolved
properties:

- :attr:`achieve_tool_use` — the raw :class:`AgentToolUseContent` for the
  achieve-tool invocation associated with the goal.
- :attr:`achieve_tool_result` — the matching
  :class:`AgentToolResultContent`, when one was persisted.
- :attr:`result` — the typed, per-goal-type :data:`GoalResult` parsed
  from the tool_use input.

All three resolve lazily by scanning the parent thread's ``messages``
list for the ``achieve_tool_use_id`` stored on the record. A single
internal pass locates the tool_use / tool_result pair and is shared by
all three accessors, so reading ``goal.achieve_tool_use``,
``goal.achieve_tool_result``, and ``goal.result`` in sequence does the
same work as reading any one of them. The pair is cached on the wrapper
after the first lookup, keyed on the messages-list identity, so
repeated reads on the same snapshot are constant-time after the first.
"""

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

# Module-scoped: ``TypeAdapter`` compiles a non-trivial schema for the
# discriminated union; constructing it per ``.result`` access would
# dominate the cost of the accessor. The adapter is stateless beyond the
# compiled schema, so a process-wide single instance is safe.
_GOAL_RESULT_ADAPTER: pydantic.TypeAdapter[GoalResult] = pydantic.TypeAdapter(GoalResult)


class AgentThreadGoalView:
    """SDK-side wrapper around an :class:`AgentThreadGoalRecord`.

    Holds a back-reference to a messages list (the parent thread's full
    message history) so the achieve-tool invocation can be located via
    ``achieve_tool_use_id`` without forcing the caller to do the lookup
    by hand.

    The wrapper is value-like: instantiating it does not copy the
    underlying record. Callers should not mutate it; mutations on the
    parent thread (via ``run`` / ``refresh``) are visible through the
    wrapper's resolved properties because the messages list is shared.
    """

    def __init__(self, record: AgentThreadGoalRecord, messages: list[AgentMessage]) -> None:
        self._record = record
        self._messages = messages
        # Cache for the (tool_use, tool_result) pair. ``None`` means "not yet
        # resolved"; a populated tuple — even of (None, None) — means we
        # already scanned the messages list and there is nothing to find.
        # Keyed on ``id(self._messages)`` so a caller who re-points the
        # wrapper's messages list (e.g. by mutating ``AgentThread.__record``
        # via ``refresh``) invalidates the cache transparently.
        self._resolved_pair_cache: (
            tuple[int, tuple[AgentToolUseContent | None, AgentToolResultContent | None]] | None
        ) = None

    # ----- delegating wire fields -----

    @property
    def record(self) -> AgentThreadGoalRecord:
        """The underlying wire record. Useful for callers that want the
        unwrapped pydantic shape (e.g. for JSON serialization)."""
        return self._record

    @property
    def goal_type(self) -> str:
        """Discriminator selecting which :data:`AgentGoal` model the goal
        was declared as. Equivalent to ``self.record.goal_type``."""
        return self._record.goal_type

    @property
    def goal_data(self) -> dict[str, Any]:
        """The original goal-declaration payload. Use :meth:`to_agent_goal`
        to re-hydrate into the typed :data:`AgentGoal` model."""
        return self._record.goal_data

    @property
    def status(self) -> AgentGoalStatus:
        """Current lifecycle state of the goal."""
        return self._record.status

    @property
    def message_sequence_num(self) -> int:
        """Index of the user-role message that declared this goal."""
        return self._record.message_sequence_num

    @property
    def created(self) -> datetime.datetime:
        """Timestamp when the goal was registered."""
        return self._record.created

    @property
    def concluded_at(self) -> datetime.datetime | None:
        """Timestamp when the goal reached a terminal state, or ``None``
        while still PENDING."""
        return self._record.concluded_at

    @property
    def achieve_tool_use_id(self) -> str | None:
        """``tool_use_id`` of the achieve-tool invocation associated with
        this goal — see :class:`AgentThreadGoalRecord.achieve_tool_use_id`
        for the per-status semantics."""
        return self._record.achieve_tool_use_id

    def to_agent_goal(self) -> AgentGoal:
        """Re-hydrate the goal declaration into its typed :data:`AgentGoal`
        model. Delegates to :meth:`AgentThreadGoalRecord.to_agent_goal`."""
        return self._record.to_agent_goal()

    # ----- resolved properties -----

    def _resolve_pair(
        self,
    ) -> tuple[AgentToolUseContent | None, AgentToolResultContent | None]:
        """Locate the (tool_use, tool_result) pair for this goal in one pass.

        Shared by :attr:`achieve_tool_use`, :attr:`achieve_tool_result`, and
        :attr:`result` so the three accessors collectively do one pass over
        the messages list, not three. Caches the result keyed on the
        messages-list identity: a snapshot replacement (a ``refresh`` that
        installs a fresh list on the parent thread) invalidates
        transparently, while repeated reads against the same list are
        constant-time.
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
        """The achieve-tool invocation the LLM submitted for this goal.

        Returns ``None`` when ``achieve_tool_use_id`` is ``None`` (no
        attempt has been recorded) or when no matching block is present
        in the thread's messages — the latter can happen if the caller
        is holding a thread snapshot that pre-dates the achieve-tool
        being persisted. In that case, a refresh of the thread should
        bring the block into view.
        """
        use, _ = self._resolve_pair()
        return use

    @property
    def achieve_tool_result(self) -> AgentToolResultContent | None:
        """The matching tool-result block for :attr:`achieve_tool_use`, if
        the runner persisted one before the turn terminated.

        For a FAILED goal whose last attempt errored mid-flight (or whose
        tool_result chunk never landed), this returns ``None`` even when
        :attr:`achieve_tool_use` is non-null.
        """
        _, result = self._resolve_pair()
        return result

    @property
    def result(self) -> GoalResult | None:
        """Typed, per-goal-type result for the achieve-tool invocation.

        Returns ``None`` when no terminal achieve-tool invocation is
        available (PENDING goal, or FAILED with no attempted invocation),
        when the matching ``tool_use`` cannot be located in the thread's
        messages, or when the persisted input is malformed enough to fail
        validation against the achieve-input model. In all three cases
        callers can still inspect :attr:`achieve_tool_use` /
        :attr:`achieve_tool_result` directly for debugging.

        The returned object is one of the concrete subclasses of
        :data:`GoalResult` (e.g. :class:`DatasetSummaryGoalResult`), so
        callers can ``isinstance``-dispatch or simply read the typed
        fields. The status field reflects the goal's terminal status, so
        the same accessor works for both ACHIEVED and FAILED outcomes.
        """
        tool_use, tool_result = self._resolve_pair()
        if tool_use is None:
            return None
        # The achieve-input payload lives at the top level of the tool_use
        # input dict; flatten it alongside the result-specific fields so
        # pydantic's discriminated-union validator sees a single object.
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
            # Persisted input no longer parses (e.g. a schema change shipped
            # after this thread was written). Surface ``None`` so callers
            # fall back to the raw-block accessors rather than crashing on
            # historical data.
            return None
