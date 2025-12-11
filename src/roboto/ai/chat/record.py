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
from ..core import RobotoLLMContext


class ChatRole(StrEnum):
    """Enumeration of possible roles in a chat conversation.

    Defines the different participants that can send messages in a chat session.
    """

    USER = "user"
    """Human user sending messages to the AI assistant."""

    ASSISTANT = "assistant"
    """AI assistant responding to user queries and requests."""

    ROBOTO = "roboto"
    """Roboto system providing tool results and system information."""


class ChatMessageStatus(StrEnum):
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
        return self in (ChatMessageStatus.COMPLETED, ChatMessageStatus.FAILED, ChatMessageStatus.CANCELLED)


class ChatStatus(StrEnum):
    """Enumeration of possible chat session states.

    Tracks the overall status of a chat session from creation to termination.
    """

    NOT_STARTED = "not_started"
    """Chat session has been created but no messages have been sent."""

    USER_TURN = "user_turn"
    """User has the turn to send a message."""

    ROBOTO_TURN = "roboto_turn"
    """Roboto is generating a message."""


class ChatContentType(StrEnum):
    """Enumeration of different types of content within chat messages.

    Defines the various content types that can be included in chat messages.
    """

    TEXT = "text"
    """Plain text content from users or AI responses."""

    TOOL_USE = "tool_use"
    """Tool invocation requests from the AI assistant."""

    TOOL_RESULT = "tool_result"
    """Results returned from tool executions."""

    ERROR = "error"
    """Error information when message generation fails."""


class ChatTextContent(pydantic.BaseModel):
    """Text content within a chat message."""

    text: str
    """The actual text content of the message."""

    def __str__(self) -> str:
        return self.text


class ChatToolUseContent(pydantic.BaseModel):
    """Tool usage request content within a chat message."""

    content_type: typing.Literal[ChatContentType.TOOL_USE] = ChatContentType.TOOL_USE
    tool_name: str
    tool_use_id: str
    raw_request: Optional[dict[str, Any]] = None


class ChatToolResultContent(pydantic.BaseModel):
    """Tool execution result content within a chat message."""

    content_type: typing.Literal[ChatContentType.TOOL_RESULT] = ChatContentType.TOOL_RESULT
    tool_name: str
    tool_use_id: str
    runtime_ms: int
    status: str
    raw_response: Optional[dict[str, Any]] = None


class ChatErrorContent(pydantic.BaseModel):
    """Error content within a chat message.

    Used when message generation fails due to an error or is cancelled by the user.
    """

    content_type: typing.Literal[ChatContentType.ERROR] = ChatContentType.ERROR
    error_message: str
    """User-friendly error message describing what went wrong."""

    error_code: Optional[str] = None
    """Optional error code for programmatic handling."""


ChatContent: typing.TypeAlias = Union[ChatTextContent, ChatToolUseContent, ChatToolResultContent, ChatErrorContent]
"""Type alias for all possible content types within chat messages."""


class ChatMessage(pydantic.BaseModel):
    """A single message within a chat conversation.

    Represents one message in the conversation, containing the sender role,
    content blocks, and generation status. Messages can contain multiple
    content blocks of different types (text, tool use, tool results).
    """

    role: ChatRole
    """The role of the message sender (user, assistant, or roboto)."""

    content: list[ChatContent]
    """List of content blocks that make up this message."""

    status: ChatMessageStatus = ChatMessageStatus.NOT_STARTED
    """Current generation status of this message."""

    created: datetime.datetime = pydantic.Field(default_factory=utcnow)
    """Timestamp when this message was created."""

    @classmethod
    def text(cls, text: str, role: ChatRole = ChatRole.USER) -> "ChatMessage":
        """Create a simple text message.

        Convenience method for creating a message containing only text content.

        Args:
            text: The text content for the message.
            role: The role of the message sender. Defaults to USER.

        Returns:
            ChatMessage instance containing the text content.
        """
        return cls(role=role, content=[ChatTextContent(text=text)])

    def __str__(self) -> str:
        combined_content = "".join(str(content) for content in self.content)
        return f"== {self.role.value.upper()} ==\n{combined_content}"

    def is_complete(self) -> bool:
        """Check if message generation is complete.

        Returns:
            True if the message status is COMPLETED, False otherwise.
        """
        return self.status == ChatMessageStatus.COMPLETED

    def is_unsuccessful(self) -> bool:
        """Check if message generation failed or was cancelled.

        Returns:
            True if the message status is FAILED or CANCELLED, False otherwise.
        """
        return self.role != ChatRole.USER and self.status in (ChatMessageStatus.FAILED, ChatMessageStatus.CANCELLED)


