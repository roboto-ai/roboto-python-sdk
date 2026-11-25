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
from ..core.content import AgentArtifactRecord
from ..core.record import (
    AGENT_CONTENT_MODEL_BY_TYPE,
    AgentClientContextEntry,
    AgentCompressionFillerContent,
    AgentContent,
    AgentContentType,
    AgentDeletedContent,
    AgentErrorContent,
    AgentGoalStatus,
    AgentMessage,
    AgentMessageStatus,
    AgentRole,
    AgentSubtask,
    AgentSubtaskStatus,
    AgentTask,
    AgentTaskBoundary,
    AgentTaskMinimal,
    AgentTaskStatus,
    AgentTextContent,
    AgentThreadDelta,
    AgentThreadGoalRecord,
    AgentThreadRecord,
    AgentThreadStatus,
    AgentToolResultContent,
    AgentToolUseContent,
    ClientToolSpec,
    ThreadOrigin,
    ThreadVisibility,
)
from ..goals import AgentGoal

MAX_GOALS_PER_TURN = 5
"""Maximum number of goals one turn may declare.

Each goal adds instructions and a tool to the AI's turn, so a long list crowds the conversation out of what the AI can
take in at once.
"""

MAX_AVAILABLE_SKILLS = 100
"""Maximum number of skills a thread's ``available_skills`` may list."""


class AgentToolDetailResponse(pydantic.BaseModel):
    """Response body of ``GET /v1/ai/threads/{thread_id}/tool-use/{tool_use_id}``.

    Holds one tool use in a thread and its result. Unlike a read of the whole thread, it keeps the tool use's
    ``raw_request`` and the result's ``raw_response``.
    """

    tool_use: AgentToolUseContent
    """Request the AI made to run the tool."""

    tool_result: AgentToolResultContent
    """Result of the tool use."""


class AgentToolArtifactResponse(pydantic.BaseModel):
    """Response body of ``GET /v1/ai/threads/{thread_id}/tool-use/{tool_use_id}/artifacts/{name}``.

    Holds a download URL for one file a tool produced in a thread, which
    :py:class:`~roboto.ai.agent_thread.AgentArtifactRecord` describes without a URL. Roboto returns it only to a caller
    who can read the thread. The URL expires after 5 minutes, so request it when you need the file rather than storing
    it.
    """

    name: str
    """Name of the file, as :py:attr:`~roboto.ai.agent_thread.AgentArtifactRecord.name` gives it."""

    url: str
    """URL to download the file from, valid for 5 minutes."""

    content_type: str
    """Media type the URL serves the file as.

    An image a browser displays keeps its own type (``image/png``, ``image/jpeg``, ``image/gif`` or ``image/webp``);
    any other file is served as ``application/octet-stream``, which a browser downloads.
    """

    bytes: int
    """Size of the file, in bytes."""


class InvokeSkillSpec(pydantic.BaseModel):
    """Skill the caller chooses to apply in a turn, rather than leaving the choice to the AI.

    Carried in ``SendMessageRequest.invoke_skills`` and ``StartAgentThreadRequest.invoke_skills``.
    """

    skill_id: str
    """ID of the skill to apply.

    The caller must be the skill's author or subscribed to it; otherwise Roboto rejects the request with
    ``RobotoUnauthorizedException``.
    """

    version: Optional[int] = None
    """Number of the skill version to apply.

    ``None`` applies the skill's latest version, even when the caller pinned another with
    :py:meth:`~roboto.domain.skills.Skill.set_ai_version`.
    """


class AvailableSkillSpec(pydantic.BaseModel):
    """Skill the AI may apply on its own during one thread, at a fixed version.

    Carried in ``StartAgentThreadRequest.available_skills``. Unlike ``InvokeSkillSpec``, it does not apply the skill;
    the AI decides whether to.
    """

    skill_id: str
    """ID of the skill.

    Any skill the caller can see is allowed, whether or not the caller subscribes to it. Roboto rejects a skill the
    caller cannot see with ``RobotoNotFoundException``.
    """

    version: Optional[int] = None
    """Number of the skill version the AI may apply in the thread.

    ``None`` uses the skill's latest version when the thread starts. The caller's pinned version, if any, does not
    apply.
    """


class SendMessageRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.send`.

    The request needs at least one of ``message``, ``goals`` and ``invoke_skills``. Building it raises
    ``pydantic.ValidationError`` when:

    - ``message``, ``goals`` and ``invoke_skills`` are all empty.
    - ``message`` is not a user message made only of text.
    - ``goals`` holds more than ``MAX_GOALS_PER_TURN`` goals.
    """

    client_context: Optional[ClientViewingContext] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("client_context", "context"),
    )
    """What the caller had open in their client when they wrote the message, such as datasets or files.

    Lets the AI resolve references like "this dataset". ``None`` sends none. Also accepted under the key
    ``context``.
    """

    message: Optional[AgentMessage] = None
    """User message that starts the turn, containing only text.

    ``None`` is allowed when ``goals`` or ``invoke_skills`` is set. With goals, Roboto writes a short user message
    that asks the AI to meet them; with only skills, the skills start the turn.
    """

    client_tools: Optional[list[ClientToolSpec]] = None
    """Client-side tools the AI may call from this turn on: tools your code runs when the AI calls them.

    A non-empty list replaces the thread's client-side tools; ``None`` or an empty list leaves them unchanged.
    """

    analysis_scope: Optional[AnalysisScope] = None
    """Analysis scope that replaces the thread's own, from this turn on.

    Roboto passes the scope to each tool the AI calls, and each tool decides whether to apply it. ``None`` leaves the
    thread's scope unchanged; no value of this field clears it.
    """

    goals: Optional[list[AgentGoal]] = pydantic.Field(default=None, max_length=MAX_GOALS_PER_TURN)
    """Goals the AI must meet in this turn, at most ``MAX_GOALS_PER_TURN``.

    Roboto prompts the AI again until it meets every goal or runs out of retries, which leaves the thread in
    :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.GOALS_FAILED`. ``None`` declares none.
    """

    invoke_skills: list["InvokeSkillSpec"] = pydantic.Field(default_factory=list)
    """Skills to apply in this turn, in order.

    Roboto adds each skill's procedure to the transcript after ``message``, as a call to the AI's skill-loading tool
    and its result. Defaults to none.
    """

    client_tab_id: Optional[str] = None
    """Opaque id of the browser tab sending this request.

    Only that tab runs the client-side tools of the turn this request starts. SDK callers leave
    this unset."""

    page_state: Optional[dict[str, Any]] = None
    """What the sending browser tab shows when it sends this request, as the Roboto web UI
    describes it: the kind of page, its entities, and the board or session visualizer on it. The service
    validates it, keeps the newest per thread, and shows it to the model on each model call until
    a later request replaces it. SDK callers leave this unset."""

    @pydantic.model_validator(mode="after")
    def _at_least_one_trigger(self) -> "SendMessageRequest":
        if self.message is None and not self.goals and not self.invoke_skills:
            raise ValueError("SendMessageRequest requires at least one of 'message', 'goals', or 'invoke_skills'.")
        return self

    @pydantic.model_validator(mode="after")
    def _message_must_be_user_text_only(self) -> "SendMessageRequest":
        # Client tool results go through AgentThread.submit_client_tool_results, and only the AI writes tool uses.
        # Roboto stores only the text of a message sent here, so reject other content rather than let the request
        # succeed while Roboto drops it.
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
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.start`.

    An agent also starts each of its threads from one, its :py:attr:`~roboto.ai.agent.Agent.request_template`. The
    request needs at least one of ``messages``, ``goals`` and ``invoke_skills``. Building it raises
    ``pydantic.ValidationError`` when:

    - ``messages``, ``goals`` and ``invoke_skills`` are all empty.
    - ``goals`` and ``messages`` are set, ``invoke_skills`` is empty, and no message contains text.
    - ``goals`` holds more than ``MAX_GOALS_PER_TURN`` goals.
    - ``available_skills`` holds more than ``MAX_AVAILABLE_SKILLS`` entries, or lists one skill twice.
    """

    # Pydantic versions before 2.10, which the SDK supports, warn at import that model_profile starts with the
    # protected model_ prefix. An empty protected_namespaces turns the warning off.
    model_config = pydantic.ConfigDict(protected_namespaces=())

    client_context: Optional[ClientViewingContext] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("client_context", "context"),
    )
    """What the caller had open in their client when they started the thread, such as datasets or files.

    Lets the AI resolve references like "this dataset". ``None`` sends none. Also accepted under the key
    ``context``.
    """

    messages: list[AgentMessage] = pydantic.Field(default_factory=list)
    """Messages to start the thread with.

    May be empty when ``goals`` or ``invoke_skills`` is set. When no user message contains text, Roboto puts a short
    user message first that asks the AI to meet the goals or apply the skills.
    """

    system_prompt: Optional[str] = None
    """Instructions Roboto adds to the AI's system prompt for the thread. ``None`` adds none."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Client-side tools the AI may call in the thread: tools your code runs when the AI calls them.

    ``None`` offers none.
    """

    model_profile: Optional[str] = None
    """ID of the model profile to run the thread with, such as ``"standard"`` or ``"advanced"``.

    ``None`` uses Roboto's default profile.
    """

    analysis_scope: Optional[AnalysisScope] = None
    """Analysis scope for the thread.

    Roboto passes the scope to each tool the AI calls, and each tool decides whether to apply it. ``None`` sets no
    scope.
    """

    goals: Optional[list[AgentGoal]] = pydantic.Field(default=None, max_length=MAX_GOALS_PER_TURN)
    """Goals the AI must meet in the first turn, at most ``MAX_GOALS_PER_TURN``.

    Roboto prompts the AI again until it meets every goal or runs out of retries, which leaves the thread in
    :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.GOALS_FAILED`. ``None`` declares none.
    """

    invoke_skills: list["InvokeSkillSpec"] = pydantic.Field(default_factory=list)
    """Skills to apply in the first turn, in order.

    Roboto adds each skill's procedure to the transcript after ``messages``, as a call to the AI's skill-loading tool
    and its result. Defaults to none.
    """

    available_skills: Optional[list["AvailableSkillSpec"]] = pydantic.Field(
        default=None, max_length=MAX_AVAILABLE_SKILLS
    )
    """Skills the AI may apply on its own during the thread, in place of the ones the caller subscribes to.

    - ``None``, the default, lets the AI apply the skills the caller subscribes to, at the versions the caller pinned
      with :py:meth:`~roboto.domain.skills.Skill.set_ai_version`.
    - An empty list lets the AI apply no skill on its own.
    - A non-empty list lets the AI apply exactly these skills, at these versions, whatever the caller subscribes to.

    Roboto resolves the list once, when the thread starts, so later changes to subscriptions or skills do not change
    it. It holds at most ``MAX_AVAILABLE_SKILLS`` entries, one per skill. Unlike ``invoke_skills``, it applies no
    skill and starts no turn, so a request that sets it still needs ``messages``, ``goals`` or ``invoke_skills``.
    """

    visibility: ThreadVisibility = ThreadVisibility.PRIVATE
    """Who can read the thread once it is created.

    The default, :py:attr:`~roboto.ai.agent_thread.ThreadVisibility.PRIVATE`, limits reads to the thread's creator and
    Roboto administrators. ``ORG`` lets every member of the thread's organization read the thread and find it with
    ``POST /v1/ai/threads/search``. :py:meth:`~roboto.ai.agent.Agent.launch` sets this field itself, to ``ORG``
    unless its caller passes another value.
    """

    client_tab_id: Optional[str] = None
    """Opaque id of the browser tab sending this request.

    Only that tab runs the client-side tools of the turn this request starts. SDK callers leave
    this unset."""

    page_state: Optional[dict[str, Any]] = None
    """What the sending browser tab shows when it sends this request, as the Roboto web UI
    describes it: the kind of page, its entities, and the board or session visualizer on it. The service
    validates it, keeps the newest per thread, and shows it to the model on each model call until
    a later request replaces it. SDK callers leave this unset."""

    @pydantic.model_validator(mode="after")
    def _at_least_one_trigger(self) -> "StartAgentThreadRequest":
        if not self.messages and not self.goals and not self.invoke_skills:
            raise ValueError(
                "StartAgentThreadRequest requires at least one of 'messages', 'goals', or 'invoke_skills'."
            )
        return self

    @pydantic.model_validator(mode="after")
    def _at_least_one_seeded_message_must_carry_text_when_goals_present(self) -> "StartAgentThreadRequest":
        # A goal-bearing turn starts from a message with text, and seeded history made only of tool uses and tool
        # results has none. When invoke_skills is set, the skills start the turn instead.
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
        # The AI loads a skill by its name, so a thread can offer only one version of each skill. Reject duplicates
        # here rather than let one of them be dropped without an error.
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
    """Outcome of a client-side tool call: whether the tool ran, failed, or was not run."""

    SUCCESS = "success"
    """The tool ran and returned its output."""

    ERROR = "error"
    """The tool failed, or the client had no tool by that name to run."""

    DECLINED = "declined"
    """The client did not run the tool."""


