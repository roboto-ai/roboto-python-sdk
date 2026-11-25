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
from ..core.record import CLIENT_TOOL_NAME_PREFIX
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
    PinThreadRequest,
    SendMessageRequest,
    StartAgentThreadRequest,
    SubmitToolResultsRequest,
    ThreadVisibility,
    UpdateThreadVisibilityRequest,
)

OnEvent = collections.abc.Callable[[AgentEvent], None]
"""Function that handles one :py:const:`~roboto.ai.agent_thread.AgentEvent`, and returns nothing.

Type of the ``on_event`` argument of :py:meth:`~roboto.ai.agent_thread.AgentThread.run`.
"""

# Fields Roboto adds to every tool's input schema, which the AI fills in with its reason for the call. They are not
# the tool's arguments: they stay in the thread's messages, but a client tool's function never receives them.
_BACKEND_INJECTED_INPUT_FIELDS = frozenset({"_compression_intent"})


class RobotoAgentGoalsFailedException(RuntimeError):
    """The AI used up its retries for a turn without achieving every goal declared for it.

    :py:meth:`~roboto.ai.agent_thread.AgentThread.run` raises it when the thread reaches
    :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.GOALS_FAILED`. The thread needs a person to act before it can
    continue; its :py:attr:`~roboto.ai.agent_thread.AgentThread.goals` and ``messages`` show which goals failed and
    why.

    It subclasses ``RuntimeError``, not a Roboto exception, because the SDK raises it from the thread's status rather
    than from an error response from Roboto.
    """

    def __init__(self, thread_id: str) -> None:
        super().__init__(
            f"Thread {thread_id} ended in GOALS_FAILED — the agent could not achieve every "
            "declared goal within its corrective re-prompt budget. The thread needs human "
            "intervention before it can continue."
        )
        self.thread_id = thread_id
        """ID of the thread whose goals failed."""


