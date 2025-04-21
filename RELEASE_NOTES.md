# 0.20.0
## No Breaking Changes

## Features Added
  - Support has been added for topic inputs to action invocations, via `InvocationInput.topics`. Action writers can access the topics via `ActionInput.topics`.
  - Added the `requires_downloaded_inputs` optional flag to `Action::create` and `Action::update`. It controls whether an action invocation's inputs will be available in its working directory before business logic runs. This is true by default.
  - Added getters to `Action` for `description`, `short_description`, `tags`, `metadata`, `published` and `requires_downloaded_inputs`.
  - `Dataset::get_topics` now has optional arguments to `include` or `exclude` topics by name, similar to `File::get_topics`.
  - Added `FileDownloader` to simplify the task of downloading multiple files, for instance from search results.
  - Added `CanonicalDataType.Timestamp` to support identifying `MessagePath`s that should be interpreted as time elapsed since the Unix epoch.
  - Added `RepresentationStorageFormat.PARQUET` in support of progress towards accepting Parquet files as a first-class ingest-able format (in addition to bag, db3/yaml, mcap, ulg, journalctrl, csv and others).

## Bugs Fixed

