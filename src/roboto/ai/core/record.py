# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import re
import typing
from typing import Any, Optional, Union

import pydantic

from ...compat import StrEnum
from ...time import utcnow
from ..goals import AgentGoal


class ThreadVisibility(StrEnum):
    """Read-scope for an :class:`AgentThreadRecord`.

    Set at thread creation time and immutable for the life of the thread.
    Import as :class:`roboto.ai.agent_thread.ThreadVisibility`.
    """

    PRIVATE = "private"
    """Only the creating user (and Roboto admins) may read the thread.

    Default for threads created via ``POST /v1/ai/threads`` so an
    in-flight experiment does not leak to the rest of the org until the
    caller opts in.
    """

    ORG = "org"
    """Any member of the thread's organization (and Roboto admins) may
    read the thread.

    Default for threads produced by the agent launch flow, since agents
    exist to share workflows across teammates. Forks of an ``ORG`` thread
    do not inherit visibility — every fork lands as ``PRIVATE``."""


CLIENT_TOOL_NAME_PREFIX = "client_"
"""Required prefix for every client-declared tool name.

Distinguishes client tools from server-side tools at every layer (API,
SDK, UI, Bedrock toolConfig) without ambiguity. Underscore is used rather
than a colon so the resulting name still matches Bedrock's Converse
``toolSpec.name`` pattern (``^[a-zA-Z][a-zA-Z0-9_]*$``).
"""

_CLIENT_TOOL_NAME_RE = re.compile(r"^client_[a-z][a-z0-9_]*$")
"""Pattern enforced on ``ClientToolSpec.name`` — see ``CLIENT_TOOL_NAME_PREFIX``."""


class ModelProfileResponse(pydantic.BaseModel):
    """Metadata about an available model profile, returned by the API."""

    id: str
    """Profile identifier, e.g. 'standard' or 'advanced'."""

    label: str
    """Human-readable display label."""

    description: str
    """Short description of the profile's characteristics."""

    is_default: bool = False
    """Whether this profile is selected by default for new threads."""


class AgentRole(StrEnum):
    """Enumeration of possible roles in an agent thread.

    Defines the different participants that can send messages in a thread.
    """

    USER = "user"
    """Human user sending messages to the agent."""

    ASSISTANT = "assistant"
    """AI agent responding to user queries and requests."""

    ROBOTO = "roboto"
    """Roboto system providing tool results and system information."""


class AgentMessageStatus(StrEnum):
    """Enumeration of possible message generation states.

    Tracks the lifecycle of message generation from initiation to completion.
    """

    NOT_STARTED = "not_started"
    """Message has been queued but generation has not begun."""

    GENERATING = "generating"
    """Message content is currently being generated."""

    COMPLETED = "completed"
    """Message generation has finished and content is complete."""

    FAILED = "failed"
    """Message generation failed due to an error."""

    CANCELLED = "cancelled"
    """Message generation was cancelled by the user."""

    def is_terminal(self) -> bool:
        """Check if the message generation is in a terminal state.

        Returns:
            True if the message is in a terminal state, False otherwise.
        """
        return self in (
            AgentMessageStatus.COMPLETED,
            AgentMessageStatus.FAILED,
            AgentMessageStatus.CANCELLED,
        )


class AgentThreadStatus(StrEnum):
    """Enumeration of possible agent thread states.

    Tracks the overall status of an agent thread from creation to termination.
    """

    NOT_STARTED = "not_started"
    """Thread has been created but no messages have been sent."""

    USER_TURN = "user_turn"
    """User has the turn to send a message."""

    ROBOTO_TURN = "roboto_turn"
    """Roboto is generating a message."""

    CLIENT_TOOL_TURN = "client_tool_turn"
    """Client must execute pending tool uses and submit results."""

    GOALS_FAILED = "goals_failed"
    """The agent runner exhausted its corrective re-prompt budget without achieving every declared goal for the
    most-recent turn. Signals to clients that the thread needs human intervention before it can continue."""


class AgentContentType(StrEnum):
    """Enumeration of different types of content within agent messages.

    Defines the various content types that can be included in agent messages.
    """

    TEXT = "text"
    """Plain text content from users or AI responses."""

    TOOL_USE = "tool_use"
    """Tool invocation requests from the AI assistant."""

    TOOL_RESULT = "tool_result"
    """Results returned from tool executions."""

    ERROR = "error"
    """Error information when message generation fails."""


class AgentTextContent(pydantic.BaseModel):
    """Text content within an agent message."""

    text: str
    """The actual text content of the message."""

    def __str__(self) -> str:
        return self.text


class AgentToolUseContent(pydantic.BaseModel):
    """Tool usage request content within an agent message."""

    content_type: typing.Literal[AgentContentType.TOOL_USE] = AgentContentType.TOOL_USE
    tool_name: str
    """Name of the tool the LLM is requesting to invoke."""
    tool_use_id: str
    """Unique identifier for this tool invocation, used to correlate with its result."""
    input: Optional[dict[str, Any]] = None
    """Parsed tool input parameters chosen by the LLM (provider-agnostic)."""
    raw_request: Optional[dict[str, Any]] = None
    """Raw, unparsed request payload for this tool invocation."""


