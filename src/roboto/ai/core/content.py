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
``roboto.ai`` import graph a DAG: ``core.content`` depends only on
:mod:`roboto.ai.core.context` (itself a leaf with no ``roboto.ai`` imports of
its own); ``goals`` and ``core.record`` both depend down onto ``core.content``.
"""

import typing
from typing import Any, Optional, Union

import pydantic

from ...compat import StrEnum
from .context import ClientViewingContext


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

    CLIENT_CONTEXT = "client_context"
    """What the caller was looking at when they composed the message this block sits on.

    Superseded shape: the same payload used to be persisted as a whole ROBOTO-role message whose
    text was a ``<ctx>...</ctx>`` marker (ENG-2185). Readers still accept that form for threads
    written before this type existed; nothing emits it any more."""

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
    payload: Optional[Union[str, dict[str, Any], list[Any]]] = None
    """What the tool returned: free-form text, or a JSON object or array of structured data.

    Independent of any model provider's wire format (provider-agnostic, like
    :py:attr:`AgentToolUseContent.input`). ``None`` on results written before this field
    existed; use :py:meth:`resolve_payload` to read old and new results uniformly."""
    raw_response: Optional[dict[str, Any]] = None
    """Legacy provider-formatted response envelope (Bedrock ``toolResult`` shape).

    Kept so results written before :py:attr:`payload` existed remain readable; deprecated
    for new readers, who should call :py:meth:`resolve_payload` instead of parsing this
    field.

    Populated only where the server-side envelope is in scope: threads read over the
    API arrive with this field stripped (and, for legacy rows, with :py:attr:`payload`
    synthesized from it server-side before the strip), so API/SDK readers should not
    expect it."""

    def resolve_payload(self) -> Optional[Union[str, dict[str, Any], list[Any]]]:
        """Return what the tool returned, whichever field carries it.

        Prefers :py:attr:`payload`. Results written before that field existed carry only
        the legacy envelope, from which the equivalent value is reconstructed via
        :py:func:`synthesize_tool_result_payload`.

        Returns:
            The tool's text or JSON output, or ``None`` when neither field carries a
            recognizable value.
        """
        if self.payload is not None:
            return self.payload
        return synthesize_tool_result_payload(self.raw_response)


def synthesize_tool_result_payload(
    raw_response: Optional[dict[str, Any]],
) -> Optional[Union[str, dict[str, Any], list[Any]]]:
    """Reconstruct a tool result's text or JSON output from its legacy response envelope.

    Reads both shapes tool results were persisted with before
    :py:attr:`AgentToolResultContent.payload` existed:

    - The provider envelope: a ``toolResult`` object whose ``content`` list carries the
      output as a ``text`` or ``json`` block, followed at most by image attachments.
    - A bare output dict with no ``toolResult`` key at all — the shape client-submitted
      results and fabricated skill-invocation results persisted, where the dict *is* the
      tool's output and is returned as the payload verbatim.

    A ``json`` value of the exact single-key form ``{"items": [...]}`` — the wrapper
    applied because the model provider rejected a top-level array — is unwrapped back to
    the bare array. This unwrap is heuristic: a tool that genuinely returned a
    single-key ``{"items": [...]}`` dict is indistinguishable from the wrapper here and
    synthesizes as the bare array. Writers that still hold the tool's true return value
    should persist :py:attr:`AgentToolResultContent.payload` directly rather than round-
    tripping through this function.

    Args:
        raw_response: The legacy value, as carried by
            :py:attr:`AgentToolResultContent.raw_response`. ``None`` is accepted.

    Returns:
        The tool's text or JSON output, or ``None`` when the value is absent, is a
        malformed envelope, or is an envelope carrying no text or JSON block.
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


class AgentClientContextEntry(pydantic.BaseModel):
    """The caller's attached viewing context, carried on their own message.

    Replaces a ``<ctx>{json}</ctx>`` marker persisted as a separate ROBOTO-role message. That shape
    made every consumer regex a JSON blob back out of prose it had serialized itself -- four
    parsers across two languages -- and relied on the ROBOTO role to keep the marker out of the
    chat view. It also put the context on a non-USER message, which the compression deletion pass
    collapses wholesale inside a resolved task's interior, so the context silently disappeared from
    compressed history.

    As a block on the user's own message it is a typed field, invisible to text renderers (no
    ``text`` field), and safe from that collapse -- USER turns are never dropped.
    """

    content_type: typing.Literal[AgentContentType.CLIENT_CONTEXT] = AgentContentType.CLIENT_CONTEXT

    context: ClientViewingContext
    """What the caller had open: attached datasets, files, and visualizer state."""


AgentContent: typing.TypeAlias = Union[
    AgentTextContent,
    AgentToolUseContent,
    AgentToolResultContent,
    AgentErrorContent,
    AgentDeletedContent,
    AgentCompressionFillerContent,
    AgentClientContextEntry,
]
"""Type alias for all possible content types within agent messages."""


AGENT_CONTENT_MODEL_BY_TYPE: dict[AgentContentType, type[AgentContent]] = {
    AgentContentType.TOOL_USE: AgentToolUseContent,
    AgentContentType.TOOL_RESULT: AgentToolResultContent,
    AgentContentType.ERROR: AgentErrorContent,
    AgentContentType.DELETED: AgentDeletedContent,
    AgentContentType.COMPRESSION_FILLER: AgentCompressionFillerContent,
    AgentContentType.CLIENT_CONTEXT: AgentClientContextEntry,
}
"""The model class for each JSON-serialized content type, keyed by discriminator.

Excludes :attr:`AgentContentType.TEXT`, whose payload is persisted as raw text
rather than a serialized model. Every other member of :data:`AgentContent`
carries a ``content_type`` discriminator and round-trips through
``model_dump_json`` / ``model_validate_json``; driving both serialization
directions off this one map keeps them symmetric, so a member added to the union
without a home here fails loudly instead of being silently dropped on write or
reconstructed without its payload on read."""