class AgentThread:
    """A thread: a persistent, multi-turn conversation with Roboto's AI.

    Get an ``AgentThread`` from ``start``, ``from_id``, ``fork`` or :py:meth:`~roboto.ai.agent.Agent.launch`. To wrap an
    :py:class:`~roboto.ai.agent_thread.AgentThreadRecord` already fetched from Roboto, build an ``AgentThread`` from it
    directly. Each instance holds a copy of the thread's record, which ``refresh``, ``events`` and ``run`` bring up to
    date.

    Each message you send starts a turn, in which the AI replies. ``events`` yields the AI's reply as it writes it, and
    returns when the turn needs your code: for your next message, or for the results of client tools, which are tools
    your code runs when the AI calls them. ``run`` also runs those tools, with the functions registered on this
    instance, and returns when it is your turn to send a message.

    Args:
        record: Record of the thread.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        client_tools: Client tools to register on this instance, without sending them to Roboto. ``run`` calls the
            function of each :py:class:`~roboto.ai.agent_thread.ClientTool` when the AI calls it. A
            :py:class:`~roboto.ai.agent_thread.ClientToolSpec` has no function, so ``run`` answers calls to it with an
            error result; submit its results yourself with ``submit_client_tool_results`` after ``events`` returns.
            ``None`` registers none.
    """

    @classmethod
    def from_id(
        cls,
        thread_id: str,
        roboto_client: Optional[RobotoClient] = None,
        load_messages: bool = True,
    ) -> AgentThread:
        """Fetch a thread by its ID.

        Fetches the messages of a long thread in several requests, and returns once it holds them all.

        Args:
            thread_id: ID of the thread, which begins with ``ath_``. Some older threads have IDs beginning with
                ``ags_`` or ``ch_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            load_messages: Whether to fetch the thread's messages. When ``False``, ``messages`` is empty until the
                next ``refresh``, ``events`` or ``run``, which fetches every message.

        Raises:
            RobotoNotFoundException: No thread has this ID.

        Examples:
            Fetch a thread to continue the conversation:

            >>> thread = AgentThread.from_id("ath_12345")
            >>> print(len(thread.messages))
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        query_params = {"load_messages": load_messages, "paged": True}
        record = roboto_client.get(f"v1/ai/threads/{thread_id}", query=query_params).to_record(AgentThreadRecord)

        thread = cls(record=record, roboto_client=roboto_client)
        if record.has_more:
            thread.refresh()
        return thread

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
        """Create a thread and start the AI's first turn in it.

        The AI starts replying as soon as the thread exists; follow its reply with ``run`` or ``events``. The thread
        needs at least one of ``message``, ``goals`` and ``invoke_skills``. It is
        :py:attr:`~roboto.ai.agent_thread.ThreadVisibility.PRIVATE`; share it with ``set_visibility``. A guest of the
        organization starts a thread only when a role they hold lets them use AI.

        Args:
            message: Message or messages to start the thread with. A string becomes a user message. A sequence of
                :py:class:`~roboto.ai.agent_thread.AgentMessage` objects may include assistant messages, to start from
                an earlier conversation. ``None`` is allowed when ``goals`` or ``invoke_skills`` is set; when no user
                message contains text, Roboto puts a short user message first that asks the AI to meet the goals or
                apply the skills.
            client_context: What the caller has open in their client as the thread starts, such as datasets or files.
                Lets the AI resolve references like "this dataset". It does not limit what the AI's tools can reach.
                ``None`` sends none.
            system_prompt: Instructions Roboto adds to the AI's system prompt for the thread. ``None`` adds none.
            model_profile: ID of the model profile to run the thread with, such as ``"standard"`` or ``"advanced"``.
                ``None`` uses Roboto's default profile.
            org_id: Organization to create the thread in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            client_tools: Client tools the AI may call in the thread, registered on the returned instance as the
                class's ``client_tools`` argument describes. ``None`` offers none.
            analysis_scope: Analysis scope for the thread. Roboto passes the scope to each tool the AI calls, and each
                tool decides whether to apply it. ``None`` sets no scope.
            goals: Goals the AI must meet in the first turn, at most 5
                (:py:const:`~roboto.ai.agent_thread.record.MAX_GOALS_PER_TURN`). Roboto prompts the AI again until it
                meets every goal or runs out of retries, which leaves the thread in
                :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.GOALS_FAILED`. ``None`` declares none.
            invoke_skills: Skills to apply in the first turn, in order. Roboto adds each skill's procedure to the
                transcript after ``message``, as a call to the AI's skill-loading tool and its result. ``None`` applies
                none.
            available_skills: Skills the AI may apply on its own during the thread, at most 100, one per skill, in
                place of the ones the caller subscribes to. ``None`` lets the AI apply the skills the caller subscribes
                to, at the versions the caller pinned; an empty list lets it apply none. Unlike ``invoke_skills``, it
                applies no skill and starts no turn, so setting it alone does not meet the need for ``message``,
                ``goals`` or ``invoke_skills``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new thread.

        Raises:
            ValueError: None of ``message``, ``goals`` and ``invoke_skills`` is set, or a message's role is neither
                ``USER`` nor ``ASSISTANT``.
            pydantic.ValidationError: The arguments break a rule of
                :py:class:`~roboto.ai.agent_thread.StartAgentThreadRequest`, such as more than 5 goals.
            RobotoNotFoundException: A skill in ``invoke_skills`` or ``available_skills`` does not exist, the caller
                cannot see it, or it has no version with the number given.
            RobotoUnauthorizedException: A skill in ``invoke_skills`` is one the caller neither wrote nor subscribes
                to, or the caller is a guest of the organization and holds no role that lets them use AI.

        Examples:
            Start a thread with a client tool, and run it until it is your turn:

            >>> from roboto.ai import client_tool
            >>> @client_tool
            ... def client_recall(query: str) -> str:
            ...     \"\"\"Search long-term memory for facts matching a query.\"\"\"
            ...     ...
            >>> thread = AgentThread.start("What do you remember?", client_tools=[client_recall])
            >>> thread.run()
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

        # Roboto writes every ROBOTO message itself, so reject one here with an error that says so.
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
        # Every request about this thread passes caller_org_id=record.org_id, because Roboto refuses some thread
        # requests that name no organization, or that name one other than the thread's.
        self.__record: AgentThreadRecord = record
        self.__roboto_client: RobotoClient = RobotoClient.defaulted(roboto_client)
        # Tools with a function, which run calls.
        self.__client_tools: dict[str, ClientTool] = {}
        # Indexes of messages whose text span is open: events has yielded AgentStartTextEvent for them but not yet
        # AgentTextEndEvent. Kept across events calls, so text a later poll brings for a message still generating
        # continues its span instead of starting another.
        self.__open_text_idxs: set[int] = set()
        # Cache for goals: the record's goals list and the views built over it. goals compares the stored list with
        # the record's by identity (is), so a new list from Roboto rebuilds the views. Holding the list rather than
        # its id() keeps the list alive, so its id cannot pass to a new object and match by accident. The list may
        # be None, for a record without goals; the outer None means nothing is cached yet.
        self.__goals_cache: tuple[Optional[list[AgentThreadGoalRecord]], list[AgentThreadGoalView]] | None = None
        self.__register_tools(client_tools)

    @property
    def thread_id(self) -> str:
        """Unique ID of the thread."""
        return self.__record.thread_id

    @property
    def latest_message(self) -> Optional[AgentMessage]:
        """Latest message in the thread, or ``None`` if this instance holds no messages."""
        if len(self.__record.messages) == 0:
            return None
        return self.__record.messages[-1]

    @property
    def messages(self) -> list[AgentMessage]:
        """Messages in the thread, oldest first.

        :py:attr:`~roboto.ai.agent_thread.AgentThreadRecord.messages` says when it is empty.
        """
        return self.__record.messages

    @property
    def status(self) -> AgentThreadStatus:
        """Status of the thread: whose turn it is, or why the thread stopped."""
        return self.__record.status

    @property
    def turn_notice(self) -> Optional[str]:
        """Short, human-readable note about the turn in progress.

        ``None`` when there is nothing to report. :py:attr:`~roboto.ai.agent_thread.AgentThreadRecord.turn_notice`
        says what it reports and when Roboto sets it.
        """
        return self.__record.turn_notice

    @property
    def visibility(self) -> ThreadVisibility:
        """Visibility of the thread: who can read it."""
        return self.__record.visibility

    @property
    def goals(self) -> list[AgentThreadGoalView]:
        """Goals declared across the thread's turns, ordered by the turn that declared them.

        Each is an :py:class:`~roboto.ai.agent_thread.AgentThreadGoalView`, which adds to the goal's record the tool use
        in which the AI submitted the goal's result (``achieve_tool_use``), that tool use's result
        (``achieve_tool_result``), and the goal's parsed result (``result``). Empty when the thread declared no goals,
        or when this instance's record was returned without its goals.

        Repeated reads return the same list and the same views until this instance receives a new list of goals from
        Roboto.
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
        """Task list of the thread, ordered by :py:attr:`~roboto.ai.agent_thread.AgentTask.position`.

        Empty when the thread has no tasks, or when this instance's record was returned without its tasks.
        """
        return list(self.__record.tasks or [])

    @property
    def client_tool_names(self) -> list[str]:
        """Names of the client tools registered on this instance with a function."""
        return list(self.__client_tools.keys())

    @property
    def transcript(self) -> str:
        """Text of the conversation: a line with the thread's ID, then each message under a line naming its role."""
        return f"=== {self.__record.thread_id} ===\n" + "\n".join(str(message) for message in self.messages)

    def register_client_tool(self, tool: ClientTool) -> AgentThread:
        """Register a client tool's function on this instance, for ``run`` to call when the AI calls the tool.

        This call does not send the tool to Roboto, so the AI cannot call it yet. Pass it in ``client_tools`` to the
        next ``send``, ``send_text`` or ``submit_client_tool_results``.

        Args:
            tool: Client tool to register. It replaces a tool registered under the same name.

        Returns:
            This instance, with ``tool``'s function registered.

        Examples:
            Register a client tool and offer it to the AI with the next message:

            >>> from roboto.ai import client_tool
            >>> @client_tool
            ... def client_remember(fact: str) -> str:
            ...     \"\"\"Store a fact in long-term memory.\"\"\"
            ...     ...
            >>> thread.register_client_tool(client_remember)
            >>> thread.send_text("Remember that the test rig is in bay 3.", client_tools=[client_remember])
            >>> thread.run()
        """
        self.__client_tools[tool.name] = tool
        return self

    def unregister_client_tool(self, name: str) -> bool:
        """Remove a client tool's function from this instance.

        Roboto keeps offering the tool to the AI until a request replaces the thread's client tools. Its name still has
        the ``client_`` prefix, so ``run`` answers later calls to it with an error result, which the AI can recover
        from.

        Args:
            name: Name of the client tool.

        Returns:
            ``True`` if a function was removed, ``False`` if none was registered under ``name``.

        Examples:
            Stop running a client tool in this process:

            >>> thread.unregister_client_tool("client_remember")
        """
        return self.__client_tools.pop(name, None) is not None

    def refresh(self) -> AgentThread:
        """Fetch the thread's changes since this instance last fetched them, and apply them to its record.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            Check whether the AI has finished its turn:

            >>> thread.refresh()
            >>> print(thread.status)
        """
        # A delta that reports has_more carries only the first of the changes; the next request fetches what follows.
        while self.__get_delta_and_update().has_more:
            pass
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
        """Send a message to the thread, starting the AI's next turn.

        The thread needs at least one of ``message``, ``goals`` and ``invoke_skills``. This instance appends
        ``message`` to ``messages`` at once; the next ``refresh``, ``events`` or ``run`` brings the AI's reply, and,
        when ``message`` is ``None``, the message Roboto writes in its place.

        Args:
            message: User message that starts the turn, containing only text. ``None`` is allowed when ``goals`` or
                ``invoke_skills`` is set. With goals, Roboto writes a short user message that asks the AI to meet them;
                with only skills, the skills start the turn.
            client_context: What the caller had open in their client when they wrote the message, such as datasets or
                files. Lets the AI resolve references like "this dataset". It does not limit what the AI's tools can
                reach. ``None`` sends none.
            client_tools: Client tools the AI may call from this turn on, registered on this instance as the class's
                ``client_tools`` argument describes. A non-empty list replaces the thread's client tools; ``None`` or
                an empty list leaves them unchanged.
            analysis_scope: Analysis scope that replaces the thread's own, from this turn on. Roboto passes the scope
                to each tool the AI calls, and each tool decides whether to apply it. ``None`` leaves the thread's
                scope unchanged.
            goals: Goals the AI must meet in this turn, at most 5
                (:py:const:`~roboto.ai.agent_thread.record.MAX_GOALS_PER_TURN`). Roboto prompts the AI again until it
                meets every goal or runs out of retries, which leaves the thread in
                :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.GOALS_FAILED`. ``None`` declares none.
            invoke_skills: Skills to apply in this turn, in order. Roboto adds each skill's procedure to the transcript
                after ``message``, as a call to the AI's skill-loading tool and its result. Only the thread's creator
                may set it, and only while the thread's status is
                :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.USER_TURN`. ``None`` applies none.

        Returns:
            This instance, with ``message`` appended to ``messages``.

        Raises:
            ValueError: None of ``message``, ``goals`` and ``invoke_skills`` is set.
            pydantic.ValidationError: The arguments break a rule of
                :py:class:`~roboto.ai.agent_thread.SendMessageRequest`, such as a ``message`` that is not a user
                message made only of text.
            RobotoThreadReadOnlyException: The thread's origin is a surface outside Roboto, such as Slack. ``fork`` it
                to continue in Roboto.
            RobotoInvalidRequestException: ``invoke_skills`` is set and the thread's status is not ``USER_TURN``.
            RobotoUnauthorizedException: ``invoke_skills`` is set and the caller did not create the thread, or it
                names a skill the caller neither wrote nor subscribes to.
            RobotoNotFoundException: A skill in ``invoke_skills`` does not exist, the caller cannot see it, or it has
                no version with the number given.

        Examples:
            Send a message and run the thread until it is your turn again:

            >>> from roboto.ai.agent_thread import AgentMessage, AgentRole
            >>> thread.send(AgentMessage.text(text="Which topics have GPS data?", role=AgentRole.USER))
            >>> thread.run()
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
            caller_org_id=self.__record.org_id,
            data=request,
        )

        self.__register_tools(client_tools)
        # With no message, Roboto writes the turn's opening itself, and only the next delta shows what it wrote.
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
        """Send a text message to the thread, starting the AI's next turn.

        Builds a user message from ``text`` and calls ``send``, whose failures also apply.

        Args:
            text: Text of the message.
            client_context: What the caller had open in their client when they wrote the message, such as datasets or
                files. Lets the AI resolve references like "this dataset". ``None`` sends none.
            client_tools: Client tools the AI may call from this turn on, registered on this instance as the class's
                ``client_tools`` argument describes. A non-empty list replaces the thread's client tools; ``None`` or
                an empty list leaves them unchanged.
            analysis_scope: Analysis scope that replaces the thread's own, from this turn on. ``None`` leaves the
                thread's scope unchanged.
            goals: Goals the AI must meet in this turn, as for ``send``. ``None`` declares none.

        Returns:
            This instance, with the message appended to ``messages``.

        Examples:
            Ask a question and print the AI's reply as it writes it:

            >>> from roboto.ai.agent_thread import AgentTextDeltaEvent
            >>> thread.send_text("Which topics have GPS data?")
            >>> for event in thread.events():
            ...     if isinstance(event, AgentTextDeltaEvent):
            ...         print(event.text, end="", flush=True)
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
        """Submit the results of client tool calls, starting the AI's next turn.

        Use it when ``events`` returns with the thread's status at
        :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.CLIENT_TOOL_TURN`; ``run`` calls it for you. Once Roboto
        accepts the results, this instance's ``status`` is ``ROBOTO_TURN``.

        Args:
            results: Results of the client tool calls the AI is waiting on.
            client_tools: Client tools the AI may call from the next turn on, registered on this instance as the
                class's ``client_tools`` argument describes. A list replaces the thread's client tools, and an empty
                list removes them. ``None`` leaves them unchanged.

        Returns:
            This instance, with its status set to ``ROBOTO_TURN``.

        Raises:
            RobotoClientToolResultsNotPendingException: The thread no longer waits on these results. Its ``reason`` is
                ``answered_elsewhere`` when another submission answered the same calls first, or ``turn_ended`` when the
                turn was stopped or expired before any submission answered them.
            RobotoInvalidRequestException: The results do not answer exactly the client tool calls the thread waits
                on.
            RobotoThreadReadOnlyException: The thread's origin is a surface outside Roboto, such as Slack.

        Examples:
            Answer the AI's calls to a client tool yourself:

            >>> from roboto.ai.agent_thread import AgentToolUseEvent, ClientToolResult, ClientToolResultStatus
            >>> calls = [e for e in thread.events() if isinstance(e, AgentToolUseEvent) and e.name == "client_remember"]
            >>> thread.submit_client_tool_results(
            ...     [
            ...         ClientToolResult(
            ...             tool_use_id=call.tool_use_id,
            ...             tool_name=call.name,
            ...             runtime_ms=0,
            ...             status=ClientToolResultStatus.SUCCESS,
            ...             output={"result": "stored"},
            ...         )
            ...         for call in calls
            ...     ]
            ... )
        """
        specs = _extract_specs(client_tools)
        request = SubmitToolResultsRequest(
            tool_results=list(results),
            client_tools=specs,
        )
        self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/tool-results",
            caller_org_id=self.__record.org_id,
            data=request,
        )
        self.__register_tools(client_tools)
        # Set the status here because the next delta may not report it. Roboto can append these results to a ROBOTO
        # message this instance's continuation token has already passed, so that delta can come back empty with
        # status None. With CLIENT_TOOL_TURN kept, run would run the same tools again and submit their results a
        # second time, which Roboto rejects with RobotoInvalidRequestException because the status is ROBOTO_TURN.
        self.__record.status = AgentThreadStatus.ROBOTO_TURN
        return self

    def set_visibility(self, visibility: ThreadVisibility) -> AgentThread:
        """Set who can read this thread.

        Only the thread's creator may call this. Roboto administrators can read every thread but cannot change the
        visibility of one they did not create. Setting the visibility the thread already has changes nothing.

        Args:
            visibility: :py:attr:`~roboto.ai.agent_thread.ThreadVisibility.ORG` to let every member of the thread's
                organization read it, or ``PRIVATE`` to limit it to its creator.

        Returns:
            This instance, with ``visibility`` updated.

        Raises:
            RobotoUnauthorizedException: The caller did not create the thread.

        Examples:
            Share the thread with your organization:

            >>> from roboto.ai.agent_thread import ThreadVisibility
            >>> thread.set_visibility(ThreadVisibility.ORG)
        """
        self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/visibility",
            caller_org_id=self.__record.org_id,
            data=UpdateThreadVisibilityRequest(visibility=visibility),
        )
        self.__record.visibility = visibility
        return self

    def set_pinned(self, pinned: bool) -> AgentThread:
        """Pin or unpin this thread for the caller.

        A pin is a personal bookmark: it puts the thread at the top of the caller's threads in the Roboto web app, and
        no one else sees it. Anyone who can read the thread can pin it, including members of its organization when its
        visibility is ``ORG``. Setting the state the thread already has changes nothing; pinning a pinned thread does
        not move it back to the top of the pinned threads.

        Args:
            pinned: ``True`` to pin, ``False`` to unpin.

        Returns:
            This instance. Its record keeps its
            :py:attr:`~roboto.ai.agent_thread.AgentThreadRecord.pinned_at`, which a read of one thread never reports.

        Examples:
            Pin the thread:

            >>> thread.set_pinned(True)

            Unpin it again:

            >>> thread.set_pinned(False)
        """
        self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/pin",
            caller_org_id=self.__record.org_id,
            data=PinThreadRequest(pinned=pinned),
        )
        return self

    def invoke_skill(self, skill_id: str, version: Optional[int] = None) -> AgentThread:
        """Apply a skill in a new turn of this thread, with no message.

        Calls ``send`` with one ``invoke_skills`` entry, so the failures of ``send`` apply.

        Args:
            skill_id: ID of the skill to apply.
            version: Number of the skill version to apply. ``None`` applies the skill's latest version.

        Returns:
            This instance.

        Examples:
            Apply a skill's latest version:

            >>> thread.invoke_skill("sk_12345")

            Apply version 2 of the skill:

            >>> thread.invoke_skill("sk_12345", version=2)
        """
        return self.send(invoke_skills=[InvokeSkillSpec(skill_id=skill_id, version=version)])

    def events(
        self,
        tick: float = 0.2,
        timeout: Optional[float] = None,
    ) -> collections.abc.Generator[AgentEvent, None, None]:
        """Yield events for the thread's new content as the AI writes it, until the turn needs the caller.

        Polls Roboto every ``tick`` seconds and returns once the thread's status is anything other than
        :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.ROBOTO_TURN`. It runs no client tools: when it returns
        with the status ``CLIENT_TOOL_TURN``, submit the results with ``submit_client_tool_results`` and call
        ``events`` again, or use ``run``, which does both.

        Each stretch of text in a message is yielded as an :py:class:`~roboto.ai.agent_thread.AgentStartTextEvent`,
        then :py:class:`~roboto.ai.agent_thread.AgentTextDeltaEvent` events, then an
        :py:class:`~roboto.ai.agent_thread.AgentTextEndEvent` once the message's generation ends or a block other than
        text follows. Messages from the caller yield no events.

        Args:
            tick: Seconds between polls.
            timeout: Seconds to keep polling while the AI is generating. ``None`` polls until the turn needs the
                caller.

        Yields:
            Events for the thread's new content, in order: text events, tool uses and their results
            (:py:class:`~roboto.ai.agent_thread.AgentToolUseEvent`,
            :py:class:`~roboto.ai.agent_thread.AgentToolResultEvent`), and errors
            (:py:class:`~roboto.ai.agent_thread.AgentErrorEvent`).

        Raises:
            TimeoutError: ``timeout`` seconds pass while the thread's status is still ``ROBOTO_TURN``. It surfaces
                during iteration, when the first poll after that time still finds the status ``ROBOTO_TURN``.

        Examples:
            Print the AI's text as it writes it:

            >>> from roboto.ai.agent_thread import AgentTextDeltaEvent
            >>> for event in thread.events():
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

                # delta_message holds only the content blocks new in this delta, which __get_delta_and_update has
                # already appended to the message this instance holds.
                for content in delta_message.content:
                    if isinstance(content, AgentTextContent):
                        if idx not in self.__open_text_idxs:
                            yield AgentStartTextEvent()
                            self.__open_text_idxs.add(idx)
                        yield AgentTextDeltaEvent(text=content.text)
                    else:
                        # A block other than text ends the message's open text span.
                        if idx in self.__open_text_idxs:
                            yield AgentTextEndEvent()
                            self.__open_text_idxs.discard(idx)

                        if isinstance(content, AgentToolUseContent):
                            yield AgentToolUseEvent(
                                name=content.tool_name,
                                tool_use_id=content.tool_use_id,
                                input=content.input,
                                answered_by_server=content.answered_by_server,
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

                # End an open text span only once the message's generation has ended, so text a later poll brings for
                # a message still generating continues the same span.
                if idx in self.__open_text_idxs and self.__record.messages[idx].status.is_terminal():
                    yield AgentTextEndEvent()
                    self.__open_text_idxs.discard(idx)

            # More changes follow this delta, yet its status describes the whole thread. Fetch them before acting on
            # the status, without sleeping, so every event of a finished turn is yielded before returning.
            if delta.has_more:
                continue

            if self.__record.status != AgentThreadStatus.ROBOTO_TURN:
                return

            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for agent to finish generating")
            # Sleeping after the status check makes the first poll immediate, so a thread already waiting on the
            # caller returns without delay.
            time.sleep(tick)

    def run(
        self,
        *,
        on_event: Optional[OnEvent] = None,
        tick: float = 0.2,
        timeout: Optional[float] = None,
    ) -> AgentThread:
        """Drive the thread until it is the caller's turn, running client tools as the AI calls them.

        Calls ``events`` and passes each event to ``on_event``. Whenever the thread waits on client tools, ``run`` calls
        the function registered on this instance for each unanswered call, and submits the results with
        ``submit_client_tool_results``:

        - A function's return value becomes the result's output: a dictionary as it is, ``None`` as an empty
          dictionary, and any other value under the key ``"result"``.
        - A function that raises an ``Exception`` gives an error result holding the exception's type and message.
        - A call to a client tool (a name with the ``client_`` prefix) with no registered function gives an error
          result saying so, which the AI can recover from.
        - A call Roboto answers itself
          (:py:attr:`~roboto.ai.agent_thread.AgentToolUseContent.answered_by_server`), or a call to a server tool (a
          name without the ``client_`` prefix), is left unanswered. When only such calls remain, ``run`` polls again
          after ``tick`` seconds.

        Returns once the thread's status is :py:attr:`~roboto.ai.agent_thread.AgentThreadStatus.USER_TURN`.

        Args:
            on_event: Function called with each event ``events`` yields, such as for progress display or logging.
                ``None`` calls nothing.
            tick: Seconds between polls.
            timeout: Seconds the whole call may take. ``None`` waits indefinitely.

        Returns:
            This instance, with its record updated from Roboto's responses.

        Raises:
            TimeoutError: ``timeout`` seconds pass before the thread's status is ``USER_TURN``.
            RobotoAgentGoalsFailedException: The AI used up its retries without achieving every goal declared for the
                turn.
            RobotoClientToolResultsNotPendingException: The thread stopped waiting on the results before ``run``
                submitted them, such as when another client answered the calls first.
            RuntimeError: The thread stops in a status other than ``USER_TURN``, ``CLIENT_TOOL_TURN`` or
                ``GOALS_FAILED``, or waits on client tools while it has no messages or its latest message is neither
                from the AI nor a ``ROBOTO`` message right after one from the AI.

        Examples:
            Run a thread with a client tool until it is your turn:

            >>> from roboto.ai import client_tool
            >>> @client_tool
            ... def client_remember(fact: str) -> str:
            ...     \"\"\"Store a fact in long-term memory.\"\"\"
            ...     ...
            >>> thread = AgentThread.start("Remember my favorite color is blue.", client_tools=[client_remember])
            >>> thread.run()

            Print each tool call as the AI makes it:

            >>> from roboto.ai.agent_thread import AgentToolUseEvent
            >>> def log(event):
            ...     if isinstance(event, AgentToolUseEvent):
            ...         print(f"[tool-use] {event.name}({event.input})")
            >>> thread.run(on_event=log)
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
                if len(results) > 0:
                    self.submit_client_tool_results(results)
                else:
                    # Roboto answers every unanswered tool use. events returns after one poll while the status is
                    # CLIENT_TOOL_TURN, so wait here between polls.
                    time.sleep(tick)
                continue

            if status == AgentThreadStatus.GOALS_FAILED:
                raise RobotoAgentGoalsFailedException(self.thread_id)

            raise RuntimeError(
                f"Session {self.thread_id} paused in unexpected status {status}; "
                "expected USER_TURN or CLIENT_TOOL_TURN."
            )

    def __get_delta_and_update(self) -> AgentThreadDelta:
        delta = self.__roboto_client.get(
            f"v1/ai/threads/{self.__record.thread_id}/delta",
            caller_org_id=self.__record.org_id,
            query={"next_token": self.__record.continuation_token, "paged": True},
        ).to_record(AgentThreadDelta)

        self.__record.continuation_token = delta.continuation_token
        self.__record.has_more = delta.has_more

        # Discard before merging. Roboto sets reset_from_message_sequence_num when it regenerated a turn onto the
        # same index, and the merge below appends to the message held there, which would join the new reply onto
        # text from the abandoned attempt.
        if delta.reset_from_message_sequence_num is not None:
            del self.__record.messages[delta.reset_from_message_sequence_num :]

        for idx in sorted(delta.messages_by_idx.keys()):
            if idx < len(self.__record.messages):
                self.__record.messages[idx].status = delta.messages_by_idx[idx].status
                self.__record.messages[idx].content.extend(delta.messages_by_idx[idx].content)
            else:
                self.__record.messages.append(delta.messages_by_idx[idx])

        if delta.status is not None:
            self.__record.status = delta.status
            # Sent with every status and authoritative then, None included.
            self.__record.client_tool_executor_tab_id = delta.client_tool_executor_tab_id

        # Copied even when None, unlike status and title: every delta carries the current activity, and None means
        # there is none.
        self.__record.activity = delta.activity
        # Copied even when None, like activity: None means there is nothing to report.
        self.__record.turn_notice = delta.turn_notice

        if delta.title is not None:
            self.__record.title = delta.title

        # goals and tasks arrive as whole lists: None means unchanged, and any list, even an empty one, replaces the
        # one held.
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
            # A ClientToolSpec is declared to the AI but has no function here.
            if isinstance(tool, ClientTool):
                self.__client_tools[tool.name] = tool

    def __dispatch_pending_client_tools(self) -> list[ClientToolResult]:
        """Run the registered function for each client tool use the thread waits on, and return the results.

        Roboto sets the status to ``CLIENT_TOOL_TURN`` in two cases:

        1. The latest message is an assistant message ending in a client tool use. Every unanswered tool use is on
           ``messages[-1]``.
        2. The latest message is a ``ROBOTO`` message holding the results of server tool uses, and the assistant
           message before it also called client tools whose results are outstanding. The unanswered tool uses are on
           ``messages[-2]``, and the results written so far on ``messages[-1]``.

        Reading only the latest message would miss case 2: ``run`` would submit nothing and wait, until its timeout,
        for results only it can submit.

        Raises:
            RuntimeError: The thread has no messages, or neither case applies.
        """
        messages = self.__record.messages
        if len(messages) == 0:
            raise RuntimeError("Session is in CLIENT_TOOL_TURN but has no messages.")

        latest = messages[-1]
        # Case 1.
        if latest.role == AgentRole.ASSISTANT:
            tool_uses = [c for c in latest.content if isinstance(c, AgentToolUseContent)]
            answered_ids: set[str] = set()
        # Case 2.
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
            # Roboto writes the result of a tool use it answers itself, which may not have reached this copy of the
            # thread yet.
            if tool_use.tool_use_id in answered_ids or tool_use.answered_by_server:
                continue
            # Answer every tool use whose name has the client_ prefix, the rule Roboto applies: it accepts a
            # submission only when it answers all of them, so a client tool this instance never declared gets an
            # error result rather than none. In case 2, messages[-2] can also hold server tool uses whose results
            # Roboto has not yet written to messages[-1], and answering one would give it two results.
            if not tool_use.tool_name.startswith(CLIENT_TOOL_NAME_PREFIX):
                continue
            results.append(self.__execute_single_client_tool(tool_use))
        return results

    def __execute_single_client_tool(self, tool_use: AgentToolUseContent) -> ClientToolResult:
        tool_name = tool_use.tool_name
        # Deep-copy so a function that changes nested values in its input cannot change this instance's copy of the
        # message.
        tool_input = copy.deepcopy(tool_use.input) if tool_use.input else {}
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
        # Any Exception from the function becomes an error result the AI reads; a BaseException such as
        # KeyboardInterrupt propagates.
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
        """Submit feedback on one of the AI's messages in this thread, for Roboto to review.

        Roboto keeps one piece of feedback per user and message. Submitting again replaces its ``sentiment``,
        ``categories`` and ``notes``, and keeps its ID and its ``created`` and ``created_by``.

        Args:
            message_sequence_num: Index of the message in ``messages``. It must be a message from the AI whose
                generation completed.
            sentiment: Whether the feedback is positive or negative.
            categories: Categories describing the feedback, each valid for ``sentiment`` as
                :py:func:`~roboto.ai.agent_thread.category_is_valid_for_sentiment` decides.
                :py:attr:`~roboto.ai.agent_thread.FeedbackCategory.OTHER` is valid for either sentiment and requires
                ``notes``. ``None`` sets none.
            notes: Free-text notes. Required when ``categories`` includes ``OTHER``; notes of only whitespace count as
                none.

        Returns:
            The feedback, as Roboto stored it.

        Raises:
            pydantic.ValidationError: A category is not valid for ``sentiment``, or ``categories`` includes ``OTHER``
                without ``notes``.
            RobotoNotFoundException: ``message_sequence_num`` matches no message in the thread.
            RobotoInvalidRequestException: The message is not from the AI, or its generation has not completed.

        Examples:
            Rate a reply as incomplete:

            >>> from roboto.ai.agent_thread import FeedbackCategory, FeedbackSentiment
            >>> thread.submit_feedback(
            ...     message_sequence_num=1,
            ...     sentiment=FeedbackSentiment.NEGATIVE,
            ...     categories=[FeedbackCategory.INCOMPLETE],
            ... )
        """
        request = SubmitFeedbackRequest(
            sentiment=sentiment,
            categories=categories if categories is not None else [],
            notes=notes,
        )
        return self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/messages/{message_sequence_num}/feedback",
            caller_org_id=self.__record.org_id,
            data=request,
        ).to_record(UserFeedbackRecord)

    def fork(self, message_sequence_num: int) -> AgentThread:
        """Create a thread owned by the caller that holds this thread's messages up to a given one.

        Anyone who can read this thread can fork it. The fork belongs to this thread's organization, so the AI's tools
        reach that organization's data. It is :py:attr:`~roboto.ai.agent_thread.ThreadVisibility.PRIVATE` whatever
        this thread's visibility, and it accepts new messages even when this thread does not.

        Args:
            message_sequence_num: Index of the last message to copy into the new thread; every earlier message is
                copied too.

        Returns:
            The new thread.

        Raises:
            RobotoInvalidRequestException: ``message_sequence_num`` matches no message, or matches one whose
                generation did not complete.

        Examples:
            Continue the conversation from its second message in a new thread:

            >>> fork = thread.fork(message_sequence_num=1)
            >>> fork.send_text("Try again with a narrower time range.")
        """
        request = ForkAgentThreadRequest(message_sequence_num=message_sequence_num)
        record = self.__roboto_client.post(
            f"v1/ai/threads/{self.__record.thread_id}/fork",
            caller_org_id=self.__record.org_id,
            data=request,
        ).to_record(AgentThreadRecord)
        return AgentThread(record=record, roboto_client=self.__roboto_client)


def _extract_specs(
    tools: Optional[collections.abc.Sequence[Union[ClientTool, ClientToolSpec]]],
) -> Optional[list[ClientToolSpec]]:
    if tools is None:
        return None
    return [tool.spec if isinstance(tool, ClientTool) else tool for tool in tools]
