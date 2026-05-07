# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional

import pydantic

from ...compat import StrEnum
from ..core import (
    AnalysisScope,
    ClientViewingContext,
)
from ..core.record import (
    AgentContent,
    AgentContentType,
    AgentErrorContent,
    AgentGoalStatus,
    AgentMessage,
    AgentMessageStatus,
    AgentRole,
    AgentSessionDelta,
    AgentSessionGoalRecord,
    AgentSessionRecord,
    AgentSessionStatus,
    AgentTextContent,
    AgentToolResultContent,
    AgentToolUseContent,
    ClientToolSpec,
)
from ..goals import AgentGoal

MAX_GOALS_PER_TURN = 5
"""Hard ceiling on the number of goals a single turn may declare.

Every declared goal expands into a prompt block injected via the in-memory
``<goals>`` section *and* an active achieve-tool registered with Bedrock for
the turn. A runaway list crowds out the model's context budget and inflates
the per-invocation tool count without making the goals easier for the LLM
to reason about. Five is a deliberate, conservative cap for v1: in practice
specialized agents declare one or two goals at a time. Lift the ceiling
intentionally (with new tests covering large-fan-out behavior) rather than
quietly raising it on demand."""


class AgentToolDetailResponse(pydantic.BaseModel):
    """Unsanitized tool request and response details for an agent tool invocation."""

    tool_use: AgentToolUseContent
    tool_result: AgentToolResultContent


class SendMessageRequest(pydantic.BaseModel):
    """Request payload for sending a message to an agent session.

    Contains the message content and optional context for the AI assistant.
    """

    client_context: Optional[ClientViewingContext] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("client_context", "context"),
    )
    """Optional :class:`ClientViewingContext` describing what the client was
    viewing when this message was composed. Wire field is ``client_context``;
    the legacy ``context`` alias is accepted during the migration window and
    will be dropped in a future release."""

    message: Optional[AgentMessage] = None
    """Message content to send. May be omitted when at least one goal is declared
    in :attr:`goals`; in that case the server synthesizes a minimal user message
    so the LLM has a turn-initiating prompt."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Optional client-side tools available for this invocation."""

    analysis_scope: Optional[AnalysisScope] = None
    """Optional replacement analysis scope. When provided, overwrites the session's current analysis scope; the new
    scope takes effect for this turn's tool invocations and every turn thereafter. When ``None``, the session's
    existing analysis scope is left untouched (there is currently no wire-format way to clear a scope via ``send``)."""

    goals: Optional[list[AgentGoal]] = pydantic.Field(default=None, max_length=MAX_GOALS_PER_TURN)
    """Goals declared for this turn. The agent runner enforces achievement: it gates a per-turn achieve-tool against
    each goal and re-prompts until every goal is satisfied or a per-turn retry budget is exhausted. May be omitted;
    when present, :attr:`message` becomes optional. Capped at :data:`MAX_GOALS_PER_TURN` entries (see the constant
    for rationale)."""

    @pydantic.model_validator(mode="after")
    def _at_least_message_or_goals(self) -> "SendMessageRequest":
        if self.message is None and not self.goals:
            raise ValueError("SendMessageRequest requires either 'message' or at least one entry in 'goals'.")
        return self

    @pydantic.model_validator(mode="after")
    def _message_with_goals_must_carry_text(self) -> "SendMessageRequest":
        # When goals are declared alongside a real message, that message becomes
        # the worker's wake-up trigger and must carry text content for
        # write_message to persist. A message containing only tool_use or
        # tool_result blocks would be silently dropped, orphaning the goals.
        # Reject at the validation layer so the route returns 4xx instead of 5xx.
        if self.goals and self.message is not None:
            has_text = any(isinstance(c, AgentTextContent) for c in self.message.content)
            if not has_text:
                raise ValueError(
                    "When 'goals' are declared, the optional 'message' must contain at least one text block. "
                    "Tool-use or tool-result-only messages cannot drive a goal-bearing turn; omit 'message' "
                    "to let the server synthesize a minimal user message instead."
                )
        return self


