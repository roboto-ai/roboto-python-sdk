# 0.49.0
## Breaking Changes
  - `roboto.fs` is renamed to `roboto.storage`. The top-level re-exports (`roboto.FileService`, etc.) are unchanged.
  - `Dataset.get_summary()` no longer generates a summary as a side effect of reading. It now returns the dataset's existing AI summary, or raises `RobotoNotFoundException` if the dataset has never been summarized; call `Dataset.generate_summary()` to create one. Previously, reading a summary-less dataset implicitly kicked off generation (spending AI credits) — so a read can no longer spend credits, and generation is always explicit.

## Features Added
  - `QueryTarget.Devices` is now a supported search target. Devices can be queried via `RobotoSearch` with filters, sort, and pagination using the same `QuerySpecification` interface as datasets, events, collections, and sessions.

## Bugs Fixed
  - Invoking an action with no input data (for example, running it against just a dataset) no longer fails. `prepare_invocation_input_data` now always writes the input manifest, treating no input (`input_data=None`) the same as empty input; previously it skipped the manifest entirely for no-input invocations, so the action later crashed reading it.
  - `InvocationContext.get_input()` now tolerates a missing or empty input manifest, returning an empty `ActionInput` instead of raising `FileNotFoundError`. A manifest that is absent entirely is logged as a warning, since setup is expected to always write the file.

## Internals
- MCAP and Parquet fetch-and-decode mechanics moved out of `roboto.domain.topics` into two new packages: `roboto.storage` holds the byte-transport (HTTP range streaming, chunk-index prefetch, cache/stream/download selection) and `roboto.formats` holds the format decoding (parsing, field projection, timestamp extraction, table transforms).

