# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Core AI abstractions usable by any other submodule within module `roboto.ai`.
"""

from .context import RobotoLLMContext
from .event import (
    AgentEvent,
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolResultEvent,
    AgentToolUseEvent,
    # Backwards-compatible aliases
    ChatEvent,
    ChatStartTextEvent,
    ChatTextDeltaEvent,
    ChatTextEndEvent,
    ChatToolResultEvent,
    ChatToolUseEvent,
)
from .record import (
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
    ModelProfileResponse,
)

__all__ = [
    "AgentContent",
    "AgentContentType",
    "AgentErrorContent",
    "AgentEvent",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentSession",
    "AgentSessionDelta",
    "AgentSessionStatus",
    "AgentStartTextEvent",
    "AgentTextContent",
    "AgentTextDeltaEvent",
    "AgentTextEndEvent",
    "AgentToolResultContent",
    "AgentToolResultEvent",
    "AgentToolUseContent",
    "AgentToolUseEvent",
    "ClientToolSpec",
    "ModelProfileResponse",
    "ChatContent",
    "ChatContentType",
    "ChatErrorContent",
    "ChatEvent",
    "ChatMessage",
    "ChatMessageStatus",
    "ChatRecord",
    "ChatRecordDelta",
    "ChatRole",
    "ChatStartTextEvent",
    "ChatStatus",
    "ChatTextContent",
    "ChatTextDeltaEvent",
    "ChatTextEndEvent",
    "ChatToolResultContent",
    "ChatToolResultEvent",
    "ChatToolUseContent",
    "ChatToolUseEvent",
    "RobotoLLMContext",
]
