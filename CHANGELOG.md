# Changelog

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

# 0.20.1
## No Breaking Changes

## Features Added
  - [CLI] Actions that don't take inputs can now be invoked from the command-line by leaving out the arguments `--dataset-id` and `--input-data`. For actions that take inputs, both arguments must be provided as before.
  - Add subset of audit fields to `RepresentationRecord` to enable determination of "latest" representation of topic data.
  - Add ability to pass `caller_org_id` to `File::import_batch`, which is necessary to exercise bring-your-own-bucket file imports for users belonging to multiple orgs.
  - Added a method to Dataset to list directories. Added metadata properties to `DirectoryRecord`. Added the `S3Directory` storage type to `FileStorageType`. Added `fs_type`, `name`, and `parent_id` to `FileRecord`. 

## Bugs Fixed

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

# 0.19.0
## Breaking Changes
  - The list of tuples returned by `ActionInput::files` now has a `File` as its first element rather than a `FileRecord`. This gives action writers access to more powerful file operations, such as retrieving topics.

## Features Added

## Bugs Fixed

# 0.18.0
## Breaking Changes
  - The `input_data` property of `Invocation` now returns an `Optional[InvocationInput]`. It used to return a `list` of file name patterns.

## Features Added
  - Added `extra_headers_provider` param to `HttpClient` which accepts a callback which generates headers on every HTTP request at runtime. This was added so we ourselves can send internal trace IDs.
  - Added getters for `created`, `created_at`, `modified`, `modified_at` to `Dataset`, `File` and other related entities, eliminating the need to access them via `.record`.
  - Enhanced `Dataset::download_files` to return both `FileRecord` objects and their corresponding local save paths.
  - Added `ActionRuntime::get_input` method to inspect resolved input data references during Action execution.
  - Introduced `InvocationInput` - a richer way of specifying inputs to action invocations which will not be limited to dataset file paths. Full platform support will be delivered in stages.
  - Introduced `Layouts` - a way to create a saved arrangement of panels for visualizing data in Roboto.
  - Added `TriggerRecord::causes`, `CreateTriggerRequest::causes`, and `UpdateTriggerRequest::causes` to allow triggers to filter which evaluation causes they respond to.
  - Added `TriggerEvaluationCause::FileIngest` to allow triggers to respond to when a file is marked as `IngestionStatus::Ingested`.

## Bugs Fixed
  - Added dynamic import guard around `roboto.version` in `requester.py` to fix in-IDE tests from Roboto's development environment (before `version.py` is dynamically generated).
  - Don't reject API requests that contain extra fields. This enables backwards-compatibility with outdated SDK builds and forwards-compatibility for adding new fields to the SDK independent of our server release cycle.

# 0.17.0
## No Breaking Changes

## Features Added
  - Reduced the scope of `ingestion_status` updates to make the feature more usable in ingestion actions.

## Bugs Fixed

# 0.16.0
## No Breaking Changes

## Features Added
  - Updated `ingestion_status` to allow a `PartlyIngested` state, and made `ingestion_status` an optional parameter to `file.update` calls.
  - Added `CHANGELOG.md`.

## Bugs Fixed
