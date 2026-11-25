# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import re
from typing import Any, Optional

import pydantic

from ...compat import StrEnum
from ...time import utcnow
from ..goals import AgentGoal, AgentGoalStatus

# The message content types are defined in content so that goals can import them without importing this module,
# which imports goals. They are re-exported here, and listed in __all__, so they also import from
# roboto.ai.core.record.
from .content import (
    AGENT_CONTENT_MODEL_BY_TYPE,
    AgentClientContextEntry,
    AgentCompressionFillerContent,
    AgentContent,
    AgentContentType,
    AgentDeletedContent,
    AgentErrorContent,
    AgentTextContent,
    AgentToolResultContent,
    AgentToolUseContent,
)

# Re-exported here, and listed in __all__, so the task types import from roboto.ai.core.record with the rest of the
# thread types.
from .task import (
    AgentSubtask,
    AgentSubtaskStatus,
    AgentTask,
    AgentTaskBoundary,
    AgentTaskMinimal,
    AgentTaskStatus,
)


class ThreadOrigin(StrEnum):
    """Origin of a thread: the surface it was started from, which owns it.

    The origin decides whether the thread accepts new messages over the API. It differs from
    ``AgentThreadRecord.created_by_principal``, which records who started the thread. Import it from
    ``roboto.ai.agent_thread``.
    """

    API = "api"
    """Roboto itself: the Roboto web app, the CLI, the SDK, or a direct REST request.

    These surfaces read the thread back from Roboto and keep no copy elsewhere, so the thread accepts new messages.
    """

    SLACK = "slack"
    """Slack, where a user started the thread by mentioning @Roboto, and where Roboto mirrors the conversation."""


class ThreadVisibility(StrEnum):
    """Visibility of a thread: who can read it.

    Set when the thread is created. Only the thread's creator can change it, with
    :py:meth:`~roboto.ai.agent_thread.AgentThread.set_visibility`. Roboto administrators can read every thread but
    cannot change the visibility of one they did not create. Import it from ``roboto.ai.agent_thread``.
    """

    PRIVATE = "private"
    """Only the thread's creator and Roboto administrators can read the thread.

    Default for threads started with :py:meth:`~roboto.ai.agent_thread.AgentThread.start`, so a thread is not shared
    with the organization until its creator chooses to share it. Every fork is ``PRIVATE``, whatever the visibility
    of the thread it was forked from.
    """

    ORG = "org"
    """Every member of the thread's organization, and Roboto administrators, can read the thread.

    Default for threads started by :py:meth:`~roboto.ai.agent.Agent.launch`, since agents exist to share work across
    an organization.
    """


CLIENT_TOOL_NAME_PREFIX = "client_"
"""Prefix every client tool's name must start with.

Roboto tells client tools from its own tools by this prefix. Tool names may contain only letters, digits, and
underscores, so the prefix ends in an underscore. The full name must match ``^client_[a-z][a-z0-9_]*$``.
"""

_CLIENT_TOOL_NAME_RE = re.compile(r"^client_[a-z][a-z0-9_]*$")
"""Regular expression a ``ClientToolSpec`` name must match in full."""


class ModelProfileResponse(pydantic.BaseModel):
    """Item of the response body of ``GET /v1/ai/model-profiles``: a model profile the organization can pick.

    A model profile names the AI model a thread runs on.
    """

    id: str
    """ID of the model profile, such as ``standard`` or ``advanced``."""

    label: str
    """Human-readable name of the model profile."""

    description: str
    """Human-readable description of the model profile."""

    is_default: bool = False
    """Whether a new thread runs on this model profile when it requests none."""


class AgentRole(StrEnum):
    """Role of a message's sender in a thread."""

    USER = "user"
    """Caller, a person or program, sending messages to Roboto's AI."""

    ASSISTANT = "assistant"
    """Roboto's AI, responding to the caller."""

    ROBOTO = "roboto"
    """Roboto itself, sending tool results and system information."""


class AgentMessageStatus(StrEnum):
    """Status of a message's generation."""

    NOT_STARTED = "not_started"
    """Generation has not begun."""

    GENERATING = "generating"
    """Generation is in progress."""

    COMPLETED = "completed"
    """Generation finished, and the message's content is complete."""

    FAILED = "failed"
    """Generation failed with an error."""

    CANCELLED = "cancelled"
    """Generation was cancelled before it finished."""

    def is_terminal(self) -> bool:
        """Return whether generation has ended: ``COMPLETED``, ``FAILED``, or ``CANCELLED``."""
        return self in (
            AgentMessageStatus.COMPLETED,
            AgentMessageStatus.FAILED,
            AgentMessageStatus.CANCELLED,
        )


