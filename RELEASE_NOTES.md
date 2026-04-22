# 0.41.0
## Breaking Changes
  - **Name swap: `AgentSession` now refers to the wrapper class (previously called `Chat`), not the Pydantic record.** On 0.39.0 `AgentSession` was the record type at `roboto.ai.core.AgentSession`; in this release the record is renamed to `AgentSessionRecord` and `AgentSession` is reused as the wrapper class. Code that followed 0.39.0's guidance and did `AgentSession(session_id=..., messages=...)` will now hit a wrapper-class constructor with a completely different signature. Update to `AgentSessionRecord(...)` when constructing the record directly.
  - Renamed `Chat` to `AgentSession` and dropped all `Chat*` backwards-compatibility aliases on the Python SDK surface. Update imports:
    - `from roboto.ai import AgentSession` (was `Chat`)
    - `from roboto.ai.agent_session import ...` (was `roboto.ai.chat`)
    - `AgentSessionRecord` (was `ChatRecord`)
    - `AgentMessage` / `AgentRole` / `AgentSessionStatus` / ... (was `ChatMessage` / `ChatRole` / `ChatStatus` / ...)
    - `AgentEvent` / `AgentTextDeltaEvent` / ... (was `ChatEvent` / `ChatTextDeltaEvent` / ...)
    - `StartAgentSessionRequest` (was `StartChatRequest`)
    - `AgentToolDetailResponse` (was `ChatToolDetailResponse`)

    The HTTP API is unchanged: URLs still live under `/v1/ai/chats/...` and responses still include `chat_id` for wire compatibility.
  - Consolidated the `AgentSession` control-flow surface down to two methods: `run()` (driver — auto-dispatches registered client-side tools until user turn; takes a single `on_event` callback) and `events()` (observer — yields `AgentEvent` objects until the session pauses, no auto-dispatch). Removed `await_user_turn()`, `stream()`, and `stream_events()` — their behaviors are composable from `run` / `events`.
  - Removed `is_user_turn()`, `is_client_tool_turn()`, and `is_roboto_turn()` inspectors — compare `session.status` against `AgentSessionStatus.XXX` directly when branching is needed.
  - Removed the `chat_id` property on the wrapper class; use `session_id`. (`chat_id` remains on `AgentSessionRecord` as a computed alias for wire compatibility.)

## Features Added
  - `AgentSession.start()` / `send()` / `send_text()` now accept `client_tools=[ClientTool | ClientToolSpec]` to register client-side tools the agent can invoke.
  - New `AgentSession.run()` drives the session until user turn, auto-dispatching registered client-side tools and optionally emitting progress via an `on_event` callback that receives typed `AgentEvent` objects (text deltas, tool uses, tool results, errors).
  - New `AgentSession.events()` yields `AgentEvent` objects as the agent generates, without auto-dispatching; callers observe and handle tool-dispatch manually by calling `submit_client_tool_results()` between `events()` loops.
  - New `ClientTool` class and `@client_tool` decorator wrap a Python callable as a client-side tool; name, description, and JSON Schema are inferred from the function's `__name__`, docstring, and type hints. Per-parameter descriptions are parsed from the docstring's `Args:` section (Google style); `typing.Annotated[T, pydantic.Field(description=...)]` and `param: T = pydantic.Field(description=...)` take precedence over the docstring when both are present. The tool description is the summary/body of the docstring — the `Args:` section is stripped out.
  - New `AgentSession.submit_client_tool_results(results, client_tools=...)` for manual tool-result submission when callers want to drive dispatch themselves.
  - New `AgentSession.unregister_client_tool(name)` removes a previously registered callback; symmetric with `register_client_tool`. The tool remains declared client-side on the session so a subsequent `tool_use` produces an error result rather than being silently skipped.
  - `AgentToolUseEvent` now carries the parsed `input` dict so progress hooks and observers can see the arguments the model chose.
  - `AgentToolResultEvent` now carries the raw `output` dict and `runtime_ms` alongside `success`, so observers can display what a tool actually returned (previously only a success bool was exposed).
  - New `AgentErrorEvent` fires from `events()` when an assistant message carries `AgentErrorContent` (for example, a failed or cancelled generation), so callers observing the event stream can detect failures without inspecting `session.messages` afterward.
  - `AgentSession.start()` validates that every initial message has role `USER` or `ASSISTANT` (seeded history); passing `ROBOTO` or `SYSTEM` raises `ValueError` up front rather than producing an opaque server rejection.

## Bugs Fixed
  - `AgentSession.events()` no longer emits spurious `AgentStartTextEvent` / `AgentTextEndEvent` pairs while a message is still generating across multiple polls. A text span now stays open until the underlying message reaches a terminal status (or a non-text content block arrives within the same message), so a streaming assistant response produces a single `Start → Delta* → End` sequence instead of one per poll.
  - `AgentSession.run()` no longer submits a client-side error `tool_result` for server-issued `tool_use_id`s when a mixed server+client turn lands before the server has mirrored its own tool result. The dispatcher now filters to tool names declared as client-side on the session; server tools are left for the server to answer. Without this filter, two `tool_result`s for the same `tool_use_id` could race, producing a Bedrock-invalid turn.

