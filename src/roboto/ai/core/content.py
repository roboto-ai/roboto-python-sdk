# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Message-content primitive value types shared across the ``roboto.ai`` layer.

These are the leaf building blocks of :attr:`AgentMessage.content`. They live
here — below both :mod:`roboto.ai.core.record` and :mod:`roboto.ai.goals` —
so the goals layer can reference the raw tool-call blocks (to carry them on a
:data:`GoalResult`) without importing from ``core.record``. That keeps the
``roboto.ai`` import graph a DAG: ``core.content`` depends on nothing in
``roboto.ai``; ``goals`` and ``core.record`` both depend down onto it.
"""

import typing
from typing import Any, Optional, Union

import pydantic

from ...compat import StrEnum


class AgentContentType(StrEnum):
    """Enumeration of different types of content within agent messages.

    Defines the various content types that can be included in agent messages.
    """

    TEXT = "text"
    """Plain text content from users or AI responses."""

    TOOL_USE = "tool_use"
    """Tool invocation requests from the AI assistant."""

    TOOL_RESULT = "tool_result"
    """Results returned from tool executions."""

    ERROR = "error"
    """Error information when message generation fails."""

    DELETED = "deleted"
    """Tombstone marking a content block elided by compression.

    Appears only inside a ``DELETED``-tier compressed variant. Both producers —
    message-tier compression dropping a pure-filler text run, and the
    cross-message deletion pass dropping a whole tool exchange — store their
    output at the DELETED tier, so a message carrying one is always a DELETED-tier
    variant. Never in the verbatim ``original`` thread the SDK and UI read."""

    COMPRESSION_FILLER = "compression_filler"
    """Stand-in block kept in a message the deletion pass emptied entirely.

    A message reduced to nothing but tombstones would break user/assistant
    alternation if it dropped from the payload. Replacing its content with this
    single filler keeps the message — and its role — in place. The model sees it
    as ``<Deleted in compression>``. Only the cross-message deletion pass produces
    it, so it appears only inside a ``DELETED``-tier compressed variant, never in
    the verbatim ``original`` thread the SDK and UI read."""


class AgentTextContent(pydantic.BaseModel):
    """Text content within an agent message."""

    text: str
    """The actual text content of the message."""

    def __str__(self) -> str:
        return self.text


class AgentToolUseContent(pydantic.BaseModel):
    """Tool usage request content within an agent message."""

    content_type: typing.Literal[AgentContentType.TOOL_USE] = AgentContentType.TOOL_USE
    tool_name: str
    """Name of the tool the LLM is requesting to invoke."""
    tool_use_id: str
    """Unique identifier for this tool invocation, used to correlate with its result."""
    input: Optional[dict[str, Any]] = None
    """Parsed tool input parameters chosen by the LLM (provider-agnostic)."""
    raw_request: Optional[dict[str, Any]] = None
    """Raw, unparsed request payload for this tool invocation."""


class AgentToolResultContent(pydantic.BaseModel):
    """Tool execution result content within an agent message."""

    content_type: typing.Literal[AgentContentType.TOOL_RESULT] = AgentContentType.TOOL_RESULT
    tool_name: str
    """Name of the tool that was executed."""
    tool_use_id: str
    """Identifier of the tool invocation this result corresponds to."""
    runtime_ms: int
    """Wall-clock execution time of the tool in milliseconds."""
    status: str
    """Outcome of the tool execution (e.g. 'success', 'error')."""
    raw_response: Optional[dict[str, Any]] = None
    """Raw, unparsed response payload from tool execution."""


class AgentErrorContent(pydantic.BaseModel):
    """Error content within an agent message.

    Used when message generation fails due to an error or is cancelled by the user.
    """

    content_type: typing.Literal[AgentContentType.ERROR] = AgentContentType.ERROR
    error_message: str
    """User-friendly error message describing what went wrong."""

    error_code: Optional[str] = None
    """Optional error code for programmatic handling."""


class AgentDeletedContent(pydantic.BaseModel):
    """Tombstone for a content block removed by compression.

    Carries no payload — its presence records that a block once occupied this
    slot, and it converts to ``None`` at the Bedrock boundary so the block drops
    from the LLM payload. Produced when compression drops a block — a pure-filler
    text run at message compression, or a whole redundant tool exchange in the
    cross-message deletion pass — and stored only at the ``DELETED`` tier, so a
    message carrying one is always a DELETED-tier variant. A message reduced to
    nothing but tombstones does not drop: it is replaced with a single
    :class:`AgentCompressionFillerContent` so it keeps its role and turn. The
    verbatim ``original`` thread (what the SDK and UI render) never contains one.
    """

    content_type: typing.Literal[AgentContentType.DELETED] = AgentContentType.DELETED


class AgentCompressionFillerContent(pydantic.BaseModel):
    """Filler standing in for a message the compression deletion pass emptied.

    Carries no payload. A message reduced to nothing but tombstones keeps this
    single block instead of an empty content list, so it stays in the Bedrock
    payload at its original role and turn alternation survives without
    relocating content. The Bedrock boundary renders it as
    ``<Deleted in compression>``. Produced only by the compression deletion pass
    and stored only at the ``DELETED`` tier; the verbatim ``original`` thread
    (what the SDK and UI render) never contains one.
    """

    content_type: typing.Literal[AgentContentType.COMPRESSION_FILLER] = AgentContentType.COMPRESSION_FILLER


AgentContent: typing.TypeAlias = Union[
    AgentTextContent,
    AgentToolUseContent,
    AgentToolResultContent,
    AgentErrorContent,
    AgentDeletedContent,
    AgentCompressionFillerContent,
]
"""Type alias for all possible content types within agent messages."""


AGENT_CONTENT_MODEL_BY_TYPE: dict[AgentContentType, type[AgentContent]] = {
    AgentContentType.TOOL_USE: AgentToolUseContent,
    AgentContentType.TOOL_RESULT: AgentToolResultContent,
    AgentContentType.ERROR: AgentErrorContent,
    AgentContentType.DELETED: AgentDeletedContent,
    AgentContentType.COMPRESSION_FILLER: AgentCompressionFillerContent,
}
"""The model class for each JSON-serialized content type, keyed by discriminator.

Excludes :attr:`AgentContentType.TEXT`, whose payload is persisted as raw text
rather than a serialized model. Every other member of :data:`AgentContent`
carries a ``content_type`` discriminator and round-trips through
``model_dump_json`` / ``model_validate_json``; driving both serialization
directions off this one map keeps them symmetric, so a member added to the union
without a home here fails loudly instead of being silently dropped on write or
reconstructed without its payload on read."""