class AgentThreadStatus(StrEnum):
    """Status of a thread: whose turn it is, or why the thread stopped."""

    NOT_STARTED = "not_started"
    """The thread exists, but no message has been sent to it."""

    USER_TURN = "user_turn"
    """Waiting for the caller's next message."""

    ROBOTO_TURN = "roboto_turn"
    """Roboto's AI is generating a response."""

    CLIENT_TOOL_TURN = "client_tool_turn"
    """Waiting for the caller to run the client tools the AI requested and submit their results."""

    GOALS_FAILED = "goals_failed"
    """The AI used up its retries for the latest turn without achieving every goal declared for it.

    The thread needs a person to act before it can continue.
    """


class ClientToolSpec(pydantic.BaseModel):
    """Specification of a client tool: a tool Roboto's AI can ask the caller to run, whose result the caller submits.

    Carried in the ``client_tools`` field of :py:class:`~roboto.ai.agent_thread.StartAgentThreadRequest`,
    :py:class:`~roboto.ai.agent_thread.SendMessageRequest`, and
    :py:class:`~roboto.ai.agent_thread.SubmitToolResultsRequest`. Roboto offers the tool to the AI but never runs it.
    :py:class:`~roboto.ai.agent_thread.ClientTool` pairs a specification with a function that
    :py:meth:`~roboto.ai.agent_thread.AgentThread.run` calls for you; for a bare specification, submit the results
    yourself with :py:meth:`~roboto.ai.agent_thread.AgentThread.submit_client_tool_results`.

    Building a specification raises ``pydantic.ValidationError`` when ``name`` does not match
    ``^client_[a-z][a-z0-9_]*$``.
    """

    name: str
    """Name of the tool, which the AI uses to request it.

    Starts with ``CLIENT_TOOL_NAME_PREFIX``, followed by a lowercase letter and then
    lowercase letters, digits, and underscores.
    """

    description: str
    """Human-readable description of what the tool does, which the AI reads to decide when to use it."""

    input_schema: dict[str, Any]
    """JSON Schema of the tool's input."""

    @pydantic.field_validator("name")
    @classmethod
    def _validate_client_prefix(cls, v: str) -> str:
        # Roboto runs this check when it reads a request too, so it rejects a bad name with HTTP 400 before it
        # stores anything about the thread. Roboto tells client tools from its own tools by the prefix, so a name
        # without it could collide with one of Roboto's tools.
        if not _CLIENT_TOOL_NAME_RE.fullmatch(v):
            raise ValueError(
                f"client tool name {v!r} must match {_CLIENT_TOOL_NAME_RE.pattern} "
                f"(start with {CLIENT_TOOL_NAME_PREFIX!r}, then lowercase letters, "
                f"digits, and underscores)"
            )
        return v


class AgentMessage(pydantic.BaseModel):
    """Message in a thread from one sender, made of content blocks such as text, tool uses, and tool results.

    Carried in ``AgentThreadRecord.messages``.
    """

    role: AgentRole
    """Role of the message's sender."""

    content: list[AgentContent]
    """Content blocks of the message, in order."""

    status: AgentMessageStatus = AgentMessageStatus.NOT_STARTED
    """Status of the message's generation."""

    created: datetime.datetime = pydantic.Field(default_factory=utcnow)
    """Time the message was created."""

    created_by: Optional[str] = None
    """ID of the user who sent the message.

    Roboto sets it on user messages a person sent, so a thread shared with an organization shows which member asked
    what. ``None`` on assistant and Roboto messages, on messages an agent launch, trigger, or Slack mention wrote, and
    on messages sent before Roboto stored it. A fork keeps the authors of the messages it copied. Roboto ignores this
    field on messages a caller sends, and records the caller instead.
    """

    @classmethod
    def text(cls, text: str, role: AgentRole = AgentRole.USER) -> "AgentMessage":
        """Build a message holding only ``text``.

        Args:
            text: Text of the message.
            role: Role of the message's sender. Defaults to ``USER``.
        """
        return cls(role=role, content=[AgentTextContent(text=text)])

    def __str__(self) -> str:
        combined_content = "".join(str(content) for content in self.content)
        return f"== {self.role.value.upper()} ==\n{combined_content}"

    def is_complete(self) -> bool:
        """Return whether generation of the message is complete."""
        return self.status == AgentMessageStatus.COMPLETED

    def is_unsuccessful(self) -> bool:
        """Return whether generation of the message failed or was cancelled.

        Always ``False`` for a message with role ``USER``.
        """
        return self.role != AgentRole.USER and self.status in (
            AgentMessageStatus.FAILED,
            AgentMessageStatus.CANCELLED,
        )


