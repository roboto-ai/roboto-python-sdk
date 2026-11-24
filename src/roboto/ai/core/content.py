# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing
from typing import Any, Optional, Union

import pydantic

from ...compat import StrEnum
from .context import ClientViewingContext


class AgentContentType(StrEnum):
    """Kind of a content block in a message."""

    TEXT = "text"
    """Text blocks (``AgentTextContent``), from the caller or from Roboto's AI."""

    TOOL_USE = "tool_use"
    """Tool uses (``AgentToolUseContent``): requests from Roboto's AI to run a tool."""

    TOOL_RESULT = "tool_result"
    """Tool results (``AgentToolResultContent``): what a tool returned when it ran."""

    ERROR = "error"
    """Errors (``AgentErrorContent``): why generating a message failed or stopped."""

    DELETED = "deleted"
    """Placeholders (``AgentDeletedContent``) for blocks Roboto removed from what it sends to the AI model.

    Messages Roboto returns never contain one."""

    CLIENT_CONTEXT = "client_context"
    """Viewing context (``AgentClientContextEntry``): what the caller had open when they sent the message."""

    COMPRESSION_FILLER = "compression_filler"
    """Stand-ins (``AgentCompressionFillerContent``) for messages left empty in what Roboto sends to the AI model.

    Messages Roboto returns never contain one."""


class AgentTextContent(pydantic.BaseModel):
    """Text block of a message, from the caller or from Roboto's AI."""

    text: str
    """Text of the block."""

    def __str__(self) -> str:
        return self.text


class AgentToolUseContent(pydantic.BaseModel):
    """Tool use block of a message: a request from Roboto's AI to run a tool."""

    content_type: typing.Literal[AgentContentType.TOOL_USE] = AgentContentType.TOOL_USE
    """Kind of content block, always ``AgentContentType.TOOL_USE``."""
    tool_name: str
    """Name of the tool the AI asks to run."""
    tool_use_id: str
    """Unique ID of the tool use, which the tool's result carries as its ``tool_use_id``."""
    input: Optional[dict[str, Any]] = None
    """Input the AI chose for the tool, in a form that does not depend on the AI model the thread runs on.

    ``None`` on tool uses recorded before Roboto stored it."""
    raw_request: Optional[dict[str, Any]] = None
    """Request to run the tool, in the AI model's format.

    Roboto removes it from threads it returns; only ``GET /v1/ai/threads/{thread_id}/tool-use/{tool_use_id}``
    (:py:class:`~roboto.ai.agent_thread.AgentToolDetailResponse`) keeps it."""
    answered_by_server: bool = False
    """Whether Roboto answers this call to a client tool itself, instead of handing it to the caller.

    ``True`` when Roboto refused the call. Roboto then records an error result for it, so the caller must not run the
    tool: client tool results submitted with a result for this tool use raise ``RobotoInvalidRequestException``.
    :py:meth:`~roboto.ai.agent_thread.AgentThread.run` skips such tool uses when it runs client tools. Always ``False``
    on a call to a tool Roboto runs."""


class AgentArtifactRecord(pydantic.BaseModel):
    """File a tool produced while it ran.

    Carried in ``AgentToolResultContent.artifacts``. Holds no URL. To download the file, request
    ``GET /v1/ai/threads/{thread_id}/tool-use/{tool_use_id}/artifacts/{name}``, which returns
    :py:class:`~roboto.ai.agent_thread.AgentToolArtifactResponse`.
    """

    name: str
    """Name of the file, as the tool reported it. It can include a directory, such as ``plots/a.png``."""

    bytes: int
    """Size of the file, in bytes."""

    content_type: str
    """Media type the tool reported for the file."""

    status: str
    """What became of the file, such as ``"uploaded"`` (stored, and downloadable) or ``"too_large"``.

    Present even when Roboto did not keep the file. Each tool defines its own values.
    """


