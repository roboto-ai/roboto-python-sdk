# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import copy
import time
import typing
from typing import Optional, Union

from ...http import RobotoClient
from ..core import AnalysisScope, ClientViewingContext
from ..goals import AgentGoal
from .agent_thread_goal_view import AgentThreadGoalView
from .client_tool import ClientTool
from .event import (
    AgentErrorEvent,
    AgentEvent,
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolResultEvent,
    AgentToolUseEvent,
)
from .feedback import (
    FeedbackCategory,
    FeedbackSentiment,
    SubmitFeedbackRequest,
    UserFeedbackRecord,
)
from .record import (
    AgentErrorContent,
    AgentMessage,
    AgentRole,
    AgentTask,
    AgentTextContent,
    AgentThreadDelta,
    AgentThreadGoalRecord,
    AgentThreadRecord,
    AgentThreadStatus,
    AgentToolResultContent,
    AgentToolUseContent,
    AvailableSkillSpec,
    ClientToolResult,
    ClientToolResultStatus,
    ClientToolSpec,
    ForkAgentThreadRequest,
    InvokeSkillSpec,
    SendMessageRequest,
    StartAgentThreadRequest,
    SubmitToolResultsRequest,
)

OnEvent = collections.abc.Callable[[AgentEvent], None]

# Backend-injected input-schema metadata, not real tool arguments. Kept on the
# wire (the web UI and the server's compression engine read it), but filtered
# out before a client-tool callback is invoked.
_BACKEND_INJECTED_INPUT_FIELDS = frozenset({"_compression_intent"})


class RobotoAgentGoalsFailedException(RuntimeError):
    """Raised by :meth:`AgentThread.run` when a goal-bearing turn exhausts
    its corrective re-prompt budget without satisfying every declared goal.

    Inherits :class:`RuntimeError` rather than ``RobotoException`` because this
    is a strictly client-side condition — the session is paused, not errored
    on the wire — and the project's ``Roboto*Exception`` hierarchy is reserved
    for exceptions cast from HTTP status codes by the SDK's response layer.
    The typed shape still lets callers distinguish "the agent gave up on
    declared goals" from "I have a bug in my client state machine," which is
    what motivated lifting it out of the opaque ``RuntimeError`` ``run()``
    used to raise on unexpected statuses.

    The session is in :attr:`AgentThreadStatus.GOALS_FAILED`; inspect
    :attr:`AgentThread.messages` and :attr:`AgentThreadRecord.goals` for
    detail about which goals failed and why.
    """

    def __init__(self, thread_id: str) -> None:
        super().__init__(
            f"Thread {thread_id} ended in GOALS_FAILED — the agent could not achieve every "
            "declared goal within its corrective re-prompt budget. The thread needs human "
            "intervention before it can continue."
        )
        self.thread_id = thread_id