class AgentThreadGoalRecord(pydantic.BaseModel):
    """Data record of a goal declared on a turn of a thread, as the Roboto API returns it.

    A goal is a structured outcome attached to a turn of a thread, which Roboto's AI must achieve before the turn
    completes. Carried in ``AgentThreadRecord.goals``.
    :py:class:`~roboto.ai.agent_thread.AgentThreadGoalView` wraps this record, and
    :py:attr:`~roboto.ai.agent_thread.AgentThread.goals` returns those wrappers.
    """

    goal_type: str
    """Kind of goal, such as ``"dataset_summary"``, which selects the model ``goal_data`` follows."""

    goal_data: dict[str, Any]
    """:py:const:`~roboto.ai.goals.AgentGoal` as a JSON-compatible dictionary.

    ``to_agent_goal`` builds the typed goal from it.
    """

    status: AgentGoalStatus
    """Status of the goal."""

    message_sequence_num: int
    """Index, in the thread's ``messages``, of the user message that declared the goal."""

    created: datetime.datetime
    """Time the goal was declared."""

    concluded_at: Optional[datetime.datetime] = None
    """Time the goal was achieved or failed, or ``None`` while it is pending."""

    achieve_tool_use_id: Optional[str] = None
    """ID of the tool use in which the AI submitted the goal's result, through the tool Roboto gives it for that goal.

    It locates the matching :py:class:`~roboto.ai.agent_thread.AgentToolUseContent` and
    :py:class:`~roboto.ai.agent_thread.AgentToolResultContent` in the thread's messages without searching by tool
    name. Roboto records each attempt, so its value depends on the goal's ``status``, a
    :py:class:`~roboto.ai.goals.AgentGoalStatus`:

    - ``ACHIEVED``: the successful attempt.
    - ``FAILED``: the last attempt, or ``None`` if the AI never attempted it before running out of retries.
    - ``PENDING``: ``None``, or the latest attempt so far.

    :py:attr:`~roboto.ai.agent_thread.AgentThreadGoalView.result` reads the submitted result from that tool use.
    """

    def to_agent_goal(self) -> AgentGoal:
        """Build the typed goal from ``goal_data``.

        Returns:
            The goal as the :py:const:`~roboto.ai.goals.AgentGoal` member ``goal_type`` selects, such as
            :py:class:`~roboto.ai.goals.DatasetSummaryAgentGoal` for ``"dataset_summary"`` or
            :py:class:`~roboto.ai.goals.DatasetTriageGoal` for ``"dataset_triage"``.
        """
        return pydantic.TypeAdapter(AgentGoal).validate_python(self.goal_data)


