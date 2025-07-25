# 0.24.1
## No Breaking Changes

## Features Added
  - Allow `device_id` to be specified explicitly when creating or updating datasets.
  - Extended first-class support for Parquet-based recording data: `Topic::get_data`, `MessagePath::get_data`, `Event::get_data`, and their `::get_data_as_df` variants now work with data ingested from Parquet files (previously raised `NotImplementedError`).
  - Addition of `MessagePathRecord::path_in_schema`, `MessagePathRecord::source_path`, and `MessagePathRecord::parents`
  for use accessing fields on topic data without heuristically assuming all message paths are or can be dot separated.

## Bugs Fixed
  - 

