# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from enum import Enum
import typing
from typing import Any, Optional, Union

import pydantic


class ChatRole(str, Enum):
    """Enumeration of possible roles in a chat conversation.

    Defines the different participants that can send messages in a chat session.
    """

    USER = "user"
    """Human user sending messages to the AI assistant."""

    ASSISTANT = "assistant"
    """AI assistant responding to user queries and requests."""

    ROBOTO = "roboto"
    """Roboto system providing tool results and system information."""


class ChatMessageStatus(str, Enum):
    """Enumeration of possible message generation states.

    Tracks the lifecycle of message generation from initiation to completion.
    """

    NOT_STARTED = "not_started"
    """Message has been queued but generation has not begun."""

    GENERATING = "generating"
    """Message content is currently being generated."""

    COMPLETED = "completed"
    """Message generation has finished and content is complete."""


class ChatContentType(str, Enum):
    """Enumeration of different types of content within chat messages.

    Defines the various content types that can be included in chat messages.
    """

    TEXT = "text"
    """Plain text content from users or AI responses."""

    TOOL_USE = "tool_use"
    """Tool invocation requests from the AI assistant."""

    TOOL_RESULT = "tool_result"
    """Results returned from tool executions."""


class ChatTextContent(pydantic.BaseModel):
    """Text content within a chat message."""

    text: str
    """The actual text content of the message."""

    def __str__(self) -> str:
        return self.text


class ChatToolUseContent(pydantic.BaseModel):
    """Tool usage request content within a chat message."""

    tool_use: dict[str, Any]
    """Tool invocation details including tool name and parameters."""


class ChatToolResultContent(pydantic.BaseModel):
    """Tool execution result content within a chat message."""

    tool_result: dict[str, Any]
    """Results returned from tool execution including output data and status."""


ChatContent: typing.TypeAlias = Union[
    ChatTextContent, ChatToolUseContent, ChatToolResultContent
]
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


class ChatRecordDelta(pydantic.BaseModel):
    """Incremental update to a chat session.

    Contains only the changes since the last synchronization, used for
    efficient real-time updates without transferring the entire chat history.
    """

    messages_by_idx: dict[int, ChatMessage]
    """New or updated messages indexed by their position in the conversation."""

    continuation_token: str
    """Updated token for the next incremental synchronization."""


class StartChatRequest(pydantic.BaseModel):
    """Request payload for starting a new chat session.

    Contains the initial messages and configuration for creating a new
    chat conversation.
    """

    messages: list[ChatMessage]
    """Initial messages to start the conversation with."""

    system_prompt: Optional[str] = None
    """Optional system prompt to customize AI assistant behavior."""
