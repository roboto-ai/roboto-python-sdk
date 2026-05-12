# 0.44.0
## Breaking Changes
  - `RobotoContextTooLongException` no longer accepts `estimated_tokens` and `max_tokens` constructor arguments, no longer exposes `estimated_tokens` / `max_tokens` properties, and no longer extends the `to_dict()` payload with those fields. The exception now serializes as the standard `{error_code, message}` shape like every other `RobotoDomainException`. The internal heuristic estimate and the model's context limit were never billing-grade values and were not consumed by any in-tree caller; they remain visible in CloudWatch failure logs (see `BedrockLLMBackbone`). Callers that need usage telemetry will get it through a separate, dedicated channel rather than by introspecting the error.

## Features Added
  - **Sessions are queryable (experimental):** Sessions join datasets, files, topics, and events as a queryable resource. You can sort and paginate listings server-side by start time or duration. Higher-level query helpers in the SDK will arrive in a follow-up release. Sessions remain experimental, and Roboto enables access per organization; contact us to opt your org in.

## Bugs Fixed
  - Concurrent `Topic.get_data_as_df` calls no longer race on cache-directory creation (which previously raised `FileExistsError` from `mkdir`) or on Parquet downloads. Within a process, downloads of the same representation are deduped via a per-path lock; across processes, an atomic temp-file-plus-rename write guarantees readers never observe a partial file.

