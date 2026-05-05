# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Core AI abstractions usable by any other submodule within module `roboto.ai`.
"""

from .context import (
    AnalysisScope,
    RobotoLLMContext,
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
    AgentContent,
    AgentContentType,
    AgentErrorContent,
    AgentMessage,
    AgentMessageStatus,
    AgentRole,
    AgentSessionDelta,
    AgentSessionRecord,
    AgentSessionStatus,
    AgentTextContent,
    AgentToolResultContent,
    AgentToolUseContent,
    ClientToolSpec,
    ModelProfileResponse,
)

__all__ = [
    "AgentContent",
    "AgentContentType",
    "AgentErrorContent",
    "AgentErrorEvent",
    "AgentEvent",
    "AgentMessage",
    "AgentMessageStatus",
    "AgentRole",
    "AgentSessionDelta",
    "AgentSessionRecord",
    "AgentSessionStatus",
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
    "ModelProfileResponse",
    "RobotoLLMContext",
]