class AgentToolResultContent(pydantic.BaseModel):
    """Tool execution result content within an agent message."""

    content_type: typing.Literal[AgentContentType.TOOL_RESULT] = AgentContentType.TOOL_RESULT
    tool_name: str
    """Name of the tool that was executed."""
    tool_use_id: str
    """Identifier of the tool invocation this result corresponds to."""
    runtime_ms: int
    """Wall-clock execution time of the tool in milliseconds."""
    status: str
    """Outcome of the tool execution (e.g. 'success', 'error')."""
    raw_response: Optional[dict[str, Any]] = None
    """Raw, unparsed response payload from tool execution."""


class AgentErrorContent(pydantic.BaseModel):
    """Error content within an agent message.

    Used when message generation fails due to an error or is cancelled by the user.
    """

    content_type: typing.Literal[AgentContentType.ERROR] = AgentContentType.ERROR
    error_message: str
    """User-friendly error message describing what went wrong."""

    error_code: Optional[str] = None
    """Optional error code for programmatic handling."""


AgentContent: typing.TypeAlias = Union[AgentTextContent, AgentToolUseContent, AgentToolResultContent, AgentErrorContent]
"""Type alias for all possible content types within agent messages."""


class ClientToolSpec(pydantic.BaseModel):
    """Declarative specification for a client-side tool.

    Unlike AgentTool (which is an ABC with a __call__ method for server-side
    execution), ClientToolSpec is a plain data model. The backend includes it
    in the LLM's tool list but never executes it — the client is responsible
    for execution and submitting the result.
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    @pydantic.field_validator("name")
    @classmethod
    def _validate_client_prefix(cls, v: str) -> str:
        # Enforced at deserialization so the API rejects bad names with a 400
        # before any thread state is persisted. The prefix is the disambiguator
        # the dispatcher relies on (``tool_name.startswith("client_")``); if a
        # client snuck a prefix-less name past this check it would either
        # collide with a server tool or fail Bedrock's Converse validation
        # later, after the thread was already on disk.
        if not _CLIENT_TOOL_NAME_RE.fullmatch(v):
            raise ValueError(
                f"client tool name {v!r} must match {_CLIENT_TOOL_NAME_RE.pattern} "
                f"(start with {CLIENT_TOOL_NAME_PREFIX!r}, then lowercase letters, "
                f"digits, and underscores)"
            )
        return v


class AgentMessage(pydantic.BaseModel):
    """A single message within an agent thread.

    Represents one message in the conversation, containing the sender role,
    content blocks, and generation status. Messages can contain multiple
    content blocks of different types (text, tool use, tool results).
    """

    role: AgentRole
    """The role of the message sender (user, assistant, or roboto)."""

    content: list[AgentContent]
    """List of content blocks that make up this message."""

    status: AgentMessageStatus = AgentMessageStatus.NOT_STARTED
    """Current generation status of this message."""

    created: datetime.datetime = pydantic.Field(default_factory=utcnow)
    """Timestamp when this message was created."""

    @classmethod
    def text(cls, text: str, role: AgentRole = AgentRole.USER) -> "AgentMessage":
        """Create a simple text message.

        Convenience method for creating a message containing only text content.

        Args:
            text: The text content for the message.
            role: The role of the message sender. Defaults to USER.

        Returns:
            AgentMessage instance containing the text content.
        """
        return cls(role=role, content=[AgentTextContent(text=text)])

    def __str__(self) -> str:
        combined_content = "".join(str(content) for content in self.content)
        return f"== {self.role.value.upper()} ==\n{combined_content}"

    def is_complete(self) -> bool:
        """Check if message generation is complete.

        Returns:
            True if the message status is COMPLETED, False otherwise.
        """
        return self.status == AgentMessageStatus.COMPLETED

    def is_unsuccessful(self) -> bool:
        """Check if message generation failed or was cancelled.

        Returns:
            True if the message status is FAILED or CANCELLED, False otherwise.
        """
        return self.role != AgentRole.USER and self.status in (
            AgentMessageStatus.FAILED,
            AgentMessageStatus.CANCELLED,
        )


class AgentGoalStatus(StrEnum):
    """Lifecycle of a per-turn declared goal.

    Goals begin PENDING when registered. They transition to ACHIEVED when the
    corresponding achieve-tool reports success, or to FAILED when the runner's
    corrective re-prompt budget for the turn is exhausted (or when the worker
    cannot construct an achieve-tool for the goal).
    """

    PENDING = "pending"
    """Goal has been registered but not yet completed."""

    ACHIEVED = "achieved"
    """Goal's corresponding achieve-tool was invoked successfully."""

    FAILED = "failed"
    """Goal could not be achieved within the turn's retry budget."""


