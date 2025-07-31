# 0.25.0
## No Breaking Changes

## Features Added
  - Updates to `README.md` including list of supported formats
  - Add `StreamingAISummary`, and modify existing `get_summary` and `generate_summary` methods to return it.
  - Initial support for invoking actions on a recurring schedule, via `ScheduledTrigger`.
  - Added `InvocationInput::file_query` and `InvocationInput::topic_query` for concisely specifying invocation inputs using RoboQL queries.

## Bugs Fixed
  - Support both single strings and collections of strings for `message_paths_include`/`message_paths_exclude` parameters in `Topic::get_data`, `MessagePath::get_data`, `Event::get_data`, and their `::get_data_as_df` variants.