class AgentThread:
    """An interactive AI agent session within the Roboto platform.

    An AgentThread is a conversational interface with Roboto's AI assistant,
    enabling users to ask questions, request data analysis, and interact with
    their robotics data through natural language. Sessions maintain conversation
    history and support streaming responses for real-time interaction.

    The primary control-flow primitives are :py:meth:`run` (drive the session
    forward with auto-dispatch of client-side tools) and :py:meth:`events`
    (observe events as the agent generates without taking any actions).

    Examples:
        Fire-and-forget with client-side tools:

        >>> from roboto.ai import AgentThread, client_tool
        >>> @client_tool
        ... def remember(fact: str) -> str:
        ...     \"\"\"Store a fact in long-term memory.\"\"\"
        ...     ...
        >>> session = AgentThread.start("Remember my favorite color is blue.", client_tools=[remember])
        >>> session.run()

        Observing events as they happen:

        >>> session = AgentThread.start("Explain machine learning.")
        >>> for event in session.events():
        ...     if isinstance(event, AgentTextDeltaEvent):
        ...         print(event.text, end="", flush=True)
    """

    @classmethod
    def from_id(
        cls,
        thread_id: str,
        roboto_client: Optional[RobotoClient] = None,
        load_messages: bool = True,
    ) -> AgentThread:
        """Retrieve an existing agent session by its unique identifier.

        Loads a previously created session from the Roboto platform, allowing
        users to resume conversations and access message history.

        Args:
            thread_id: Unique identifier for the session. Accepts both
                ``ags_*`` and legacy ``ch_*`` identifiers.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            load_messages: Whether to load the session's messages. If False, the
                session's messages will be empty.

        Returns:
            AgentThread instance representing the existing session.

        Raises:
            RobotoNotFoundException: If the session does not exist.
            RobotoUnauthorizedException: If the caller lacks permission to access the session.

        Examples:
            Resume an existing session:

            >>> session = AgentThread.from_id("ags_abc123")
            >>> print(f"Session has {len(session.messages)} messages")
            Session has 5 messages
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        query_params = {"load_messages": load_messages}
        record = roboto_client.get(f"v1/ai/threads/{thread_id}", query=query_params).to_record(AgentThreadRecord)

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def start(
        cls,
        message: Optional[Union[str, AgentMessage, collections.abc.Sequence[AgentMessage]]] = None,
        *,
        client_context: Optional[ClientViewingContext] = None,
        system_prompt: Optional[str] = None,
        model_profile: Optional[str] = None,
        org_id: Optional[str] = None,
        client_tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]] = None,
        analysis_scope: Optional[AnalysisScope] = None,
        goals: Optional[collections.abc.Sequence[AgentGoal]] = None,
        invoke_skills: Optional[collections.abc.Sequence[InvokeSkillSpec]] = None,
        available_skills: Optional[collections.abc.Sequence[AvailableSkillSpec]] = None,
        roboto_client: Optional[RobotoClient] = None,
    ) -> AgentThread:
        """Start a new agent session with an initial message.

        Creates a new session and sends the initial message to begin the
        conversation. The AI assistant will process the message and generate a
        response, which can be driven to completion with :py:meth:`run` or
        observed event-by-event with :py:meth:`events`.

        Args:
            message: Initial message to start the conversation. Can be a text
                string, a single AgentMessage, or a sequence of AgentMessage
                objects for multi-turn initialization. Optional when at least
                one entry is provided in ``goals`` or ``invoke_skills``; in
                those cases the server synthesizes a minimal user message —
                implicitly "achieve the goals" or "apply the invoked skills"
                — and the agent will work the turn from there.
            client_context: Optional :class:`ClientViewingContext` describing
                what the calling client (e.g. the Web UI) is currently
                displaying when this session is started. Lets the agent
                resolve deictic references like "this dataset" without the
                user spelling them out. Informational only; does not gate
                authorization or scope tools — see ``analysis_scope`` for
                that.
            system_prompt: Optional system prompt to customize the AI assistant's
                behavior for this conversation.
            model_profile: Optional model profile ID (e.g. "standard",
                "advanced"). Defaults to the deployment's default profile.
            org_id: Organization ID to create the session in. If None, uses the
                caller's default organization.
            client_tools: Optional list of client-side tools to make available
                to the agent. Accepts :class:`ClientTool` instances (which
                include a callback for auto-dispatch) and bare
                :class:`ClientToolSpec` objects (which describe the tool but
                require the caller to submit results manually).
            analysis_scope: Optional :class:`AnalysisScope` for the session
                (e.g. a time window or topic-pattern filter). When provided,
                the scope is persisted on the session and delivered to every
                tool invocation on the server side. Individual tools opt in
                to honoring the scope as they are adopted.
            goals: Optional structured goals to declare for the first turn.
                When provided, ``message`` may be omitted; the server will
                synthesize a minimal user message and the agent runner will
                enforce achievement of every declared goal before completing
                the turn.
            invoke_skills: Optional sequence of :class:`InvokeSkillSpec` to
                invoke one or more stored skills at session start, in order.
                For each entry the server fabricates a ``load_skill``
                tool_use/tool_result pair after any seeded ``message``; with no
                ``message`` and no ``goals``, the fabricated pairs alone seed
                the conversation. Each skill must be visible to the caller (org
                skill or own private skill); the version must exist on the
                skill but is not required to be the latest one. Latest
                (MAX(version)) is used when ``version`` is omitted on an entry.
            available_skills: Optional explicit set of skills the AI may
                auto-invoke during this session, replacing the registry it
                would otherwise derive from the caller's skill subscriptions.
                ``None`` (the default) keeps the subscription-derived behavior;
                an empty list gives the AI no auto-invokable skills; a non-empty
                list of :class:`AvailableSkillSpec` makes exactly those skill
                versions auto-invokable and ignores subscriptions and per-user
                ``ai_version`` pins. Each entry may reference any org skill or
                the caller's own private skill (visibility only — no
                subscription needed), at any version. This is session
                configuration, not a turn trigger: it does not by itself
                satisfy the "needs a message, goal, or invoked skill"
                requirement. Distinct from ``invoke_skills``, which seeds skill
                bodies into the opening transcript.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            AgentThread instance representing the newly created session.

        Raises:
            RobotoInvalidRequestException: If the message format is invalid.
            RobotoUnauthorizedException: If the caller lacks permission to create sessions.

        Examples:
            Start and drive a session with client-side tools:

            >>> from roboto.ai import client_tool
            >>> @client_tool
            ... def recall(query: str) -> str:
            ...     \"\"\"Search long-term memory for facts matching a query.\"\"\"
            ...     ...
            >>> session = AgentThread.start("What do you remember?", client_tools=[recall])
            >>> session.run()
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        if message is None:
            messages: list[AgentMessage] = []
        elif isinstance(message, AgentMessage):
            messages = [message]
        elif isinstance(message, str):
            messages = [AgentMessage.text(text=message, role=AgentRole.USER)]
        else:
            messages = list(message)

        if not messages and not goals and not invoke_skills:
            raise ValueError("AgentThread.start requires at least one of 'message', 'goals', or 'invoke_skills'.")

        # A conversation starts with user input (optionally preceded by a
        # seeded ASSISTANT transcript). ROBOTO and SYSTEM are produced by the
        # server, never passed in — reject them up front so callers get a
        # clear client-side error instead of an opaque server rejection or a
        # session that silently misbehaves.
        for m in messages:
            if m.role not in (AgentRole.USER, AgentRole.ASSISTANT):
                raise ValueError(
                    f"Initial messages must be USER or ASSISTANT (for seeded history); "
                    f"got role={m.role!r}. ROBOTO (tool-result) and SYSTEM messages are "
                    f"produced by the server and cannot be passed as input."
                )

        specs = _extract_specs(client_tools)

        request = StartAgentThreadRequest(
            client_context=client_context,
            messages=list(messages),
            system_prompt=system_prompt,
            model_profile=model_profile,
            client_tools=specs,
            analysis_scope=analysis_scope,
            goals=list(goals) if goals is not None else None,
            invoke_skills=list(invoke_skills) if invoke_skills is not None else [],
            available_skills=list(available_skills) if available_skills is not None else None,
        )

        record = roboto_client.post("v1/ai/threads", caller_org_id=org_id, data=request).to_record(AgentThreadRecord)

        return cls(
            record=record,
            roboto_client=roboto_client,
            client_tools=client_tools,
        )

    def __init__(
        self,
        record: AgentThreadRecord,
        roboto_client: Optional[RobotoClient] = None,
        client_tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]] = None,
    ):
        """Initialize an AgentThread with an underlying record.

        Note:
            This constructor is intended for internal use. Prefer
            :py:meth:`AgentThread.start` or :py:meth:`AgentThread.from_id`.

        Args:
            record: AgentThreadRecord containing the session's persisted data.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            client_tools: Pre-declared client tools. :class:`ClientTool` entries
                are registered for auto-dispatch; :class:`ClientToolSpec` entries
                are recorded as client-side (so the dispatcher doesn't mistake
                them for server tools) but have no callback and require manual
                submission via :py:meth:`submit_client_tool_results`.
        """
        self.__record: AgentThreadRecord = record
        self.__roboto_client: RobotoClient = RobotoClient.defaulted(roboto_client)
        # Tools with a registered callback — the set :py:meth:`run` will
        # auto-dispatch.
        self.__client_tools: dict[str, ClientTool] = {}
        # Every tool name the caller has declared as client-side, including
        # ClientToolSpec entries with no callback. The dispatcher uses this
        # set to distinguish client tools (which we answer) from server tools
        # (which the server answers). Without this split, a mixed server+
        # client tool turn where the server tool's result hasn't been mirrored
        # into the ROBOTO message yet would race: we'd ship an error
        # ClientToolResult for the server tool_use_id, then the server would
        # post the real result, yielding two tool_results for the same id
        # (which Bedrock rejects).
        self.__declared_client_tool_names: set[str] = set()
        # Tracks message indices for which we have emitted AgentStartTextEvent
        # but not yet AgentTextEndEvent. In practice only one span is ever
        # open at a time (the currently-generating assistant message), but
        # modeling as a set keeps the bookkeeping correct if a future server
        # behavior ever streams multiple messages concurrently. Must persist
        # across events() polls so a message that is still GENERATING doesn't
        # receive a premature End on one poll and a duplicate Start on the
        # next when more text chunks arrive.
        self.__open_text_idxs: set[int] = set()
        # Cache for ``self.goals``. Keyed on the ``self.__record.goals`` object
        # itself (compared with ``is``) so a ``refresh`` that installs a fresh
        # goals list invalidates transparently while repeated reads against the
        # same list reuse the wrappers. Holding the list rather than ``id(...)``
        # is load-bearing: an id is only unique among live objects, and since
        # the cache would not otherwise reference the list, a freed list's id
        # could be reused by an unrelated object and yield a false hit. The key
        # may also be ``None`` (the record's "goals not loaded" sentinel), which
        # caches cleanly. The outer ``None`` means "not yet built".
        self.__goals_cache: tuple[Optional[list[AgentThreadGoalRecord]], list[AgentThreadGoalView]] | None = None
        self.__register_tools(client_tools)

    @property
    def thread_id(self) -> str:
        """Unique identifier for this thread."""
        return self.__record.thread_id

    @property
    def latest_message(self) -> Optional[AgentMessage]:
        """The most recent message in the conversation, or None if no messages exist."""
        if len(self.__record.messages) == 0:
            return None
        return self.__record.messages[-1]

    @property
    def messages(self) -> list[AgentMessage]:
        """Complete list of messages in the conversation in chronological order."""
        return self.__record.messages

    @property
    def status(self) -> AgentThreadStatus:
        """Current status of the thread."""
        return self.__record.status

    @property
    def goals(self) -> list[AgentThreadGoalView]:
        """Goals declared across this thread's turns, oldest first.

        Each entry is an :class:`AgentThreadGoalView` SDK wrapper that delegates
        the goal-record fields and adds three resolved properties:

        - :attr:`AgentThreadGoalView.achieve_tool_use` — the LLM's achieve-tool
          invocation, located by ``achieve_tool_use_id``.
        - :attr:`AgentThreadGoalView.achieve_tool_result` — the matching tool
          result block, if one was persisted.
        - :attr:`AgentThreadGoalView.result` — the typed, per-goal-type
          :data:`GoalResult` (with the LLM's submitted payload parsed into
          typed fields).

        Returns an empty list when the thread declared no goals or when
        the underlying record was fetched without loading them — call
        :meth:`refresh` if you expect goals to be present but the list is
        empty.

        Wrappers are cached against the underlying goals-list identity:
        repeated reads return the same list (and the same per-goal wrappers)
        until a ``refresh`` installs a fresh goals list, at which point the
        cache is invalidated transparently. Callers may rely on identity
        comparison across reads against the same snapshot.
        """
        goals_list = self.__record.goals
        cached = self.__goals_cache
        if cached is not None and cached[0] is goals_list:
            return cached[1]
        wrappers = [AgentThreadGoalView(record, self.__record.messages) for record in (goals_list or [])]
        self.__goals_cache = (goals_list, wrappers)
        return wrappers

    @property
    def tasks(self) -> list[AgentTask]:
        """The thread's task list, ordered by position.

        Returns an empty list when the thread has no tasks or when the
        underlying record was fetched without loading them — call
        :meth:`refresh` if you expect tasks but the list is empty.
        """
        return list(self.__record.tasks or [])

    @property
    def client_tool_names(self) -> list[str]:
        """Names of client-side tools registered on this session with callbacks."""
        return list(self.__client_tools.keys())

    @property
    def transcript(self) -> str:
        """Human-readable transcript of the entire conversation.

        Returns a formatted string containing all messages in the conversation,
        with role indicators and message content clearly separated.
        """
        return f"=== {self.__record.thread_id} ===\n" + "\n".join(str(message) for message in self.messages)

    def register_client_tool(self, tool: ClientTool) -> AgentThread:
        """Register a client-side tool for auto-dispatch in subsequent turns.

        The tool's spec is not sent to the backend by this call; pass it via
        the ``client_tools=`` argument on :py:meth:`send`,
        :py:meth:`send_text`, or :py:meth:`submit_client_tool_results` on the
        next outbound request.

        Args:
            tool: The ClientTool to register.

        Returns:
            Self for method chaining.
        """
        self.__client_tools[tool.name] = tool
        self.__declared_client_tool_names.add(tool.name)
        return self

    def unregister_client_tool(self, name: str) -> bool:
        """Remove a previously registered client-tool callback.

        This only removes the local callback. The backend was told about the
        tool in :class:`StartAgentThreadRequest` ``client_tools`` (or via a
        later :py:meth:`send`) and may still emit ``tool_use`` events for it;
        once the callback is gone, :py:meth:`run` will submit an error result
        for those invocations so the agent can recover. There is no
        server-side deregistration API.

        The tool name remains recorded as a declared client tool on this
        session, so the dispatcher still treats it as client-side (and not as
        a server tool whose result the server will post).

        Args:
            name: Name of the client tool to unregister.

        Returns:
            ``True`` if a callback was removed, ``False`` if no callback was
            registered under ``name``.
        """
        return self.__client_tools.pop(name, None) is not None

    def refresh(self) -> AgentThread:
        """Update the session with the latest messages and status.

        Fetches any new messages or status changes from the server and updates
        the local session state.

        Returns:
            Self for method chaining.
        """
        self.__get_delta_and_update()
        return self

    def send(
        self,
        message: Optional[AgentMessage] = None,
        *,
        client_context: Optional[ClientViewingContext] = None,
        client_tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]] = None,
        analysis_scope: Optional[AnalysisScope] = None,
        goals: Optional[collections.abc.Sequence[AgentGoal]] = None,
        invoke_skills: Optional[collections.abc.Sequence[InvokeSkillSpec]] = None,
    ) -> AgentThread:
        """Send a structured message to the session.

        Args:
            message: AgentMessage object containing the message content and
                metadata. Optional when at least one entry is provided in
                ``goals`` or ``invoke_skills``; in that case the server
                synthesizes a minimal user message for the turn.
            client_context: Optional :class:`ClientViewingContext` describing
                what the calling client is currently viewing when this
                message was composed. Informational only; see
                :meth:`AgentThread.start` for full semantics.
            client_tools: Optional client-side tools to add or update for this
                and subsequent turns. ClientTool callbacks are registered on
                the session for auto-dispatch.
            analysis_scope: Optional replacement :class:`AnalysisScope`. When
                provided, overwrites the session's current scope for all
                subsequent tool invocations. When ``None``, the session's
                existing scope (if any) is left untouched.
            goals: Optional structured goals to declare for this turn. The
                agent runner enforces achievement of every declared goal
                before completing the turn.
            invoke_skills: Optional sequence of :class:`InvokeSkillSpec` to
                invoke one or more stored skills as part of this turn. For each
                entry the server fabricates a ``load_skill``
                tool_use/tool_result pair after ``message`` (if any). When
                ``message`` and ``goals`` are both omitted, the fabricated
                pairs alone trigger the turn. Latest (MAX(version)) is used
                when ``version`` is omitted on an entry.

        Returns:
            Self for method chaining.

        Raises:
            RobotoInvalidRequestException: If the message format is invalid.
            RobotoUnauthorizedException: If the caller lacks permission to send messages.
        """
        if message is None and not goals and not invoke_skills:
            raise ValueError("AgentThread.send requires at least one of 'message', 'goals', or 'invoke_skills'.")

        specs = _extract_specs(client_tools)
        request = SendMessageRequest(
            message=message,
            client_context=client_context,
            client_tools=specs,
            analysis_scope=analysis_scope,
            goals=list(goals) if goals is not None else None,
            invoke_skills=list(invoke_skills) if invoke_skills is not None else [],
        )

        self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/messages",
            data=request,
        )

        self.__register_tools(client_tools)
        # When ``message`` is None the server synthesizes the user message (or
        # writes the skill_invocation directly); the SDK has no way to know
        # what landed, so leave the local transcript untouched and rely on the
        # next ``events`` poll to surface it.
        if message is not None:
            self.__record.messages.append(message)
        return self

    def send_text(
        self,
        text: str,
        *,
        client_context: Optional[ClientViewingContext] = None,
        client_tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]] = None,
        analysis_scope: Optional[AnalysisScope] = None,
        goals: Optional[collections.abc.Sequence[AgentGoal]] = None,
    ) -> AgentThread:
        """Send a text message to the session.

        Convenience method for sending a simple text message without needing to
        construct an :class:`AgentMessage`.

        Args:
            text: Text content to send to the assistant.
            client_context: Optional :class:`ClientViewingContext` describing
                what the calling client is currently viewing.
            client_tools: Optional client-side tools to add or update.
            analysis_scope: Optional replacement :class:`AnalysisScope`; see
                :py:meth:`send` for update semantics.
            goals: Optional goals to declare for this turn. See :py:meth:`send`
                for full semantics.

        Returns:
            Self for method chaining.

        Raises:
            RobotoInvalidRequestException: If the text is empty or invalid.
            RobotoUnauthorizedException: If the caller lacks permission to send messages.
        """
        return self.send(
            AgentMessage.text(text=text, role=AgentRole.USER),
            client_context=client_context,
            client_tools=client_tools,
            analysis_scope=analysis_scope,
            goals=goals,
        )

    def submit_client_tool_results(
        self,
        results: collections.abc.Sequence[ClientToolResult],
        client_tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]] = None,
    ) -> AgentThread:
        """Submit results of client-side tool execution to resume the session.

        On success the server has persisted every submitted ``tool_result``
        and queued a new worker turn; the local ``record.status`` flips to
        ``ROBOTO_TURN`` to match. See the inline comment for why the next
        delta poll cannot communicate that transition on its own.

        Args:
            results: Tool results from client-side execution.
            client_tools: Optional updated client-side tools for the next
                invocation. ClientTool callbacks are registered on the session
                for auto-dispatch.

        Returns:
            Self for method chaining.
        """
        specs = _extract_specs(client_tools)
        request = SubmitToolResultsRequest(
            tool_results=list(results),
            client_tools=specs,
        )
        self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/tool-results",
            data=request,
        )
        self.__register_tools(client_tools)
        # The server appends our results to the existing ROBOTO tool_result message, but the SDK's token has
        # already advanced past that message on the prior CLIENT_TOOL_TURN poll — the next delta returns empty
        # with status=None, so record.status stays CLIENT_TOOL_TURN. Without this flip, run() re-dispatches the
        # same tool_uses and re-POSTs; the second POST hits ROBOTO_TURN and raises RobotoInvalidRequestException.
        self.__record.status = AgentThreadStatus.ROBOTO_TURN
        return self

    def invoke_skill(self, skill_id: str, version: Optional[int] = None) -> AgentThread:
        """Manually invoke a skill into this thread.

        Thin wrapper around :py:meth:`send` that builds a single-element
        ``invoke_skills`` list and sends it with no user message — kept for
        SDK ergonomics on the common "invoke exactly one skill" case.

        Args:
            skill_id: The skill to invoke.
            version: Optional version number. Must exist on the skill (any
                version is invokable). If omitted, the latest (MAX(version))
                version is used.

        Returns:
            Self for method chaining.

        Examples:
            Apply a skill's latest version to the current turn:

            >>> thread.invoke_skill("sk_qa_review")

            Apply a specific version of the skill:

            >>> thread.invoke_skill("sk_qa_review", version=2)
        """
        return self.send(invoke_skills=[InvokeSkillSpec(skill_id=skill_id, version=version)])

    def events(
        self,
        tick: float = 0.2,
        timeout: Optional[float] = None,
    ) -> collections.abc.Generator[AgentEvent, None, None]:
        """Yield events from the agent as they are generated.

        Polls the session and yields :class:`AgentEvent` objects as new content
        arrives. Does **not** auto-dispatch client-side tools — if the session
        reaches :py:attr:`AgentThreadStatus.CLIENT_TOOL_TURN`, the generator
        returns and the caller is expected to call
        :py:meth:`submit_client_tool_results` (and then call :py:meth:`events`
        again to continue). For automatic dispatch, use :py:meth:`run`.

        Args:
            tick: Polling interval in seconds between checks for new content.
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.

        Yields:
            :class:`AgentEvent` objects (:class:`AgentStartTextEvent`,
            :class:`AgentTextDeltaEvent`, :class:`AgentTextEndEvent`,
            :class:`AgentToolUseEvent`, :class:`AgentToolResultEvent`,
            :class:`AgentErrorEvent`) as they become available. Text events
            are scoped to a single message: an :class:`AgentTextEndEvent` is
            emitted at the end of each message that carried text, so adjacent
            assistant messages produce separate start/end pairs.

        Raises:
            TimeoutError: If ``timeout`` elapses before the session pauses.

        Examples:
            Stream text output as it arrives:

            >>> for event in session.events():
            ...     if isinstance(event, AgentTextDeltaEvent):
            ...         print(event.text, end="", flush=True)
        """
        start_time = time.time()

        while True:
            delta = self.__get_delta_and_update()

            for idx in sorted(delta.messages_by_idx.keys()):
                delta_message = delta.messages_by_idx[idx]
                if delta_message.role == AgentRole.USER:
                    continue

                # Iterate only the *new* content chunks carried by this
                # delta. __get_delta_and_update() has already appended them
                # onto self.__record.messages[idx]; the delta_message is our
                # incremental view.
                for content in delta_message.content:
                    if isinstance(content, AgentTextContent):
                        if idx not in self.__open_text_idxs:
                            yield AgentStartTextEvent()
                            self.__open_text_idxs.add(idx)
                        yield AgentTextDeltaEvent(text=content.text)
                    else:
                        # Any non-text content block closes an open text span
                        # for this message — text followed by a tool_use/
                        # tool_result/error is a clean partition.
                        if idx in self.__open_text_idxs:
                            yield AgentTextEndEvent()
                            self.__open_text_idxs.discard(idx)

                        if isinstance(content, AgentToolUseContent):
                            yield AgentToolUseEvent(
                                name=content.tool_name,
                                tool_use_id=content.tool_use_id,
                                input=content.input,
                            )
                        elif isinstance(content, AgentToolResultContent):
                            yield AgentToolResultEvent(
                                name=content.tool_name,
                                tool_use_id=content.tool_use_id,
                                success=content.status == ClientToolResultStatus.SUCCESS.value,
                                output=content.raw_response,
                                runtime_ms=content.runtime_ms,
                            )
                        elif isinstance(content, AgentErrorContent):
                            yield AgentErrorEvent(
                                error_message=content.error_message,
                                error_code=content.error_code,
                            )

                # Close any still-open text span *only* if the message has
                # reached a terminal status. While the message is still
                # GENERATING, leave the span open so the next poll continues
                # the same Start/Delta/End sequence instead of restarting it.
                if idx in self.__open_text_idxs and self.__record.messages[idx].status.is_terminal():
                    yield AgentTextEndEvent()
                    self.__open_text_idxs.discard(idx)

            if self.__record.status != AgentThreadStatus.ROBOTO_TURN:
                return

            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for agent to finish generating")
            # Cadence gate: each poll of the delta endpoint is at least
            # ``tick`` seconds apart. Placed at the bottom of the loop (after
            # the terminal-status and timeout checks) so the first poll fires
            # immediately — no leading delay when the session has already
            # reached USER_TURN / CLIENT_TOOL_TURN.
            time.sleep(tick)

    def run(
        self,
        *,
        on_event: Optional[OnEvent] = None,
        tick: float = 0.2,
        timeout: Optional[float] = None,
    ) -> AgentThread:
        """Drive the session forward until it is the user's turn.

        Polls the session, auto-dispatching any pending client-side tool
        invocations against the callbacks registered with this session
        (via :py:meth:`start`, :py:meth:`send`, or
        :py:meth:`register_client_tool`). Returns once the session status is
        :py:attr:`AgentThreadStatus.USER_TURN`.

        If the agent requests a client-side tool that has no registered
        callback, an ``error`` result is submitted automatically with a
        descriptive message so the agent can recover, and execution continues.
        If a registered callback raises, the exception is caught and also
        submitted as an ``error`` result.

        Args:
            on_event: Optional callback invoked for each :class:`AgentEvent`
                as the agent generates (text deltas, tool uses, tool results,
                start/end markers). Use this for progress display or logging.
            tick: Polling interval in seconds between status checks.
            timeout: Total time budget in seconds across the whole loop. If
                None, waits indefinitely.

        Returns:
            Self for method chaining.

        Raises:
            TimeoutError: If the ``timeout`` budget is exhausted before the
                session reaches ``USER_TURN``.
            RuntimeError: If the session is in ``CLIENT_TOOL_TURN`` with no
                messages (i.e. a server state that should not be reachable),
                or if an unexpected :class:`AgentThreadStatus` value is
                observed.
            RobotoHttpException: Propagated from the underlying
                :py:meth:`submit_client_tool_results` POST if the server
                rejects the submission (for example, a concurrent caller
                already answered the tool-use).

        Examples:
            Fire-and-forget:

            >>> session = AgentThread.start("Remember my favorite color is blue.", client_tools=[remember])
            >>> session.run()

            With progress logging:

            >>> def log(event):
            ...     if isinstance(event, AgentToolUseEvent):
            ...         print(f"[tool-use] {event.name}({event.input})")
            >>> session.run(on_event=log)
        """
        start_time = time.time()

        while True:
            remaining = None if timeout is None else max(0.0, timeout - (time.time() - start_time))
            if timeout is not None and remaining == 0.0:
                raise TimeoutError("Timeout waiting for user turn")

            for event in self.events(tick=tick, timeout=remaining):
                if on_event is not None:
                    on_event(event)

            status = self.__record.status
            if status == AgentThreadStatus.USER_TURN:
                return self

            if status == AgentThreadStatus.CLIENT_TOOL_TURN:
                results = self.__dispatch_pending_client_tools()
                self.submit_client_tool_results(results)
                continue

            if status == AgentThreadStatus.GOALS_FAILED:
                # Typed exception so callers can distinguish "agent gave up on
                # declared goals" from generic RuntimeError. The session is
                # now paused; inspect messages and AgentThreadRecord.goals
                # for the failure detail.
                raise RobotoAgentGoalsFailedException(self.thread_id)

            raise RuntimeError(
                f"Session {self.thread_id} paused in unexpected status {status}; "
                "expected USER_TURN or CLIENT_TOOL_TURN."
            )

    def __get_delta_and_update(self) -> AgentThreadDelta:
        delta = self.__roboto_client.get(
            f"v1/ai/threads/{self.__record.thread_id}/delta",
            query={"next_token": self.__record.continuation_token},
        ).to_record(AgentThreadDelta)

        self.__record.continuation_token = delta.continuation_token

        for idx in sorted(delta.messages_by_idx.keys()):
            if idx < len(self.__record.messages):
                self.__record.messages[idx].status = delta.messages_by_idx[idx].status
                self.__record.messages[idx].content.extend(delta.messages_by_idx[idx].content)
            else:
                self.__record.messages.append(delta.messages_by_idx[idx])

        if delta.status is not None:
            self.__record.status = delta.status

        if delta.title is not None:
            self.__record.title = delta.title

        # ``goals`` and ``tasks`` arrive as full snapshots with the same
        # contract: ``None`` means unchanged since the last poll (retain what we
        # hold), while any list — including an empty one — is authoritative and
        # replaces the current value. Skipping these left a refreshed thread
        # reporting only the goals/tasks captured at the original fetch.
        if delta.goals is not None:
            self.__record.goals = delta.goals

        if delta.tasks is not None:
            self.__record.tasks = delta.tasks

        return delta

    def __register_tools(
        self,
        tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]],
    ) -> None:
        if tools is None:
            return
        for tool in tools:
            # Every declared tool (callback-backed or spec-only) goes into
            # the declared-names set so the dispatcher treats it as client-
            # side; only callback-backed tools are actually invocable.
            self.__declared_client_tool_names.add(tool.name)
            if isinstance(tool, ClientTool):
                self.__client_tools[tool.name] = tool

    def __dispatch_pending_client_tools(self) -> list[ClientToolResult]:
        """Collect ClientToolResults for every tool_use the server expects us to answer.

        The server promotes the session to ``CLIENT_TOOL_TURN`` in two ways
        (see ``calculate_thread_status`` in ``roboto_service``):

        1. The latest message is an assistant message ending in a client
           ``tool_use`` block. All unanswered tool_uses live on
           ``messages[-1]``.
        2. The latest message is a ROBOTO ``tool_result`` message answering
           server tool_uses, but the preceding assistant message also asked
           for one or more client tools whose results are still outstanding.
           In this mixed-tool case, the unanswered tool_uses live on
           ``messages[-2]`` and the already-submitted results live on
           ``messages[-1]``.

        Scanning only ``latest_message`` misses case 2 — the method would
        return ``[]``, ``submit_client_tool_results([])`` would fire a no-op
        POST, and the server would keep re-asserting ``CLIENT_TOOL_TURN`` on
        the next poll, producing a loop bounded only by ``run(timeout=...)``.
        """
        messages = self.__record.messages
        if len(messages) == 0:
            raise RuntimeError("Session is in CLIENT_TOOL_TURN but has no messages.")

        latest = messages[-1]
        # Case 1: the latest message is the assistant message carrying the
        # unanswered tool_uses.
        if latest.role == AgentRole.ASSISTANT:
            tool_uses = [c for c in latest.content if isinstance(c, AgentToolUseContent)]
            answered_ids: set[str] = set()
        # Case 2: latest is a ROBOTO tool_result; unanswered client tool_uses
        # are on the preceding assistant message.
        elif latest.role == AgentRole.ROBOTO and len(messages) >= 2 and messages[-2].role == AgentRole.ASSISTANT:
            tool_uses = [c for c in messages[-2].content if isinstance(c, AgentToolUseContent)]
            answered_ids = {c.tool_use_id for c in latest.content if isinstance(c, AgentToolResultContent)}
        else:
            raise RuntimeError(
                f"Session {self.thread_id} is in CLIENT_TOOL_TURN but neither the latest "
                f"message nor its predecessor contains unanswered client tool_uses."
            )

        results: list[ClientToolResult] = []
        for tool_use in tool_uses:
            if tool_use.tool_use_id in answered_ids:
                continue
            # Dispatch only tool_uses whose name was declared as client-side
            # on this session. In case 2 (mixed server+client turn),
            # messages[-2] may also carry server tool_uses; if the server
            # hasn't yet mirrored its own tool_result into messages[-1],
            # those would appear unanswered from our perspective. Submitting
            # an error result for a server tool_use_id would collide with
            # the server's own tool_result once it lands, producing two
            # tool_results for the same id (which Bedrock rejects).
            if tool_use.tool_name not in self.__declared_client_tool_names:
                continue
            results.append(self.__execute_single_client_tool(tool_use))
        return results

    def __execute_single_client_tool(self, tool_use: AgentToolUseContent) -> ClientToolResult:
        tool_name = tool_use.tool_name
        # Deep-copy so a callback that mutates nested structures (pops from a
        # list, sets keys on an inner dict) cannot corrupt the session's own
        # in-memory copy of the message.
        tool_input = copy.deepcopy(tool_use.input) if tool_use.input else {}
        # Backend-injected metadata must not reach the callback as kwargs.
        tool_input = {key: value for key, value in tool_input.items() if key not in _BACKEND_INJECTED_INPUT_FIELDS}
        tool = self.__client_tools.get(tool_name)

        if tool is None:
            return ClientToolResult(
                tool_use_id=tool_use.tool_use_id,
                tool_name=tool_name,
                runtime_ms=0,
                status=ClientToolResultStatus.ERROR,
                output={
                    "error": (
                        f"No callback registered for client tool {tool_name!r}. "
                        "Register one with register_client_tool(), pass it via client_tools=, "
                        "or call submit_client_tool_results() manually."
                    ),
                },
            )

        t0 = time.monotonic()
        try:
            output = tool(**tool_input)
        except Exception as exc:
            runtime_ms = int((time.monotonic() - t0) * 1000)
            return ClientToolResult(
                tool_use_id=tool_use.tool_use_id,
                tool_name=tool_name,
                runtime_ms=runtime_ms,
                status=ClientToolResultStatus.ERROR,
                output={"error": f"{type(exc).__name__}: {exc}"},
            )

        runtime_ms = int((time.monotonic() - t0) * 1000)
        if output is None:
            output_dict: dict[str, typing.Any] = {}
        elif isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {"result": output}
        return ClientToolResult(
            tool_use_id=tool_use.tool_use_id,
            tool_name=tool_name,
            runtime_ms=runtime_ms,
            status=ClientToolResultStatus.SUCCESS,
            output=output_dict,
        )

    def submit_feedback(
        self,
        message_sequence_num: int,
        sentiment: FeedbackSentiment,
        categories: Optional[list[FeedbackCategory]] = None,
        notes: Optional[str] = None,
    ) -> UserFeedbackRecord:
        """Submit structured feedback on a specific assistant message in this session.

        Persists categorized feedback so it can be reviewed by Roboto operators.
        Re-submitting from the same user on the same message overwrites
        ``sentiment``, ``categories``, and ``notes`` on the existing row
        rather than creating a duplicate; the ``feedback_id`` and original
        ``created``/``created_by`` are preserved.

        Args:
            message_sequence_num: Zero-indexed position of the assistant message being rated.
            sentiment: Overall rating direction.
            categories: Zero or more categories describing the feedback. Must match ``sentiment``.
                ``FeedbackCategory.OTHER`` is always permitted but requires ``notes``.
            notes: Free-text notes. Required when ``FeedbackCategory.OTHER`` is among the categories.

        Returns:
            The persisted feedback as a :class:`UserFeedbackRecord`. Admin
            triage columns (``admin_label``, ``admin_note``, ``resolved``,
            ``resolved_by``, ``resolved_at``) are intentionally not part of
            this shape — they are only visible through the admin API.

        Raises:
            RobotoInvalidRequestException: If the message is still generating, the
                sentiment/category combination is invalid, or ``OTHER`` is used
                without notes.
            RobotoUnauthorizedException: If the caller cannot access this session.
            RobotoNotFoundException: If ``message_sequence_num`` is out of range.
        """
        # Default to ``[]`` only when the caller actually omitted categories.
        # ``categories or []`` would also flatten an explicit ``[]`` through the
        # truthiness check, which is the same value but it is worth making the
        # distinction explicit so a future ``[None]`` or similar doesn't get
        # silently swallowed.
        request = SubmitFeedbackRequest(
            sentiment=sentiment,
            categories=categories if categories is not None else [],
            notes=notes,
        )
        return self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/messages/{message_sequence_num}/feedback",
            data=request,
        ).to_record(UserFeedbackRecord)

    def fork(self, message_sequence_num: int) -> AgentThread:
        """Fork this session's history up to a specific message into a new session owned by the caller.

        Available to the session's creator (forking their own session) and to
        Roboto admins (``is_roboto_admin``) forking anyone's session. The new
        session carries the source session's ``org_id`` so tool calls resolve
        against the source org's data. The new session is owned by the caller,
        so admin forks of a customer session never appear in the customer's
        session list.

        Args:
            message_sequence_num: Highest message sequence number (inclusive) to copy.

        Returns:
            A new ``AgentThread`` instance for the forked session.

        Raises:
            RobotoUnauthorizedException: If the caller is not a member of the
                source session's org, or is a member but is neither the source
                session's creator nor a Roboto admin.
            RobotoInvalidRequestException: If ``message_sequence_num`` is out
                of range or points at a message still generating.
        """
        request = ForkAgentThreadRequest(message_sequence_num=message_sequence_num)
        record = self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/fork",
            data=request,
        ).to_record(AgentThreadRecord)
        return AgentThread(record=record, roboto_client=self.__roboto_client)


def _extract_specs(
    tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]],
) -> Optional[list[ClientToolSpec]]:
    if tools is None:
        return None
    return [tool.spec if isinstance(tool, ClientTool) else tool for tool in tools]
