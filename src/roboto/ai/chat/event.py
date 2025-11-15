# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic


class ChatStartTextEvent(pydantic.BaseModel):
    """Signals the beginning of text generation in a chat response."""


class ChatTextDeltaEvent(pydantic.BaseModel):
    """Contains incremental text content as the AI generates its response."""

    text: str
    """Text fragment from the streaming response."""


class ChatTextEndEvent(pydantic.BaseModel):
    """Signals the completion of text generation in a chat response."""


class ChatToolUseEvent(pydantic.BaseModel):
    """Signals that the AI is invoking a tool to gather information."""

    name: str
    """Name of the tool being invoked."""

    tool_use_id: str
    """Unique identifier for this tool invocation."""


class ChatToolResultEvent(pydantic.BaseModel):
    """Contains the result of a tool invocation."""

    name: str
    """Name of the tool that was invoked."""

    tool_use_id: str
    """Unique identifier for this tool invocation."""

    success: bool
    """Whether the tool invocation succeeded."""


ChatEvent: typing.TypeAlias = typing.Union[
    ChatStartTextEvent,
    ChatTextDeltaEvent,
    ChatTextEndEvent,
    ChatToolUseEvent,
    ChatToolResultEvent,
]