class AgentThreadRecord(pydantic.BaseModel):
    """Data record of a thread, as the Roboto API returns it.

    A thread is a persistent, multi-turn conversation with Roboto's AI. :py:class:`~roboto.ai.agent_thread.AgentThread`
    wraps this record with methods that act on the thread, and
    :py:meth:`~roboto.ai.agent_thread.AgentThread.from_id` fetches it.
    """

    # model_profile starts with pydantic's reserved model_ prefix, which makes pydantic before 2.10 warn on import,
    # and the SDK supports pydantic 2.5 and later. Clearing the protected namespaces silences the warning.
    model_config = pydantic.ConfigDict(protected_namespaces=())

    thread_id: str = pydantic.Field(
        validation_alias=pydantic.AliasChoices("thread_id", "session_id", "chat_id"),
    )
    """Unique ID of the thread.

    Also accepted under the key ``session_id`` or ``chat_id``.
    """

    created: datetime.datetime
    """Time the thread was created."""

    created_by: str
    """ID of the user who created the thread."""

    created_by_principal: Optional[str] = None
    """Principal that started the thread, as ``<type>:<id>``.

    For example, ``user:<user_id>`` or ``invocation:<invocation_id>``. Unlike ``created_by``, it records whether a
    person, a device, or an action invocation started the thread. ``None`` on forks and on threads started before
    Roboto stored it.
    """

    org_id: str
    """ID of the organization that owns the thread."""

    messages: list[AgentMessage] = pydantic.Field(default_factory=list)
    """Messages in the thread, oldest first.

    Empty when the thread was fetched with ``load_messages=False``, as
    :py:meth:`~roboto.ai.agent_thread.AgentThread.from_id` allows.
    """

    continuation_token: str
    """Token marking how much of the thread this record holds.

    Pass it as ``next_token`` to ``GET /v1/ai/threads/{thread_id}/delta`` to fetch what changed since.
    """

    has_more: bool = False
    """Whether Roboto left the thread's later messages out of ``messages`` to keep the response small.

    ``True`` only in a response to a request sent with ``paged=true``. To fetch the messages left out, request
    ``GET /v1/ai/threads/{thread_id}/delta`` with ``paged=true``, passing ``continuation_token`` as ``next_token``,
    and repeat with each delta's token until a delta reports ``has_more`` as ``False``.
    :py:meth:`~roboto.ai.agent_thread.AgentThread.from_id` does this, so a thread it returns holds every message.
    """

    status: AgentThreadStatus
    """Status of the thread: whose turn it is, or why the thread stopped."""

    activity: Optional[str] = None
    """Sentence for display saying what Roboto's AI is doing that the thread's messages do not show yet.

    ``None`` when there is no such activity. While Roboto summarizes the thread's older messages so the conversation
    fits the AI model's context window, it is "Summarizing older messages to fit the model's context window". While a
    tool runs and reports its progress, it is that tool's latest report, such as "Starting the Python sandbox".
    """

    title: Optional[str] = None
    """Title of the thread, or ``None`` if it has none."""

    model_profile: Optional[str] = None
    """ID of the model profile the thread runs on, such as ``standard`` or ``advanced``."""

    forked_from_thread_id: Optional[str] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("forked_from_thread_id", "forked_from_session_id"),
    )
    """ID of the thread this thread was forked from, or ``None`` if it is not a fork.

    Also accepted under the key ``forked_from_session_id``.
    """

    forked_from_message_sequence_num: Optional[int] = None
    """Index of the last message the fork copied from the source thread, or ``None`` if the thread is not a fork."""

    visibility: ThreadVisibility = ThreadVisibility.PRIVATE
    """Visibility of the thread: who can read it."""

    created_from_agent_id: Optional[str] = None
    """ID of the agent whose launch started the thread, or ``None`` if no agent launch started it.

    A fork does not inherit it.
    """

    created_from_trigger_id: Optional[str] = None
    """ID of the trigger that started the thread, or ``None`` if no trigger started it.

    The trigger started the thread through its :py:attr:`~roboto.domain.triggers.TriggerTargetType.StartAgent`
    target. It is ``None`` when a person launched the same agent. When it is set, ``created_from_agent_id`` names
    the agent the trigger launched. A fork does not inherit it.
    """

    origin: Optional[ThreadOrigin] = None
    """Origin of the thread: the surface it was started from, which owns it.

    Roboto sets it; no request does. When the origin is a surface outside Roboto, such as ``ThreadOrigin.SLACK``,
    Roboto refuses new messages to the thread over the API
    with :py:class:`~roboto.exceptions.RobotoThreadReadOnlyException`; reading, cancelling, and rating the thread
    still work. A fork does not inherit the origin, so a fork accepts new messages. ``None`` on forks and on threads
    started before Roboto stored it, and means the same as ``API``.
    """

    pinned_at: Optional[datetime.datetime] = None
    """Time the calling user pinned the thread, or ``None`` if they have not.

    A pin is a personal bookmark, so two users reading the same thread see different values. Pin and unpin with
    :py:meth:`~roboto.ai.agent_thread.AgentThread.set_pinned`. Only ``GET /v1/ai/threads`` and
    ``POST /v1/ai/threads/search`` report it; a read of a single thread leaves it ``None`` whatever the pin state.
    """

    goals: Optional[list[AgentThreadGoalRecord]] = None
    """Goals declared across the thread's turns, ordered by the turn that declared them.

    ``None`` when the record was returned without its goals; an empty list when the thread declared none.
    """

    tasks: Optional[list[AgentTask]] = None
    """Task list of the thread, ordered by :py:attr:`~roboto.ai.agent_thread.AgentTask.position`.

    ``None`` when the record was returned without its tasks; an empty list when the thread has none.
    """

    client_tool_executor_tab_id: Optional[str] = None
    """Opaque id of the browser tab that sent the latest turn's user message.

    That tab is the only one that runs the turn's client-side tools. ``None`` when the message
    came from a caller that does not identify its tab, such as the SDK; any client may then run
    them."""

    turn_notice: Optional[str] = None
    """Short, human-readable note about the turn in progress.

    For example, that the turn stopped unexpectedly and Roboto is retrying it. ``None`` when there is nothing to
    report, and always ``None`` unless ``status`` is ``ROBOTO_TURN``. Roboto computes it on each read of a single
    thread and each delta, and does not store it with the thread.
    """


