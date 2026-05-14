# 0.44.2
## Bugs Fixed
  - `AgentSession.submit_client_tool_results` now advances the session's local status to `ROBOTO_TURN` on success. Previously, after a turn that mixed server and client tools, the local status stayed on `CLIENT_TOOL_TURN`, so `run()` re-dispatched the same client tools and re-POSTed their results; the duplicate POST raised `RobotoInvalidRequestException` from the server.

