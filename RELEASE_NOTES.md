# 0.46.0
## Breaking Changes
  - **Name swap:** `AgentThread` is the new name for the wrapper class previously called `AgentSession`, and the matching record is `AgentThreadRecord` (previously `AgentSessionRecord`). This continues the 0.41.0 `Chat → AgentSession` rename. Update imports:
    - `from roboto.ai import AgentThread` (was `AgentSession`)
    - `from roboto.ai.agent_thread import ...` (was `roboto.ai.agent_session`)
    - `AgentThreadRecord` (was `AgentSessionRecord`)
    - `AgentThreadDelta` / `AgentThreadStatus` / `AgentThreadGoalRecord` (was `AgentSession*`)
    - `ThreadVisibility` (was `SessionVisibility`)
    - `StartAgentThreadRequest` (was `StartAgentSessionRequest`)
    - `ForkAgentThreadRequest` (was `ForkChatRequest`)
    - `LaunchAgentRequest` (was `InvokeAgentRequest`)
    The SDK surface keeps no `AgentSession*` aliases; update imports in the same release.
  - `AgentThreadRecord.thread_id` replaces `AgentSessionRecord.session_id`. The constructor still accepts the legacy `session_id` and `chat_id` spellings via Pydantic `AliasChoices`, so `AgentThreadRecord(session_id=..., ...)` still works; the canonical Python attribute is `record.thread_id`, and `record.session_id` raises `AttributeError`. The `chat_id` computed-field alias is gone; pre-v2026_05_20 callers still receive `session_id` and `chat_id` in API response bodies via a server-side transform. `forked_from_session_id` becomes `forked_from_thread_id` with the same input-alias compatibility.
  - `Agent.invoke()` is renamed to `Agent.launch()`, and `InvokeAgentRequest` to `LaunchAgentRequest`. The route path moves from `POST /v1/ai/agents/<agent_id>/invoke` to `…/launch`. `Invocation` continues to mean an action run; `launch` now applies to starting an agent thread. The legacy `/invoke` URL was removed outright (it was a feature-flagged developer-only preview with no in-the-wild callers); upgrade `Agent.invoke()` call sites to `Agent.launch()`.

## Features Added
  - `RobotoApiVersion.v2026_05_20` pins the cutover where `chat_id` and `session_id` become `thread_id` on the wire, `/v1/ai/chats` becomes `/v1/ai/threads`, and agent `invoke` becomes `launch`. Clients on older API versions continue to receive `session_id` (and `chat_id`) in response bodies via a server-side transform and may keep calling the legacy `/v1/ai/chats` paths, which remain registered as aliases on the same handlers. Clients on v2026_05_20 or newer must use `/v1/ai/threads`; the legacy `/chats` paths return `RobotoDeprecatedException` (HTTP 400) for v2026_05_20+ callers so the entire legacy alias block can be deleted in one diff once pre-v2026_05_20 leaves the support window.
  - Experimental: new `AgentThreadSubject` pydantic model under `roboto.ai.agent_thread`. The service appends one subject row per dataset or file an agent thread references via a goal target or `ClientViewingContext`, and `POST /v1/ai/threads/search` gains a `subject_id` filter that returns threads referencing a given association id (e.g. `ds_xxx`). The SDK exports the model now; dedicated SDK search helpers are a follow-up.