class ChatRecord(pydantic.BaseModel):
    """Complete record of a chat session.

    Contains all the persistent data for a chat session including metadata,
    message history, and synchronization state.
    """

    chat_id: str
    """Unique identifier for this chat session."""

    created: datetime.datetime
    """Timestamp when the chat session was created."""

    created_by: str
    """User ID of the person who created this chat session."""

    org_id: str
    """Organization ID that owns this chat session."""

    messages: list[ChatMessage] = pydantic.Field(default_factory=list)
    """Complete list of messages in the conversation."""

    continuation_token: str
    """Token used for incremental updates and synchronization."""

    status: ChatStatus
    """Current status of the chat session."""

    title: Optional[str] = None
    """Title of the chat session."""

    def calculate_new_status(self) -> ChatStatus:
        """Calculate the new status of the chat session based on the latest message."""
        if len(self.messages) == 0:
            return ChatStatus.NOT_STARTED

        latest_message = self.messages[-1]

        # Failed or cancelled messages always return control to the user
        if latest_message.is_unsuccessful():
            return ChatStatus.USER_TURN

        # Normal completion: assistant message with text content
        is_user_turn = (
            latest_message.role == ChatRole.ASSISTANT
            and latest_message.status == ChatMessageStatus.COMPLETED
            and len(latest_message.content) > 0
            and isinstance(latest_message.content[-1], ChatTextContent)
        )

        if is_user_turn:
            return ChatStatus.USER_TURN
        else:
            return ChatStatus.ROBOTO_TURN


class ChatRecordDelta(pydantic.BaseModel):
    """Incremental update to a chat session.

    Contains only the changes since the last synchronization, used for
    efficient real-time updates without transferring the entire chat history.
    """

    messages_by_idx: dict[int, ChatMessage]
    """New or updated messages indexed by their position in the conversation."""

    continuation_token: str
    """Updated token for the next incremental synchronization."""

    status: Optional[ChatStatus] = None
    """Updated status of the chat session."""

    title: Optional[str] = None
    """Updated title of the chat session."""

    def calculate_new_status(self) -> ChatStatus | None:
        """Calculate the new status of the chat session based on the latest message."""
        if len(self.messages_by_idx) == 0:
            return None

        latest_message_idx = max(self.messages_by_idx.keys())
        latest_message = self.messages_by_idx[latest_message_idx]

        # Failed or cancelled messages always return control to the user
        if latest_message.is_unsuccessful():
            return ChatStatus.USER_TURN

        # Normal completion: assistant message with text content
        is_user_turn = (
            latest_message.role == ChatRole.ASSISTANT
            and latest_message.status == ChatMessageStatus.COMPLETED
            and len(latest_message.content) > 0
            and isinstance(latest_message.content[-1], ChatTextContent)
        )

        if is_user_turn:
            return ChatStatus.USER_TURN
        else:
            return ChatStatus.ROBOTO_TURN


class SendMessageRequest(pydantic.BaseModel):
    """Request payload for sending a message to a chat session.

    Contains the message content and optional context for the AI assistant.
    """

    context: Optional[RobotoLLMContext] = None
    """Optional context to include with the message."""

    message: ChatMessage
    """Message content to send."""


class StartChatRequest(pydantic.BaseModel):
    """Request payload for starting a new chat session.

    Contains the initial messages and configuration for creating a new
    chat conversation.
    """

    context: Optional[RobotoLLMContext] = None
    """Optional context to include with the message."""

    messages: list[ChatMessage]
    """Initial messages to start the conversation with."""

    system_prompt: Optional[str] = None
    """Optional system prompt to customize AI assistant behavior."""
