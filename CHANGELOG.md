# Changelog

# 0.25.1
## No Breaking Changes

## Features Added
  - Allow `device_id' to be specified explicitly when uploading, importing, or updating files.
  - Change `Dataset::upload_file` to return a lazy-resolving `File` handle vs. returning `None`.

## Bugs Fixed
  - 

# 0.25.0
## No Breaking Changes

## Features Added
  - Updates to `README.md` including list of supported formats
  - Add `StreamingAISummary`, and modify existing `get_summary` and `generate_summary` methods to return it.
  - Initial support for invoking actions on a recurring schedule, via `ScheduledTrigger`.
  - Added `InvocationInput::file_query` and `InvocationInput::topic_query` for concisely specifying invocation inputs using RoboQL queries.

## Bugs Fixed
  - Support both single strings and collections of strings for `message_paths_include`/`message_paths_exclude` parameters in `Topic::get_data`, `MessagePath::get_data`, `Event::get_data`, and their `::get_data_as_df` variants.

# 0.24.1
## No Breaking Changes

## Features Added
  - Allow `device_id` to be specified explicitly when creating or updating datasets.
  - Extended first-class support for Parquet-based recording data: `Topic::get_data`, `MessagePath::get_data`, `Event::get_data`, and their `::get_data_as_df` variants now work with data ingested from Parquet files (previously raised `NotImplementedError`).
  - Addition of `MessagePathRecord::path_in_schema`, `MessagePathRecord::source_path`, and `MessagePathRecord::parents`
  for use accessing fields on topic data without heuristically assuming all message paths are or can be dot separated.

## Bugs Fixed

# 0.23.1
## No Breaking Changes

## Features Added
  - Extended `RobotoPrincipal` to include devices + invocations, and added methods to convert to and from a canonical string format.
  - Add `RobotoSearch::for_roboto_client` and `RobotoClient.for_profile` to simplify code snippets for users with multiple profiles.

# 0.23.0
## No Breaking Changes

## Features Added
  - Improved help text for various Roboto CLI commands.
  - Add X-Roboto-Api-Version to all SDK requests.

# 0.22.1
## No Breaking Changes

## Features Added
  - Added `File::import_one` which automatically looks up the size of S3 files + verifies they exist.

# 0.22.0
## No Breaking Changes

## Features Added
  - Added `RobotoPrincipal`, which generalized providing a user or org to various platform APIs.
  - Added `Dataset::create_if_not_exists` to simplify a common pattern from read only BYOB file import scenarios.
  - Added `create_directory` method and docstring to `Dataset`, which allows you to create a directory in a dataset, including intermediate directories.
  - Comprehensive docstring updates for `roboto.domain.topics` module following Google-style format with Examples sections for all public methods, enhanced Args/Returns/Raises documentation, and improved cross-references.
  - Comprehensive docstring updates for `roboto.domain.actions` module following Google-style format with Examples sections for all public methods, detailed Args/Returns/Raises documentation, and improved cross-references. All Action, Invocation, and Trigger classes now have extensive documentation with practical examples.
  - Comprehensive docstring updates for `roboto.domain.users` and `roboto.domain.orgs` modules following Google-style format with Examples sections for all public methods, field docstrings for Pydantic models, and enhanced Args/Returns/Raises documentation. All User, Org, and OrgInvite classes now have extensive documentation with practical examples.
  - Comprehensive docstring updates for `roboto.domain.events` module following Google-style format with Examples sections for all public methods, detailed Args/Returns/Raises documentation, and improved cross-references. All Event classes now have extensive documentation with practical examples using proper Roboto ID conventions.
  - Comprehensive docstring updates for `roboto.domain.devices` module following Google-style format with Examples sections for all public methods, enhanced Args/Returns/Raises documentation, field docstrings for Pydantic models, and improved cross-references. All Device classes now have extensive documentation with practical examples for device registration, token management, and device operations.
  - Comprehensive docstring updates for `roboto.domain.comments` module following Google-style format with Examples sections for all public methods, field docstrings for Pydantic models, and enhanced Args/Returns/Raises documentation. All Comment classes now have extensive documentation with practical examples for creating, retrieving, updating, and deleting comments on platform entities.
  - Added placeholder implementation for working with topic data ingested as Parquet in the SDK. Attempting to fetch Parquet-ingested data currently raises a `NotImplementedError`.
  - Added `roboto datasets import-external-file` CLI command for importing files from customer S3 buckets into Roboto datasets.

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

# 0.20.1
## No Breaking Changes

## Features Added
  - [CLI] Actions that don't take inputs can now be invoked from the command-line by leaving out the arguments `--dataset-id` and `--input-data`. For actions that take inputs, both arguments must be provided as before.
  - Add subset of audit fields to `RepresentationRecord` to enable determination of "latest" representation of topic data.
  - Add ability to pass `caller_org_id` to `File::import_batch`, which is necessary to exercise bring-your-own-bucket file imports for users belonging to multiple orgs.
  - Added a method to Dataset to list directories. Added metadata properties to `DirectoryRecord`. Added the `S3Directory` storage type to `FileStorageType`. Added `fs_type`, `name`, and `parent_id` to `FileRecord`. 

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

# 0.19.0
## Breaking Changes
  - The list of tuples returned by `ActionInput::files` now has a `File` as its first element rather than a `FileRecord`. This gives action writers access to more powerful file operations, such as retrieving topics.

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

# 0.16.0
## No Breaking Changes

## Features Added
  - Updated `ingestion_status` to allow a `PartlyIngested` state, and made `ingestion_status` an optional parameter to `file.update` calls.
  - Added `CHANGELOG.md`.