class StartAgentSessionRequest(pydantic.BaseModel):
    """Request payload for starting a new agent session.

    Contains the initial messages and configuration for creating a new
    conversation.
    """

    client_context: Optional[ClientViewingContext] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("client_context", "context"),
    )
    """Optional :class:`ClientViewingContext` describing what the client was
    viewing when this session was started. Wire field is ``client_context``;
    the legacy ``context`` alias is accepted during the migration window and
    will be dropped in a future release."""

    messages: list[AgentMessage] = pydantic.Field(default_factory=list)
    """Initial messages to start the conversation with. May be empty when at least one goal is declared in
    :attr:`goals`; in that case the server synthesizes a minimal user message so the LLM has a turn-initiating
    prompt."""

    system_prompt: Optional[str] = None
    """Optional system prompt to customize AI assistant behavior."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Optional client-side tools available for this invocation."""

    model_profile: Optional[str] = None
    """Optional model profile ID for the session (e.g. 'standard', 'advanced')."""

    analysis_scope: Optional[AnalysisScope] = None
    """Optional analysis scope for the session. Delivered to every tool invocation on the server side; individual
    tools opt in to honoring it. ``None`` means no scope."""

    goals: Optional[list[AgentGoal]] = pydantic.Field(default=None, max_length=MAX_GOALS_PER_TURN)
    """Goals declared for the first turn. The agent runner enforces achievement: it gates a per-turn achieve-tool
    against each goal and re-prompts until every goal is satisfied or a per-turn retry budget is exhausted. May be
    omitted; when present, :attr:`messages` may be empty. Capped at :data:`MAX_GOALS_PER_TURN` entries (see the
    constant for rationale)."""

    @pydantic.model_validator(mode="after")
    def _at_least_messages_or_goals(self) -> "StartAgentSessionRequest":
        if not self.messages and not self.goals:
            raise ValueError(
                "StartAgentSessionRequest requires either at least one entry in 'messages' or at least one entry "
                "in 'goals'."
            )
        return self

    @pydantic.model_validator(mode="after")
    def _at_least_one_seeded_message_must_carry_text_when_goals_present(self) -> "StartAgentSessionRequest":
        # When goals are declared alongside seeded history, at least one
        # message in the history must carry text content. The runner needs a
        # text-bearing message to drive the turn against; a tool-use- or
        # tool-result-only seeded list has nothing for write_message to
        # persist as the wake-up trigger, leaving goals orphaned. Mirrors
        # SendMessageRequest._message_with_goals_must_carry_text.
        if self.goals and self.messages:
            has_text = any(isinstance(c, AgentTextContent) for m in self.messages for c in m.content)
            if not has_text:
                raise ValueError(
                    "When 'goals' are declared with seeded 'messages', at least one message must contain "
                    "a text block. Tool-use or tool-result-only seeded history cannot drive a goal-bearing "
                    "turn; omit 'messages' to let the server synthesize a minimal user message instead."
                )
        return self


class ClientToolResultStatus(StrEnum):
    """Outcome of executing a client-side tool."""

    SUCCESS = "success"
    ERROR = "error"
    DECLINED = "declined"


class ClientToolResult(pydantic.BaseModel):
    """Result of executing a client-side tool."""

    tool_use_id: str
    """Identifier of the tool invocation this result corresponds to."""

    tool_name: str
    """Name of the tool that was executed."""

    runtime_ms: int
    """Wall-clock execution time of the tool in milliseconds."""

    status: ClientToolResultStatus
    """Outcome of the tool execution."""

    output: Optional[dict[str, Any]] = None
    """Structured output returned by the tool."""


class SubmitToolResultsRequest(pydantic.BaseModel):
    """Request payload for submitting client-side tool execution results."""

    tool_results: list[ClientToolResult]
    """Tool results from client-side execution."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Optional updated client-side tools for the next invocation."""


class ForkChatRequest(pydantic.BaseModel):
    """Request payload for forking a chat at a specific message."""

    message_sequence_num: int
    """Highest message sequence number (inclusive) to copy into the new chat."""


__all__ = [
    "AgentContent",
    "AgentContentType",
    "AgentErrorContent",
    "AgentGoalStatus",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentSessionDelta",
    "AgentSessionGoalRecord",
    "AgentSessionRecord",
    "AgentSessionStatus",
    "AgentTextContent",
    "AgentToolDetailResponse",
    "AgentToolResultContent",
    "AgentToolUseContent",
    "ClientToolResult",
    "ClientToolResultStatus",
    "ClientToolSpec",
    "ForkChatRequest",
    "SendMessageRequest",
    "StartAgentSessionRequest",
    "SubmitToolResultsRequest",
]
