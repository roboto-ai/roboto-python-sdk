# 0.35.0
## Breaking Changes
  - `get_data()` now yields `tuple[int | float, dict]` instead of `dict`. The first element of the tuple is the record's timestamp in nanoseconds since Unix epoch, and the record is no longer enriched with a `log_time` field.
  - `get_data_as_df()` now returns a DataFrame with a timezone-aware UTC `DatetimeIndex`. A `log_time` column is no longer added to the DataFrame.

## Features Added
  - Added `--device-id` argument to `roboto datasets create` and `roboto datasets update` CLI commands.
  - DataFrames returned by `get_data_as_df()` can now be passed directly to `File.add_topic()` without specifying `timestamp_column` or `timestamp_unit`.

## Bugs Fixed
  - `Dataset.update()` now supports explicitly clearing `description` and `name` fields by passing `None`. Previously, passing `None` was indistinguishable from omitting the parameter.
  - Removed unused `conditions` parameter from `Dataset.update()` and `UpdateDatasetRequest`.

