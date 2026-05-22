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
    AgentTextContent,
    AgentThreadDelta,
    AgentThreadGoalRecord,
    AgentThreadRecord,
    AgentThreadStatus,
    AgentToolResultContent,
    AgentToolUseContent,
    ClientToolSpec,
    ThreadVisibility,
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

MAX_AVAILABLE_SKILLS = 100
"""Hard ceiling on the size of a thread's explicit ``available_skills`` set.

Every entry becomes a line in the ``load_skill`` tool's registry description and
a value in its ``name`` enum. An unbounded set bloats the tool schema and the
per-turn prompt without making skill selection easier for the model. 100 is a
generous cap for v1 — well above any realistic curated set — and can be lifted
intentionally (with tests covering large registries) rather than removed on
demand."""


class AgentToolDetailResponse(pydantic.BaseModel):
    """Unsanitized tool request and response details for an agent tool invocation."""

    tool_use: AgentToolUseContent
    tool_result: AgentToolResultContent


class InvokeSkillSpec(pydantic.BaseModel):
    """Spec for invoking a skill as part of a turn trigger.

    Embedded in :class:`SendMessageRequest` and :class:`StartAgentThreadRequest`.
    The route layer resolves access (org visibility, private gating) and version
    selection; this struct only carries the caller's choice.

    Defined locally to avoid the ``roboto.ai`` ↔ ``roboto.domain.skills``
    import cycle.
    """

    skill_id: str
    """Target skill's ID. Must be visible to the caller (own private skill or
    an org-shared skill); the route layer rejects unauthorized invocations
    before the spec reaches the service."""

    version: Optional[int] = None
    """Optional. If omitted, resolves to the skill's latest (MAX(version)) row.

    Note this is the structural latest, not the caller's pinned ``ai_version``:
    a manually-invoked chip runs MAX(version) regardless of what the caller's
    AI auto-invoke is pinned to. Use ``Skill.set_ai_version()`` to control the
    pin separately.
    """


class AvailableSkillSpec(pydantic.BaseModel):
    """One entry in a thread's explicit AI-invokable skill set.

    Embedded in :attr:`StartAgentThreadRequest.available_skills`. Unlike
    :class:`InvokeSkillSpec` — which seeds a skill into the opening transcript
    as a turn trigger — this struct only declares that a skill *version* is
    available for the AI to auto-invoke via its ``load_skill`` tool during the
    thread. The route layer resolves access (org visibility, private gating)
    and version selection; this struct only carries the caller's choice.

    Defined locally to avoid the ``roboto.ai`` <-> ``roboto.domain.skills``
    import cycle.
    """

    skill_id: str
    """Target skill's ID. Must be visible to the caller — an org-shared skill,
    or the caller's own private skill. A subscription is *not* required; the
    per-thread set bypasses subscription state entirely."""

    version: Optional[int] = None
    """Optional. If omitted, resolves to the skill's latest (MAX(version)) row.

    Pins the exact version exposed to the AI for this thread. Subscriptions and
    their per-user ``ai_version`` pins are ignored when a thread carries an
    explicit ``available_skills`` set."""


