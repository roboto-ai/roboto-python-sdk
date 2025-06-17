# 0.21.0
## No Breaking Changes

## Features Added
  - Add `summary_id` and `status` to `AISummary`, in support of new async summary generation.
  - Add rich documentation to many `roboto.domain.*` files
  - Add `get_summary()` and `generate_summary()` to `File`, exposing LLM summaries of files.
  - Add `get_summary_sync()` to `Dataset` and `File`, which allows you to await the completion of a summary.
  - Added an optional `print_progress` flag to all `Dataset::upload_*` methods, which allows the caller to suppress TQDM progress bars printing to STDOUT.
  - Added an optional `upload_destination` argument to `Action::invoke` and `Trigger::invoke`. If provided, it tells the Roboto platform where to upload any outputs produced by the invocation.
  - Added an optional `--output-dataset-id` command-line argument to `roboto actions invoke` to let users set an invocation's upload destination to a Roboto dataset.

## Bugs Fixed
  - 

