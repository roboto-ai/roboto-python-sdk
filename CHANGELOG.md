# Changelog

# 
## No Breaking Changes

## Features Added
  - Release notes generation.

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
  - Added dynamic import guard around `roboto.version` in `requester.py` to fix in-IDE tests from Roboto's development environment (before `version.py` is dynamically generated)
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
