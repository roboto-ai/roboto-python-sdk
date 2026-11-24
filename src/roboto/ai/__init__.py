# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Conversations with Roboto's AI, and the summaries the AI writes of datasets and sessions.

To converse with the AI, use :py:class:`~roboto.ai.agent_thread.AgentThread` to start a thread, a persistent,
multi-turn conversation, and to send it messages and follow its replies as the AI writes them; to have the AI summarize
a dataset, use :py:meth:`~roboto.domain.datasets.Dataset.generate_summary` or
:py:meth:`~roboto.domain.datasets.Dataset.get_summary`. Decorate a function with
:py:func:`~roboto.ai.agent_thread.client_tool` to let the AI call it in your Python process during a thread. The
summary methods return a :py:class:`~roboto.ai.summary.StreamingAISummary`, which gives the summary as
:py:class:`~roboto.ai.AISummary` snapshots or as text streamed while the AI writes it.
"""

from .agent_thread import (
    AgentThread,
    ClientTool,
    ClientToolResult,
    ClientToolResultStatus,
    ClientToolSpec,
    client_tool,
)
from .core.record import AgentThreadRecord
from .record import (
    PromptRequest,
    SetSummaryRequest,
)
from .summary import AISummary

__all__ = [
    "AgentThread",
    "AgentThreadRecord",
    "AISummary",
    "ClientTool",
    "ClientToolResult",
    "ClientToolResultStatus",
    "ClientToolSpec",
    "PromptRequest",
    "SetSummaryRequest",
    "client_tool",
]
