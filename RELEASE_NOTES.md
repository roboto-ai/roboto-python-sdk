# 0.60.0
## Breaking Changes
  - The `session.created`, `session.updated`, and `session.file_added` platform events are removed, along with `OncePer.Session` and the dry-run `session_id` option. A trigger subscribed to one of them no longer parses.
  - Sessions (experimental): `SessionFile.range_min_timestamp_ns` and `range_max_timestamp_ns` are replaced by `min_file_timestamp_ns` and `max_file_timestamp_ns`, which are in the file's own timestamps, not Unix-epoch nanoseconds. Renaming the fields without converting the values declares the wrong window.
  - Sessions (experimental): `Session.add_file`, `add_files`, `remove_file`, and `remove_files` no longer return the `Session`. The plural forms return a `BatchResponse` and do not raise when the platform refuses an entry, so check its `failed` list.
  - `Device.create_session` (experimental) requires `name`, and a second call with the same name returns the existing session instead of creating another.
  - `File.set_timeline_offset` (experimental) takes `offset` in place of `unix_epoch_offset_ns`, and reads a `float`, `Decimal`, or numeric string as seconds, where it read nanoseconds.
  - `Metric.publish` and `Session.publish_metrics` (experimental): each item in the result's `failed` list is the exception the platform refused it with, replacing `PublishMetricsError`.
  - `Topic.from_id`, `Topic.from_record`, and the `Topic` constructor (experimental) take `context` in place of `session_context`. `Topic.context` and `Topic.set_context` are removed; build another `Topic` to read in a different context.
  - `Topic.get_data`, `get_data_as_df`, and `get_data_as_record_batches` (experimental) return only the fields that `fields_include` and `fields_exclude` select. The field a topic's timestamps come from is no longer added to a filtered read, and filters that select no field raise `RobotoInvalidRequestException`.

## Features Added
  - `Device.create_sessions` (experimental) creates up to 100 sessions in one call from files you have already uploaded, declaring each file's topics, schemas, and timeline sources. `File.declare_topics` declares one file's topics without a session, and `Session.add_files` accepts the same declarations.
  - A declared topic (experimental) can list `representations`, the MCAP or Parquet files a read opens, so data in a ROS bag, PX4 ULog, or CSV is read through files converted from it. `File.set_representations` replaces them later.
  - `Session.set_unix_offset` and `Topic.set_unix_offset` (experimental) anchor data recorded in relative time to wall-clock time; `anchor_ns` on a declaration does the same when the data is declared.
  - `Device.get_or_create` (experimental) registers a device, or returns the existing one when the ID is taken.
  - Every method taking a `roboto.time.Time` accepts a NumPy integer, so a timestamp from a pandas or NumPy column can be passed as is.
  - `FileContext`, `DatasetContext`, and `DeviceContext` (experimental) scope a `Topic`'s reads to its data in one file, a dataset's files, or a device's files, with no session needed. `start_time` and `end_time` may be omitted and default to the extent of that data.
  - `roboto.ai.mcp` gains `McpServerOrgCredentialRecord` and `SetMcpServerOrgCredentialRequest`, record types for an MCP server's org token: an org secret whose value the AI sends as a bearer token for service users, and for members who have not connected the server themselves or whose own connection fails. The record names the secret and never holds its value. These are request and response types only: no SDK method sends or returns them.

## Bugs Fixed
  - Experimental APIs no longer emit `ExperimentalWarning` when called, which could print on every call. Each one is still marked as experimental in its documentation, and `roboto.ExperimentalWarning` is still importable.
  - Experimental topic reads scoped to a session return only that session's data when the session holds part of a file, whether a time window or a `data_range` slice. Requires this SDK version.
  - Experimental topic reads no longer raise `TypeError` on Python 3.10 and 3.11 when timestamps come from a schema field that declares a time unit.