class SendMessageRequest(pydantic.BaseModel):
    """Request payload for sending a message to an agent thread.

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
    """Optional replacement analysis scope. When provided, overwrites the thread's current analysis scope; the new
    scope takes effect for this turn's tool invocations and every turn thereafter. When ``None``, the thread's
    existing analysis scope is left untouched (there is currently no wire-format way to clear a scope via ``send``)."""

    goals: Optional[list[AgentGoal]] = pydantic.Field(default=None, max_length=MAX_GOALS_PER_TURN)
    """Goals declared for this turn. The agent runner enforces achievement: it gates a per-turn achieve-tool against
    each goal and re-prompts until every goal is satisfied or a per-turn retry budget is exhausted. May be omitted;
    when present, :attr:`message` becomes optional. Capped at :data:`MAX_GOALS_PER_TURN` entries (see the constant
    for rationale)."""

    invoke_skills: list["InvokeSkillSpec"] = pydantic.Field(default_factory=list)
    """Skills to invoke as part of this turn, in order. The server fabricates one
    ``LoadSkillTool`` ``tool_use`` + ``tool_result`` pair per entry and appends them to the
    transcript after :attr:`message` (if any). When :attr:`message` is empty and no goals
    are declared, the fabricated pairs become the turn trigger themselves — useful for
    chip-only invocations that don't carry a typed prompt. Pass a single-element
    list for the common "invoke one skill" case."""

    @pydantic.model_validator(mode="after")
    def _at_least_one_trigger(self) -> "SendMessageRequest":
        if self.message is None and not self.goals and not self.invoke_skills:
            raise ValueError("SendMessageRequest requires at least one of 'message', 'goals', or 'invoke_skills'.")
        return self

    @pydantic.model_validator(mode="after")
    def _message_must_be_user_text_only(self) -> "SendMessageRequest":
        # /send carries user-originated turn triggers. Anything else has its own
        # endpoint: client tool results go to submit_client_tool_results, and
        # tool_use blocks are never user-originated. Without this guard,
        # write_message silently drops the offending content and the caller
        # sees a 200 with the wrong outcome.
        if self.message is None:
            return self
        if self.message.role != AgentRole.USER:
            raise ValueError("When 'message' is provided to send_message, its role must be USER.")
        if not self.message.content:
            raise ValueError("When 'message' is provided to send_message, it must contain at least one text block.")
        for content in self.message.content:
            if not isinstance(content, AgentTextContent):
                raise ValueError(
                    "When 'message' is provided to send_message, content may only contain text blocks. "
                    "Tool results from client-side tools must be submitted via the "
                    "submit_client_tool_results endpoint, not via send_message."
                )
        return self


class StartAgentThreadRequest(pydantic.BaseModel):
    """Request payload for starting a new agent thread.

    Contains the initial messages and configuration for creating a new
    conversation.
    """

    client_context: Optional[ClientViewingContext] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("client_context", "context"),
    )
    """Optional :class:`ClientViewingContext` describing what the client was
    viewing when this thread was started. Wire field is ``client_context``;
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
    """Optional model profile ID for the thread (e.g. 'standard', 'advanced')."""

    analysis_scope: Optional[AnalysisScope] = None
    """Optional analysis scope for the thread. Delivered to every tool invocation on the server side; individual
    tools opt in to honoring it. ``None`` means no scope."""

    goals: Optional[list[AgentGoal]] = pydantic.Field(default=None, max_length=MAX_GOALS_PER_TURN)
    """Goals declared for the first turn. The agent runner enforces achievement: it gates a per-turn achieve-tool
    against each goal and re-prompts until every goal is satisfied or a per-turn retry budget is exhausted. May be
    omitted; when present, :attr:`messages` may be empty. Capped at :data:`MAX_GOALS_PER_TURN` entries (see the
    constant for rationale)."""

    invoke_skills: list["InvokeSkillSpec"] = pydantic.Field(default_factory=list)
    """Skills to invoke at thread start, in order. The server fabricates one
    ``LoadSkillTool`` ``tool_use`` + ``tool_result`` pair per entry and appends them to the
    transcript after any seeded :attr:`messages`. When ``messages`` is empty and no goals
    are declared, the fabricated pairs become the thread seed. Pass a
    single-element list for the common "invoke one skill" case."""

    available_skills: Optional[list["AvailableSkillSpec"]] = pydantic.Field(
        default=None, max_length=MAX_AVAILABLE_SKILLS
    )
    """Explicit set of skills the AI may auto-invoke during this thread,
    replacing the subscription-derived ``load_skill`` registry.

    Tri-state:

    - ``None`` (the default) — the AI's ``load_skill`` registry is derived per
      turn from the caller's skill subscriptions, as usual.
    - ``[]`` — the AI has *no* auto-invokable skills for this thread.
    - a non-empty list — exactly these skill versions are auto-invokable; the
      caller's subscriptions and per-user ``ai_version`` pins are ignored.

    Each entry may reference any org-shared skill or the caller's own private
    skill (visibility only — no subscription required), at any version. One
    version per skill: duplicate ``skill_id`` entries are rejected. Resolved
    once at thread start and frozen onto the thread; later subscription
    changes and skill-body edits do not propagate into it. Capped at
    :data:`MAX_AVAILABLE_SKILLS` entries.

    Distinct from :attr:`invoke_skills`: ``available_skills`` configures *what
    the AI can reach for*, while ``invoke_skills`` *seeds* skill bodies into the
    opening transcript as a turn trigger. It is configuration, not a trigger — a
    request carrying only ``available_skills`` and no ``messages`` / ``goals`` /
    ``invoke_skills`` is still rejected."""

    visibility: ThreadVisibility = ThreadVisibility.PRIVATE
    """Who may read the resulting thread after it is created. ``PRIVATE``
    (the default) restricts reads to the creator and Roboto admins; ``ORG``
    lets any member of the thread's org read it and makes the thread
    visible to org members on ``POST /v1/ai/threads/search``. The default
    is ``PRIVATE`` so that a thread started via ``POST /v1/ai/threads``
    does not leak to the rest of the org until the caller opts in;
    threads created through the agent launch flow default to ``ORG``
    instead, since agents exist to share workflows across teammates."""

    @pydantic.model_validator(mode="after")
    def _at_least_one_trigger(self) -> "StartAgentThreadRequest":
        if not self.messages and not self.goals and not self.invoke_skills:
            raise ValueError(
                "StartAgentThreadRequest requires at least one of 'messages', 'goals', or 'invoke_skills'."
            )
        return self

    @pydantic.model_validator(mode="after")
    def _at_least_one_seeded_message_must_carry_text_when_goals_present(self) -> "StartAgentThreadRequest":
        # When goals are declared alongside seeded history (and no skill_invocation), at
        # least one message in the history must carry text content. The runner needs a
        # text-bearing message to drive the turn against; a tool-use- or tool-result-only
        # seeded list has nothing for write_message to persist as the wake-up trigger,
        # leaving goals orphaned. Mirrors SendMessageRequest._message_with_goals_must_carry_text.
        # When invoke_skills is non-empty, the fabricated pairs provide the trigger.
        if self.goals and self.messages and not self.invoke_skills:
            has_text = any(isinstance(c, AgentTextContent) for m in self.messages for c in m.content)
            if not has_text:
                raise ValueError(
                    "When 'goals' are declared with seeded 'messages' and no 'invoke_skills', at least one "
                    "message must contain a text block. Tool-use or tool-result-only seeded history cannot "
                    "drive a goal-bearing turn; omit 'messages' to let the server synthesize a minimal user "
                    "message instead, or supply 'invoke_skills' to seed the turn from skill bodies."
                )
        return self

    @pydantic.model_validator(mode="after")
    def _available_skills_have_unique_skill_ids(self) -> "StartAgentThreadRequest":
        # The per-thread AI registry holds at most one version per skill —
        # LoadSkillTool keys its enum by skill name, so two versions of the
        # same skill would collide. Reject duplicates here so the caller gets
        # a clear client-side error instead of a silently-deduplicated set.
        if self.available_skills:
            seen: set[str] = set()
            for spec in self.available_skills:
                if spec.skill_id in seen:
                    raise ValueError(
                        f"available_skills lists skill_id '{spec.skill_id}' more than once; the per-thread "
                        "AI registry holds one version per skill."
                    )
                seen.add(spec.skill_id)
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


