# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
from typing import Any, Optional

import pydantic


class AgentStartTextEvent(pydantic.BaseModel):
    """Signals the beginning of text generation in a chat response."""


class AgentTextDeltaEvent(pydantic.BaseModel):
    """Contains incremental text content as the AI generates its response."""

    text: str
    """Text fragment from the streaming response."""


class AgentTextEndEvent(pydantic.BaseModel):
    """Signals the completion of text generation in a chat response."""


class AgentToolUseEvent(pydantic.BaseModel):
    """Signals that the AI is invoking a tool to gather information."""

    name: str
    """Name of the tool being invoked."""

    tool_use_id: str
    """Unique identifier for this tool invocation."""

    input: Optional[dict[str, Any]] = None
    """Parsed tool input parameters chosen by the LLM."""


class AgentToolResultEvent(pydantic.BaseModel):
    """Contains the result of a tool invocation."""

    name: str
    """Name of the tool that was invoked."""

    tool_use_id: str
    """Unique identifier for this tool invocation."""

    success: bool
    """Whether the tool invocation succeeded."""

    output: Optional[dict[str, Any]] = None
    """Raw tool output payload (from the underlying tool_result's
    ``raw_response``). May be ``None`` for errored invocations or for tools
    that return no data."""

    runtime_ms: Optional[int] = None
    """Wall-clock execution time of the tool in milliseconds, as reported by
    the tool-result content. ``None`` only if the underlying content omits it."""


class AgentErrorEvent(pydantic.BaseModel):
    """Signals that message generation failed or was cancelled."""

    error_message: str
    """User-friendly error message describing what went wrong."""

    error_code: Optional[str] = None
    """Optional error code for programmatic handling."""


AgentEvent: typing.TypeAlias = typing.Union[
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolUseEvent,
    AgentToolResultEvent,
    AgentErrorEvent,
]
