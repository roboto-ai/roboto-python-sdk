# 0.33.0
## Features Added
  - Expanded `RobotoLLMContext` to include visualizer state and a misc context block for generic use during experimental feature development.
  - `roboto actions invoke-local` now automatically caches downloaded files between invocations. This eliminates the need to manage workspace state manually when iterating on action development. As such, the `--preserve-workspace` flag is now removed.
  - Added `roboto cache` commands (`where`, `size`, `clear`) to inspect and manage Roboto's local file cache.

## Bugs Fixed
  - Trigger conditions now correctly support substring checks against string-valued fields using `CONTAINS` or `NOT_CONTAINS`, e.g. `dataset.name CONTAINS "foo"`.
  - Added first class `Error` content type to `ChatMessage`, and expand data model to handle errors and cancellations.
  - Fixed an issue where action invocations with multi-dataset input could silently overwrite files when different datasets contained files with the same relative path. Files from multiple datasets are now stored in dataset-specific subdirectories.

