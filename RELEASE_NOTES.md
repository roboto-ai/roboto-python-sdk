# 0.38.0
## Features Added
  - Renamed the `Chat*` type family to `Agent*` across `roboto.ai.core`: `AgentSession`, `AgentMessage`, `AgentRole`, `AgentSessionStatus`, `AgentMessageStatus`, `AgentContentType`, and their content types (`AgentTextContent`, `AgentToolUseContent`, `AgentToolResultContent`, `AgentErrorContent`). The previous `Chat*` names remain as aliases.
  - Added `ClientToolSpec` model for declaring client-side tools.
  - Added `SubmitToolResultsRequest` model for returning client-executed tool results.
  - Added `CLIENT_TOOL_TURN` status to `AgentSessionStatus`, signaling that the session awaits client-side tool execution.
  - Renamed `chat_id` to `session_id` in `AgentSession`, with `chat_id` retained as a backwards-compatible computed alias in API responses.

## Internals
  - Moved canonical type definitions from `roboto.ai.chat` to `roboto.ai.core`. The `roboto.ai.chat` module re-exports all types for backwards compatibility.
  - Renamed the `ChatEvent` streaming event types to `AgentEvent` (`AgentStartTextEvent`, `AgentTextDeltaEvent`, `AgentTextEndEvent`, `AgentToolUseEvent`, `AgentToolResultEvent`). The previous `Chat*` event names remain as aliases.

## Bugs Fixed
  - `RobotoClient` HTTP retry now handles DNS resolution failures on all platforms, bare `ConnectionResetError` during response reads, and additional `ConnectionError` subclasses (`ConnectionRefusedError`, `ConnectionAbortedError`, `BrokenPipeError`) on idempotent requests.

