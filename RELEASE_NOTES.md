# 0.39.0
## Internals
  - Removed `MetadataValuesRequest` and `MetadataValuesResponse` from `roboto.query`.
  - Introduced `@experimental` decorator for SDK classes, methods and functions whose functionality is incomplete, preview-only or subject to change or removal without notice.

## Breaking Changes
  - Search and query operations (e.g., `RobotoSearch.find_files()`, `RobotoSearch.find_datasets()`) now use eventually consistent reads for improved performance and scalability. Results may not immediately reflect very recent writes (typically within 1 second). If you create or update data and immediately query for it, you may need to add retry logic. See the [Eventual Consistency Migration Guide](https://docs.roboto.ai/learn/eventual-consistency-migration.html) for complete details, affected endpoints, and code examples.

## Features Added
  - `find_similar_signals` now supports rate-invariant (multi-scale) search via a new `scale` parameter accepting a `Scale` object. Finds a query pattern regardless of how fast or slow it occurs in the target. Each `Match` carries a `scale` field for the matched time-scale factor. Use `Scale(min, max, steps, spacing)` to configure the search grid, or `Scale.any()` for a wide default range. Distances are normalised so existing `max_distance` thresholds apply without adjustment.

## Bugs Fixed
  - Fixed `_derive_session_status` unconditionally returning `CLIENT_TOOL_TURN` for any completed assistant message ending with a tool_use block. Status derivation now requires explicit `client_tool_names` to distinguish client tools from server tools, defaulting to `ROBOTO_TURN` for unrecognised tools.
  - `find_similar_signals` no longer raises when a DataFrame contains non-numeric string values (e.g. header rows). Non-convertible rows are silently dropped and logged at `INFO`; a `ValueError` is raised only if the entire needle or a target topic collapses entirely to non-numeric data.  
  - `Condition.matches()` now correctly handles comparing a `datetime` field in the target dictionary to an ISO 8601 timestamp.

