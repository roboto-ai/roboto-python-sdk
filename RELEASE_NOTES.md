# 0.28.0
## Features Added
  - Rename `ActionRuntime` to `InvocationContext` to better reflect that this utility provides context for the current action invocation. For backward compatibility, `ActionRuntime` remains available as a deprecated alias and will be removed in a future release. Update your code to use `InvocationContext.from_env()` instead of `ActionRuntime.from_env()`.
  - `InvocationContext::get_optional_parameter` enables specifying a default value for a parameter instead of raising an `ActionRuntimeException` if the parameter is not provided (as done by `InvocationContext::get_parameter`).
  - `ActionInputResolver` is now available in the SDK to support local testing and debugging of actions. This utility resolves invocation inputs (files, topics) the same way the platform does, enabling developers to test their actions outside of the Roboto runtime environment before deployment.

## Bugs Fixed
  - Added a clarification to the documentation for `Dataset::get_topics` and `Topics::get_by_dataset`