class AgentToolResultContent(pydantic.BaseModel):
    """Tool result block of a message: what a tool returned when it ran for a tool use."""

    content_type: typing.Literal[AgentContentType.TOOL_RESULT] = AgentContentType.TOOL_RESULT
    """Kind of content block, always ``AgentContentType.TOOL_RESULT``."""
    tool_name: str
    """Name of the tool that ran."""
    tool_use_id: str
    """ID of the tool use this result answers, as ``AgentToolUseContent.tool_use_id`` gives it."""
    runtime_ms: int
    """Wall-clock time the tool took to run, in milliseconds."""
    status: str
    """Outcome of the tool run, such as ``"success"`` or ``"error"``."""
    artifacts: Optional[list[AgentArtifactRecord]] = None
    """Files the tool produced while it ran, or ``None`` when the tool's output lists none.

    Roboto reads them from the ``outputs`` field of the tool's output. Unlike ``raw_response``, kept in threads Roboto
    returns, so a client can offer downloads without fetching each tool result.
    """

    payload: Optional[Union[str, dict[str, Any], list[Any]]] = None
    """What the tool returned: text, or a JSON object or array.

    Its form does not depend on the AI model the thread runs on. ``None`` when the result holds no text or JSON output.
    A result recorded before Roboto stored this field can hold its output only in ``raw_response``;
    ``resolve_payload`` reads it from either field."""
    raw_response: Optional[dict[str, Any]] = None
    """Deprecated. Result of the tool in the AI model's format, a ``toolResult`` object.

    Read ``payload``, or call ``resolve_payload``, instead. Roboto removes this field from threads it returns, after
    filling ``payload`` from it when ``payload`` is empty; only
    ``GET /v1/ai/threads/{thread_id}/tool-use/{tool_use_id}``
    (:py:class:`~roboto.ai.agent_thread.AgentToolDetailResponse`) keeps it."""

    def resolve_payload(self) -> Optional[Union[str, dict[str, Any], list[Any]]]:
        """Return what the tool returned, from ``payload``, or from ``raw_response`` when ``payload`` is ``None``.

        Returns:
            The tool's text or JSON output, or ``None`` when neither field holds one.
        """
        if self.payload is not None:
            return self.payload
        return synthesize_tool_result_payload(self.raw_response)


def synthesize_tool_result_payload(
    raw_response: Optional[dict[str, Any]],
) -> Optional[Union[str, dict[str, Any], list[Any]]]:
    """Build a tool result's text or JSON output from its ``raw_response``.

    Roboto calls this when it records a tool result, and when it returns a result recorded before it stored
    ``AgentToolResultContent.payload``. To read a result's output, use ``AgentToolResultContent.resolve_payload``
    instead.

    It reads two forms of ``raw_response``:

    - A dictionary with a ``toolResult`` key, whose ``content`` list holds the output. The first ``text`` or ``json``
      block in the list is the output.
    - A dictionary with no ``toolResult`` key, which is the tool's output itself and comes back unchanged.

    A ``json`` value of exactly ``{"items": [...]}`` comes back as the bare list, because Roboto wraps a tool's
    top-level array that way, which the AI model's format does not accept. A tool that itself returned a dictionary
    whose only key is ``items``, holding a list, therefore also comes back as that list.

    Args:
        raw_response: Value of ``AgentToolResultContent.raw_response``. ``None`` returns ``None``.

    Returns:
        The tool's text or JSON output, or ``None`` when ``raw_response`` is ``None`` or empty, its ``toolResult`` is
        not a dictionary holding a ``content`` list, or the list holds no text or JSON output.
    """
    if not raw_response:
        return None
    if "toolResult" not in raw_response:
        return raw_response
    tool_result = raw_response.get("toolResult")
    if not isinstance(tool_result, dict):
        return None
    blocks = tool_result.get("content")
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if "json" in block:
            value = block["json"]
            if isinstance(value, dict) and set(value) == {"items"} and isinstance(value["items"], list):
                return value["items"]
            if isinstance(value, (str, dict, list)):
                return value
            return None
        if "text" in block and isinstance(block["text"], str):
            return block["text"]
    return None


