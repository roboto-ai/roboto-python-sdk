# 0.29.0rc0
## Features Added
  - Added utilities to initialize an invocation's runtime environment in the SDK to better support action development and local testing.

## Bugs Fixed
  - Fixed imports in `Org` docstring code examples.
  - Removed dependence on environment variables from `InvocationContext` to better support action development and local testing.

## Chores
  - Move `ActionConfig` (the model used to define and validate file-based Action configuration) from the CLI source tree to `roboto.domain.actions` to better support action development and local testing.