class AgentThreadDelta(pydantic.BaseModel):
    """Response body of ``GET /v1/ai/threads/{thread_id}/delta``: a thread's changes since a continuation token.

    Read by :py:meth:`~roboto.ai.agent_thread.AgentThread.refresh` and
    :py:meth:`~roboto.ai.agent_thread.AgentThread.events`, which merge it into the thread they hold.
    """

    messages_by_idx: dict[int, AgentMessage]
    """Messages that are new or changed since the token, keyed by index in the thread's ``messages``.

    At an index the client already holds, the message carries only the content blocks the client has not seen; the
    client appends them to the message it holds and takes the new ``status``.
    """

    continuation_token: str
    """Token to pass as ``next_token`` on the next request for a delta."""

    reset_from_message_sequence_num: Optional[int] = None
    """Index from which the client discards the messages it holds before applying this delta.

    ``None`` means the client discards nothing. Roboto sets it when a turn stopped partway and Roboto regenerated it.
    The replacement message reuses the same index, so appending to the message the client holds there would join the
    reply onto text from the abandoned attempt. When it is set, the client:

    1. Drops the messages it holds at this index and after.
    2. Applies ``messages_by_idx`` and adopts ``continuation_token``.
    """

    status: Optional[AgentThreadStatus] = None
    """New status of the thread, or ``None`` if it has not changed."""

    activity: Optional[str] = None
    """The thread's ``AgentThreadRecord.activity`` as of this delta.

    Unlike ``status``, ``title``, ``goals`` and ``tasks``, ``None`` does not mean unchanged: every delta carries the
    thread's current activity, so ``None`` means there is none. A client replaces the activity it holds with this
    value on every delta.
    """

    client_tool_executor_tab_id: Optional[str] = None
    """The thread's :py:attr:`AgentThreadRecord.client_tool_executor_tab_id` as of this delta.

    Sent whenever :attr:`status` is, and then authoritative: ``None`` alongside a status means the
    turn names no tab. When :attr:`status` is ``None``, clients should retain the value they
    already hold."""

    title: Optional[str] = None
    """New title of the thread, or ``None`` if it has not changed."""

    goals: Optional[list[AgentThreadGoalRecord]] = None
    """Every goal declared in the thread, in the order they were declared.

    ``None`` if none has changed since the previous delta. A list, even an empty one, replaces the goals the client
    holds.
    """

    tasks: Optional[list[AgentTask]] = None
    """Task list of the thread, ordered by :py:attr:`~roboto.ai.agent_thread.AgentTask.position`.

    ``None`` if it has not changed since the previous delta. A list, even an empty one, replaces the tasks the client
    holds.
    """

    turn_notice: Optional[str] = None
    """The thread's ``AgentThreadRecord.turn_notice`` as of this delta.

    Like ``activity``, and unlike ``status``, ``title``, ``goals`` and ``tasks``, ``None`` does not mean unchanged:
    every delta carries the thread's current notice, so ``None`` means there is nothing to report. A client replaces
    the notice it holds with this value on every delta.
    """

    has_more: bool = False
    """Whether the thread has changes after the ones this delta carries, for the client to fetch at once.

    ``True`` in two cases. For a request sent with ``paged=true``, Roboto ends a delta early to keep the response
    small. A delta that sets ``reset_from_message_sequence_num`` carries none of the messages from that index on,
    whether or not the request was sent with ``paged=true``.

    When it is ``True``, the client requests the next delta with ``continuation_token`` without waiting, and repeats
    until a delta reports ``False``; only then does it hold every message the thread had. ``status`` describes the
    whole thread, so a delta that reports ``True`` can say the turn is over before the client holds the turn's last
    message. A delta that Roboto ended early carries ``goals`` and ``tasks`` as ``None``, changed or not; a later
    delta carries them.
    """


# Lists the content and task types and AgentGoalStatus, which this module imports from other modules, so they import
# from roboto.ai.core.record too.
__all__ = [
    "AGENT_CONTENT_MODEL_BY_TYPE",
    "CLIENT_TOOL_NAME_PREFIX",
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
    "AgentTextContent",
    "AgentThreadDelta",
    "AgentThreadGoalRecord",
    "AgentThreadRecord",
    "AgentThreadStatus",
    "AgentTask",
    "AgentTaskBoundary",
    "AgentTaskMinimal",
    "AgentTaskStatus",
    "AgentToolResultContent",
    "AgentToolUseContent",
    "ClientToolSpec",
    "ModelProfileResponse",
    "ThreadOrigin",
    "ThreadVisibility",
]