class AgentErrorContent(pydantic.BaseModel):
    """Error block of a message: why Roboto's AI failed to generate the message, or that it was cancelled."""

    content_type: typing.Literal[AgentContentType.ERROR] = AgentContentType.ERROR
    """Kind of content block, always ``AgentContentType.ERROR``."""
    error_message: str
    """Human-readable description of what went wrong."""

    error_code: Optional[str] = None
    """Code naming the kind of error, such as ``"TURN_CANCELLED"``, or ``None`` if Roboto gave none."""


class AgentDeletedContent(pydantic.BaseModel):
    """Placeholder for a content block Roboto removed from the shortened copy of a thread it sends to the AI model.

    Holds nothing but its kind. Roboto shortens a long thread so it fits the AI model's context window, removing
    blocks the AI model no longer needs, such as filler text or a tool use and its result that later messages make
    redundant. A message left with only placeholders gets one ``AgentCompressionFillerContent`` instead, so it keeps
    its place and sender in the conversation. Messages Roboto returns, and the Roboto web app shows, never contain one.
    """

    content_type: typing.Literal[AgentContentType.DELETED] = AgentContentType.DELETED
    """Kind of content block, always ``AgentContentType.DELETED``."""


class AgentCompressionFillerContent(pydantic.BaseModel):
    """Stand-in for the content of a message Roboto emptied in the copy of a thread it sends to the AI model.

    Holds nothing but its kind, and keeps the message's place and sender in that copy. Messages Roboto returns, and
    the Roboto web app shows, never contain one.
    """

    content_type: typing.Literal[AgentContentType.COMPRESSION_FILLER] = AgentContentType.COMPRESSION_FILLER
    """Kind of content block, always ``AgentContentType.COMPRESSION_FILLER``."""


class AgentClientContextEntry(pydantic.BaseModel):
    """What the caller had open when they sent a message, carried as a block on that message.

    Roboto adds it when the caller passes ``client_context`` to :py:meth:`~roboto.ai.agent_thread.AgentThread.start`
    or :py:meth:`~roboto.ai.agent_thread.AgentThread.send`. It has no ``text`` field, so text renderers skip it, and
    Roboto keeps it when it shortens a long thread for the AI model.
    """

    content_type: typing.Literal[AgentContentType.CLIENT_CONTEXT] = AgentContentType.CLIENT_CONTEXT
    """Kind of content block, always ``AgentContentType.CLIENT_CONTEXT``."""

    context: ClientViewingContext
    """What the caller had open, such as datasets, files, and visualizer state."""


AgentContent: typing.TypeAlias = Union[
    AgentTextContent,
    AgentToolUseContent,
    AgentToolResultContent,
    AgentErrorContent,
    AgentDeletedContent,
    AgentCompressionFillerContent,
    AgentClientContextEntry,
]
"""Content block of any kind: one of the content block models.

The models are ``AgentTextContent``, ``AgentToolUseContent``, ``AgentToolResultContent``, ``AgentErrorContent``,
``AgentDeletedContent``, ``AgentCompressionFillerContent`` and ``AgentClientContextEntry``. Each but
``AgentTextContent`` names its kind in ``content_type``.
"""


AGENT_CONTENT_MODEL_BY_TYPE: dict[AgentContentType, type[AgentContent]] = {
    AgentContentType.TOOL_USE: AgentToolUseContent,
    AgentContentType.TOOL_RESULT: AgentToolResultContent,
    AgentContentType.ERROR: AgentErrorContent,
    AgentContentType.DELETED: AgentDeletedContent,
    AgentContentType.COMPRESSION_FILLER: AgentCompressionFillerContent,
    AgentContentType.CLIENT_CONTEXT: AgentClientContextEntry,
}
"""Model of each kind of content block other than text, keyed by its ``content_type``.

Roboto reads this map when it stores a message's content blocks and when it reads them back, so a kind of block
missing from it fails both ways instead of being dropped. ``AgentContentType.TEXT`` is left out because a text block
has no ``content_type`` field.
"""