class ForkAgentThreadRequest(pydantic.BaseModel):
    """Request payload for forking an agent thread at a specific message."""

    message_sequence_num: int
    """Highest message sequence number (inclusive) to copy into the new thread."""


class AgentThreadSubject(pydantic.BaseModel):
    """Canonical record of an entity an :class:`AgentThread` applies to.

    Used to answer "which agent threads are about this dataset / file?"
    — the dataset detail page's Agent Threads tab is one consumer; future
    surfaces that want to discover threads by entity will use the same
    record.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    association_id: str
    """Identifier of the entity the thread applies to — e.g. a dataset id
    or file id."""

    note: str
    """Short, free-form explanation of how the subject came to be
    attached (e.g. why this thread applies to that entity)."""


__all__ = [
    "AgentContent",
    "AgentContentType",
    "AgentErrorContent",
    "AgentGoalStatus",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentThreadDelta",
    "AgentThreadGoalRecord",
    "AgentThreadRecord",
    "AgentThreadStatus",
    "AgentThreadSubject",
    "AgentTextContent",
    "AgentToolDetailResponse",
    "AgentToolResultContent",
    "AgentToolUseContent",
    "AvailableSkillSpec",
    "ClientToolResult",
    "ClientToolResultStatus",
    "ClientToolSpec",
    "ForkAgentThreadRequest",
    "InvokeSkillSpec",
    "SendMessageRequest",
    "ThreadVisibility",
    "StartAgentThreadRequest",
    "SubmitToolResultsRequest",
]
