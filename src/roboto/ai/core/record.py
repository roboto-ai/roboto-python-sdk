# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing
from typing import Any, Optional, Union

import pydantic

from ...compat import StrEnum
from ...time import utcnow


class ModelProfileResponse(pydantic.BaseModel):
    """Metadata about an available model profile, returned by the API."""

    id: str
    """Profile identifier, e.g. 'standard' or 'advanced'."""

    label: str
    """Human-readable display label."""

    description: str
    """Short description of the profile's characteristics."""

    is_default: bool = False
    """Whether this profile is selected by default for new sessions."""


class AgentRole(StrEnum):
    """Enumeration of possible roles in an agent session.

    Defines the different participants that can send messages in a session.
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


class AgentSessionStatus(StrEnum):
    """Enumeration of possible agent session states.

    Tracks the overall status of an agent session from creation to termination.
    """

    NOT_STARTED = "not_started"
    """Session has been created but no messages have been sent."""

    USER_TURN = "user_turn"
    """User has the turn to send a message."""

    ROBOTO_TURN = "roboto_turn"
    """Roboto is generating a message."""

    CLIENT_TOOL_TURN = "client_tool_turn"
    """Client must execute pending tool uses and submit results."""


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


class AgentMessage(pydantic.BaseModel):
    """A single message within an agent session.

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


class AgentSession(pydantic.BaseModel):
    """Complete record of an agent session.

    Contains all the persistent data for a session including metadata,
    message history, and synchronization state.
    """

    session_id: str = pydantic.Field(validation_alias=pydantic.AliasChoices("session_id", "chat_id"))
    """Unique identifier for this agent session."""

    created: datetime.datetime
    """Timestamp when this agent session was created."""

    created_by: str
    """User ID of the person who created this agent session."""

    org_id: str
    """Organization ID that owns this agent session."""

    messages: list[AgentMessage] = pydantic.Field(default_factory=list)
    """Complete list of messages in the conversation."""

    continuation_token: str
    """Token used for incremental updates and synchronization."""

    status: AgentSessionStatus
    """Current status of this agent session."""

    title: Optional[str] = None
    """Title of this agent session."""

    model_profile: Optional[str] = None
    """Model profile used for this agent session (e.g., 'standard', 'advanced')."""

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def chat_id(self) -> str:
        """Backwards-compatible alias — serialized as chat_id in API responses."""
        return self.session_id


class AgentSessionDelta(pydantic.BaseModel):
    """Incremental update to an agent session.

    Contains only the changes since the last synchronization, used for
    efficient real-time updates without transferring the entire session history.
    """

    messages_by_idx: dict[int, AgentMessage]
    """New or updated messages indexed by their position in the conversation."""

    continuation_token: str
    """Updated token for the next incremental synchronization."""

    status: Optional[AgentSessionStatus] = None
    """Updated status of the agent session."""

    title: Optional[str] = None
    """Updated title of the agent session."""


# Backwards-compatible aliases
ChatRole = AgentRole
ChatMessageStatus = AgentMessageStatus
ChatStatus = AgentSessionStatus
ChatContentType = AgentContentType
ChatTextContent = AgentTextContent
ChatToolUseContent = AgentToolUseContent
ChatToolResultContent = AgentToolResultContent
ChatErrorContent = AgentErrorContent
ChatContent = AgentContent
ChatMessage = AgentMessage
ChatRecord = AgentSession
ChatRecordDelta = AgentSessionDelta
