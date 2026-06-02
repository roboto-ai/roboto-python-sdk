# 0.47.0
## Features Added
  - New `roboto.experimental` namespace for SDK APIs whose shape may change before stabilizing.
  - `RobotoSearch.find_sessions` (experimental) now supports searching sessions by their metrics with the `metric.<name>` query field.

## Bugs Fixed
  - Client-side tools dispatched by `AgentThread.run()` now receive only their declared parameters. The server adds an internal `_compression_intent` field to every tool's input schema; `run()` previously passed it to the callback, raising `TypeError` for any strict-signature client tool (the only kind `ClientTool.from_function` produces).

## Internals
  - `Topic.get_data` and `Topic.get_data_as_df` are now faster.

