# 0.36.0rc0
## Breaking Changes
  - `MessagePath.parents()` now requires a `list[str]` (`path_in_schema`) instead of a dot-delimited `str`. This reflects the shift from ambiguous dot-separated paths to explicit schema path components for correct handling of nested and dot-containing field names. If you were calling `MessagePath.parents("pose.position.x")`, update to `MessagePath.parents(["pose", "position", "x"])`. Passing a string now raises a `TypeError` with guidance on how to migrate.
  - `MessagePath.parts()` has been removed. Use `MessagePathRecord.path_in_schema` directly to obtain path components.

## Features Added
  - Introduced `QueryContentMode`, allowing search endpoints to return Roboto entities with or without custom metadata. Initial support is for dataset queries in particular, since datasets can store large amounts of `metadata`, which is known to affect search latency and response size. More entity types will be supported in the future.
  - Improved `Topic.get_data` and `Topic.get_data_as_df` performance for Parquet-backed data.
  - `Topic.create_from_df()` and `File.add_topic()` now support DataFrames containing nested column types (structs, lists, list<struct>). Previously, only top-level primitive columns were fully supported.
  - `AddMessagePathRequest` now accepts a `path_in_schema` field to explicitly specify the field's location in the source data schema as an ordered list of path components. Relatedly, `Topic.add_message_path()` and `Topic.update_message_path()` now accept an optional `path_in_schema` parameter.

## Bugs Fixed
  - Updated behavior to not retry requests when server response exceeds the maximum safe payload size.

