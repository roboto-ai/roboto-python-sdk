# 0.29.0rc1
## Features Added
  - Added utilities to initialize an invocation's runtime environment in the SDK to better support action development and local testing.
  - `roboto actions invoke-local` command enables local invocation of actions from either local directories (e.g., actions created with `roboto actions init`) or actions fetched from the Roboto platform.
  - Action invocation from the CLI now supports query-based input specifications (file queries and topic queries) in addition to the legacy dataset+file-paths model. For example: `roboto actions invoke --topic-query "msgpaths[cpuload.load].max > 0.9" <ACTION_NAME>`. See `roboto actions invoke --help` or `roboto actions invoke-local --help` for more details.

## Bugs Fixed
  - Fixed imports in `Org` docstring code examples.
  - Removed dependence on environment variables from `InvocationContext` to better support action development and local testing.

## Chores
  - Move `ActionConfig` (the model used to define and validate file-based Action configuration) from the CLI source tree to `roboto.domain.actions` to better support action development and local testing.