class AgentThreadGoalRecord(pydantic.BaseModel):
    """Customer-visible read shape of a goal declared on an agent thread."""

    goal_type: str
    """Discriminator selecting which :class:`AgentGoal` model the
    :attr:`goal_data` payload conforms to (e.g. ``"dataset_summary"``)."""

    goal_data: dict[str, Any]
    """The validated goal payload as JSON. Use :meth:`to_agent_goal` to
    recover the typed model the caller declared."""

    status: AgentGoalStatus
    """Current lifecycle state of the goal."""

    message_sequence_num: int
    """Index in the thread's full messages list of the :attr:`AgentRole.USER`
    message that declared this goal. Use to render goals adjacent to the turn
    they were attached to."""

    created: datetime.datetime
    """Timestamp when the goal was registered."""

    concluded_at: Optional[datetime.datetime] = None
    """Timestamp when the goal transitioned to a terminal state (ACHIEVED or
    FAILED). ``None`` while the goal is still PENDING."""

    def to_agent_goal(self) -> AgentGoal:
        """Re-hydrate :attr:`goal_data` into the typed :data:`AgentGoal` the caller declared.

        Returns:
            The validated, discriminated :data:`AgentGoal` instance — for
            ``"dataset_summary"`` rows, a :class:`DatasetSummaryAgentGoal`;
            for ``"dataset_triage"`` rows, a :class:`DatasetTriageGoal`; etc.
        """
        return pydantic.TypeAdapter(AgentGoal).validate_python(self.goal_data)


class AgentThreadRecord(pydantic.BaseModel):
    """Complete record of an agent thread.

    Contains all the persistent data for a thread including metadata,
    message history, and synchronization state.
    """

    thread_id: str = pydantic.Field(
        validation_alias=pydantic.AliasChoices("thread_id", "session_id", "chat_id"),
    )
    """Unique identifier for this agent thread.

    Deserialization also accepts the legacy ``session_id`` and ``chat_id``
    spellings for backward compatibility; the canonical attribute name is
    ``thread_id``."""

    created: datetime.datetime
    """Timestamp when this agent thread was created."""

    created_by: str
    """User ID of the person who created this agent thread."""

    org_id: str
    """Organization ID that owns this agent thread."""

    messages: list[AgentMessage] = pydantic.Field(default_factory=list)
    """Complete list of messages in the conversation."""

    continuation_token: str
    """Token used for incremental updates and synchronization."""

    status: AgentThreadStatus
    """Current status of this agent thread."""

    title: Optional[str] = None
    """Title of this agent thread."""

    model_profile: Optional[str] = None
    """Model profile used for this agent thread (e.g., 'standard', 'advanced')."""

    forked_from_thread_id: Optional[str] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("forked_from_thread_id", "forked_from_session_id"),
    )
    """If this thread was forked, the id of the source thread. ``None`` otherwise.

    Deserialization also accepts the legacy ``forked_from_session_id``
    spelling for backward compatibility."""

    forked_from_message_sequence_num: Optional[int] = None
    """Message sequence number in the source thread that this fork was taken from.

    Populated in tandem with ``forked_from_thread_id``; both are ``None`` for
    threads that were not created as a fork.
    """

    visibility: ThreadVisibility = ThreadVisibility.PRIVATE
    """Who can read this thread. ``PRIVATE`` (the default) restricts reads
    to the :attr:`created_by` user and Roboto admins; ``ORG`` opens the
    thread to every member of :attr:`org_id`."""

    created_from_agent_id: Optional[str] = None
    """If this thread was started via the agent launch flow, the id of
    the agent that produced it. ``None`` for threads started directly
    through ``POST /v1/ai/threads``. Forks do not inherit this field —
    a fork is its own thread."""

    goals: Optional[list[AgentThreadGoalRecord]] = None
    """Goals declared across this thread's turns, ordered by the turn
    that declared them. ``None`` means goals were not loaded for this
    record; an empty list means they were loaded but the thread never
    declared any."""


class AgentThreadDelta(pydantic.BaseModel):
    """Incremental update to an agent thread.

    Contains only the changes since the last synchronization, used for
    efficient real-time updates without transferring the entire thread history.
    """

    messages_by_idx: dict[int, AgentMessage]
    """New or updated messages indexed by their position in the conversation."""

    continuation_token: str
    """Updated token for the next incremental synchronization."""

    status: Optional[AgentThreadStatus] = None
    """Updated status of the agent thread."""

    title: Optional[str] = None
    """Updated title of the agent thread."""

    goals: Optional[list[AgentThreadGoalRecord]] = None
    """Latest snapshot of every goal declared in the thread, ordered by
    allocation. ``None`` means there has been no change since the previous
    delta — clients should retain the snapshot they already hold. An empty
    list means the thread has no declared goals. A non-empty list is the
    authoritative current snapshot and replaces any prior value."""
