# 0.66.0
## Features Added
  - `RobotoClientToolResultsNotPendingException`, a `RobotoConflictException` you can import from `roboto.exceptions`, is raised when `AgentThread.submit_client_tool_results` sends results to a thread that no longer waits on them. Its `reason` is `answered_elsewhere` when another submission answered the same tool calls first, or `turn_ended` when the turn was stopped or expired before any submission answered them. Sending an accepted submission again has no effect.
  - A thread waiting on client tool results stops waiting five minutes after its last sign of life: each pending tool call gets an error result and the model continues. The Roboto web app keeps its turns alive while they run; the SDK does not, so a client tool you run through `AgentThread` that takes longer than five minutes may find its turn already ended, and its results are then refused with `RobotoClientToolResultsNotPendingException`.
  - `SendMessageRequest`, `StartAgentThreadRequest` and `SubmitToolResultsRequest` gain `page_state`, which the Roboto web app sends to tell the AI what its browser tab shows, such as the board or the session visualizer on screen. SDK callers leave it unset: the AI keeps reading `client_context`.

## Bugs Fixed
  - `AgentThread.run` answers a tool call whose name starts with `client_` but that your session did not declare with an error result, instead of leaving the thread waiting for it.

