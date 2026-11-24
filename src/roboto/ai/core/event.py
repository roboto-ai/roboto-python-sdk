# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
from typing import Any, Optional

import pydantic


class AgentStartTextEvent(pydantic.BaseModel):
    """Event marking the start of a run of text in a message.

    ``AgentTextDeltaEvent`` events carry the run's text, and an ``AgentTextEndEvent`` ends it. A message yields one run
    for each stretch of text that no other content interrupts.
    """


class AgentTextDeltaEvent(pydantic.BaseModel):
    """Event carrying the next piece of a run of text, as Roboto's AI generates it."""

    text: str
    """Next piece of the run's text. Joining the pieces in order gives the run's full text."""


class AgentTextEndEvent(pydantic.BaseModel):
    """Event marking the end of a run of text in a message.

    Yielded when content other than text, such as a tool use, follows the run in the message, or when generation of
    the message ends.
    """


class AgentToolUseEvent(pydantic.BaseModel):
    """Event reporting that Roboto's AI asked to run a tool."""

    name: str
    """Name of the tool the AI asked to run."""

    tool_use_id: str
    """Unique ID of the tool use. The ``AgentToolResultEvent`` reporting its result carries the same ID."""

    input: Optional[dict[str, Any]] = None
    """Input the AI chose for the tool, or ``None`` if the tool use carries none."""

    answered_by_server: bool = False
    """Whether Roboto answers this call to a client tool itself, in which case the caller must not run the tool.

    Always ``False`` for a tool Roboto runs. See :py:attr:`~roboto.ai.core.AgentToolUseContent.answered_by_server`.
    """


class AgentToolResultEvent(pydantic.BaseModel):
    """Event reporting the result of a tool the AI asked to run."""

    name: str
    """Name of the tool the result is for."""

    tool_use_id: str
    """ID of the tool use this result answers, the same as on its ``AgentToolUseEvent``."""

    success: bool
    """Whether the tool succeeded."""

    output: Optional[dict[str, Any]] = None
    """Unused. Always ``None``, since Roboto leaves the tool's raw result out of the threads it returns.

    The SDK copies it from :py:attr:`~roboto.ai.core.AgentToolResultContent.raw_response`. Read what the tool returned
    from ``payload`` on the matching :py:class:`~roboto.ai.core.AgentToolResultContent` in
    :py:attr:`~roboto.ai.agent_thread.AgentThread.messages` instead.
    """

    runtime_ms: Optional[int] = None
    """Wall-clock time the tool took to run, in milliseconds."""


class AgentErrorEvent(pydantic.BaseModel):
    """Event reporting an error in a message, such as when its generation failed or was cancelled."""

    error_message: str
    """Human-readable description of what went wrong."""

    error_code: Optional[str] = None
    """Code identifying the kind of error, for a program to act on, or ``None`` if the error has none."""


AgentEvent: typing.TypeAlias = typing.Union[
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolUseEvent,
    AgentToolResultEvent,
    AgentErrorEvent,
]
"""Event of any kind that :py:meth:`~roboto.ai.agent_thread.AgentThread.events` yields.

One of ``AgentStartTextEvent``, ``AgentTextDeltaEvent``, ``AgentTextEndEvent``, ``AgentToolUseEvent``,
``AgentToolResultEvent`` and ``AgentErrorEvent``. The SDK builds each event from the content Roboto adds to the
thread's messages; the caller's own messages yield none. :py:meth:`~roboto.ai.agent_thread.AgentThread.run` passes each
event to its ``on_event`` function.
"""
