# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic

from ..core import RobotoLLMContext
from ..core.record import (
    AgentContent,
    AgentContentType,
    AgentErrorContent,
    AgentMessage,
    AgentMessageStatus,
    AgentRole,
    AgentSession,
    AgentSessionDelta,
    AgentSessionStatus,
    AgentTextContent,
    AgentToolResultContent,
    AgentToolUseContent,
    # Backwards-compatible aliases
    ChatContent,
    ChatContentType,
    ChatErrorContent,
    ChatMessage,
    ChatMessageStatus,
    ChatRecord,
    ChatRecordDelta,
    ChatRole,
    ChatStatus,
    ChatTextContent,
    ChatToolResultContent,
    ChatToolUseContent,
    ClientToolSpec,
)


class ChatToolDetailResponse(pydantic.BaseModel):
    """Unsanitized tool request and response details for a chat tool invocation."""

    tool_use: AgentToolUseContent
    tool_result: AgentToolResultContent


class SendMessageRequest(pydantic.BaseModel):
    """Request payload for sending a message to a chat session.

    Contains the message content and optional context for the AI assistant.
    """

    context: Optional[RobotoLLMContext] = None
    """Optional context to include with the message."""

    message: AgentMessage
    """Message content to send."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Optional client-side tools available for this invocation."""


class StartChatRequest(pydantic.BaseModel):
    """Request payload for starting a new chat session.

    Contains the initial messages and configuration for creating a new
    chat conversation.
    """

    context: Optional[RobotoLLMContext] = None
    """Optional context to include with the message."""

    messages: list[AgentMessage]
    """Initial messages to start the conversation with."""

    system_prompt: Optional[str] = None
    """Optional system prompt to customize AI assistant behavior."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Optional client-side tools available for this invocation."""

    model_profile: Optional[str] = None
    """Optional model profile ID for the session (e.g. 'standard', 'advanced')."""


class SubmitToolResultsRequest(pydantic.BaseModel):
    """Request payload for submitting client-side tool execution results."""

    tool_results: list[AgentToolResultContent]
    """Tool results from client-side execution."""

    client_tools: Optional[list[ClientToolSpec]] = None
    """Optional updated client-side tools for the next invocation."""


__all__ = [
    "AgentContent",
    "AgentContentType",
    "AgentErrorContent",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentSession",
    "AgentSessionDelta",
    "AgentSessionStatus",
    "AgentTextContent",
    "AgentToolResultContent",
    "AgentToolUseContent",
    "ChatContent",
    "ChatContentType",
    "ChatErrorContent",
    "ChatMessage",
    "ChatMessageStatus",
    "ChatRecord",
    "ChatRecordDelta",
    "ChatRole",
    "ChatStatus",
    "ChatTextContent",
    "ChatToolDetailResponse",
    "ChatToolResultContent",
    "ChatToolUseContent",
    "ClientToolSpec",
    "SendMessageRequest",
    "StartChatRequest",
    "SubmitToolResultsRequest",
]
