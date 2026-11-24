# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Data models of threads with Roboto's AI: messages, their content blocks, and the events a thread yields.

:py:attr:`~roboto.ai.agent_thread.AgentThread.messages` returns :py:class:`~roboto.ai.core.AgentMessage` items, and
:py:meth:`~roboto.ai.agent_thread.AgentThread.events` yields :py:const:`~roboto.ai.core.AgentEvent` items as the AI
responds. Pass :py:class:`~roboto.ai.core.ClientViewingContext` to :py:meth:`~roboto.ai.agent_thread.AgentThread.start`
or :py:meth:`~roboto.ai.agent_thread.AgentThread.send` to tell the AI what the user is looking at, and
:py:class:`~roboto.ai.core.AnalysisScope` to set the time range the AI should analyze.
"""

from .content import (
    synthesize_tool_result_payload,
)
from .context import (
    AnalysisScope,
    ClientViewingContext,
)
from .event import (
    AgentErrorEvent,
    AgentEvent,
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolResultEvent,
    AgentToolUseEvent,
)
from .record import (
    AGENT_CONTENT_MODEL_BY_TYPE,
    AgentClientContextEntry,
    AgentCompressionFillerContent,
    AgentContent,
    AgentContentType,
    AgentDeletedContent,
    AgentErrorContent,
    AgentMessage,
    AgentMessageStatus,
    AgentRole,
    AgentTextContent,
    AgentThreadDelta,
    AgentThreadRecord,
    AgentThreadStatus,
    AgentToolResultContent,
    AgentToolUseContent,
    ClientToolSpec,
    ModelProfileResponse,
)

__all__ = [
    "AGENT_CONTENT_MODEL_BY_TYPE",
    "AgentClientContextEntry",
    "AgentCompressionFillerContent",
    "AgentContent",
    "AgentContentType",
    "AgentDeletedContent",
    "AgentErrorContent",
    "AgentErrorEvent",
    "AgentEvent",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentThreadDelta",
    "AgentThreadRecord",
    "AgentThreadStatus",
    "AgentStartTextEvent",
    "AgentTextContent",
    "AgentTextDeltaEvent",
    "AgentTextEndEvent",
    "AgentToolResultContent",
    "AgentToolResultEvent",
    "AgentToolUseContent",
    "AgentToolUseEvent",
    "AnalysisScope",
    "ClientToolSpec",
    "ClientViewingContext",
    "ModelProfileResponse",
    "synthesize_tool_result_payload",
]


# Deprecated alias for ClientViewingContext, so existing imports of RobotoLLMContext keep working.
RobotoLLMContext = ClientViewingContext
