# 0.42.0
## Features Added
  - New `AnalysisScope` in `roboto.ai.core` captures a time window (`start_time` / `end_time`, nanoseconds since the Unix epoch) that scopes which data the agent's tools may consider. `AgentSession.start()`, `.send()`, and `.send_text()` accept an `analysis_scope=` kwarg; on `start` it attaches the scope to the session, on `send`/`send_text` an explicit value replaces the session's current scope (omitting the kwarg leaves it untouched). The scope is persisted on the session and delivered to every tool invocation on the server side. The `analyze_topic` tool honors the scope today by clamping topic data to the window; other tools will opt in as they adopt.
  - New `RobotoFeatureNotAvailableException` in `roboto.exceptions`, raised when an API call targets a route gated by a feature flag that is not enabled for the caller.