class ClientToolResult(pydantic.BaseModel):
    """Result of one client-side tool call: a tool your code ran when the AI called it.

    Carried in ``SubmitToolResultsRequest.tool_results``. :py:meth:`~roboto.ai.agent_thread.AgentThread.run` builds
    and submits one for each call to a tool registered with a callback.
    """

    tool_use_id: str
    """ID of the tool use this result answers.

    It is the :py:attr:`~roboto.ai.agent_thread.AgentToolUseContent.tool_use_id` of the AI's call.
    """

    tool_name: str
    """Name of the tool that was called."""

    runtime_ms: int
    """Time the tool took to run, in milliseconds."""

    status: ClientToolResultStatus
    """Outcome of the call."""

    output: Optional[dict[str, Any]] = None
    """Output of the tool as a JSON-compatible dictionary, or ``None`` if it has none."""


class SubmitToolResultsRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.submit_client_tool_results`."""

    tool_results: list[ClientToolResult]
    """Results of the client-side tool calls the AI is waiting on."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Client-side tools the AI may call from the next turn on, replacing the thread's current ones.

    ``None`` leaves them unchanged, and an empty list removes them.
    """

    client_tab_id: Optional[str] = None
    """Opaque id of the browser tab submitting these results.

    The first complete set of results for a turn is accepted. A resend of that set from the same
    tab has no effect; a later set from another tab is rejected with
    :class:`~roboto.exceptions.RobotoClientToolResultsNotPendingException`. SDK callers leave this
    unset."""

    page_state: Optional[dict[str, Any]] = None
    """What the sending browser tab shows when it sends this request, as the Roboto web UI
    describes it: the kind of page, its entities, and the board or session visualizer on it. The service
    validates it, keeps the newest per thread, and shows it to the model on each model call until
    a later request replaces it. SDK callers leave this unset."""


class ClientToolTurnHeartbeatRequest(pydantic.BaseModel):
    """Request payload telling the service that the tab running a thread's client tools is still open.

    While a thread waits on client-side tool results, the tab that runs them sends this
    periodically. If the heartbeats stop, each pending tool call is answered with an error
    result five minutes after the last one.
    """

    client_tab_id: Optional[str] = None
    """Opaque id of the sending browser tab.

    Only the tab that sent the turn's user message keeps the turn alive; when that message named
    no tab, any caller does."""


class ForkAgentThreadRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.fork`."""

    message_sequence_num: int
    """Sequence number of the last message to copy into the new thread; every earlier message is copied too."""


class UpdateThreadVisibilityRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.set_visibility`."""

    visibility: ThreadVisibility
    """Who can read the thread after the change."""


class PinThreadRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.set_pinned`."""

    pinned: bool
    """Whether the thread is pinned for the caller after the change."""


class AgentThreadSubject(pydantic.BaseModel):
    """Resource an agent thread is about, such as a dataset, file or session, recorded so the thread can be found.

    Roboto records one for each resource a turn's goal targets, and for each one the caller has open in
    ``client_context`` when starting the thread or sending a message. ``POST /v1/ai/threads/search`` finds the
    threads about a resource by its ``subject_id``. No SDK method or Roboto route sends or returns this model.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    association_id: str
    """ID of the resource the thread is about, such as a dataset ID."""

    note: str
    """Short, free-form note on why the thread is about the resource."""


__all__ = [
    "AGENT_CONTENT_MODEL_BY_TYPE",
    "AgentArtifactRecord",
    "AgentClientContextEntry",
    "AgentCompressionFillerContent",
    "AgentContent",
    "AgentContentType",
    "AgentDeletedContent",
    "AgentErrorContent",
    "AgentGoalStatus",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentSubtask",
    "AgentSubtaskStatus",
    "AgentThreadDelta",
    "AgentThreadGoalRecord",
    "AgentThreadRecord",
    "AgentThreadStatus",
    "AgentThreadSubject",
    "AgentTextContent",
    "AgentTask",
    "AgentTaskBoundary",
    "AgentTaskMinimal",
    "AgentTaskStatus",
    "AgentToolArtifactResponse",
    "AgentToolDetailResponse",
    "AgentToolResultContent",
    "AgentToolUseContent",
    "AvailableSkillSpec",
    "ClientToolResult",
    "ClientToolResultStatus",
    "ClientToolSpec",
    "ForkAgentThreadRequest",
    "InvokeSkillSpec",
    "PinThreadRequest",
    "SendMessageRequest",
    "ThreadOrigin",
    "ThreadVisibility",
    "StartAgentThreadRequest",
    "SubmitToolResultsRequest",
    "UpdateThreadVisibilityRequest",
]
