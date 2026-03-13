# 0.37.0
## Breaking Changes
 - `File.get_summary()` and `File.generate_summary()` have been removed. `roboto.ai.Chat` should instead be used for the summarization of 1+ files. It offers a superset of the functionality of the old `File`-level summary API.

## Features Added
  - `roboto datasets upload-files` CLI command now accepts an optional `--device-id` flag to associate uploaded files with a specific device.
  - Improved MCAP topic data access performance for high-latency connections. Time-range queries now use HTTP Range requests to fetch only the required byte ranges instead of downloading entire files.

## Bugs Fixed
  - Removed `typing_extensions` dependency as Python 3.9 is EOL. (`typing` is part of the standard library for Python 3.10+.)
  - `UpdateUserRequest` now rejects empty strings for `name` and `picture_url` fields, returning a validation error instead of causing a server error.
  - `find_similar_signals` now accepts DataFrames with string-typed numeric columns (e.g. `"1.23"`) for both needle and haystack. Columns are coerced to `float64` before processing; a `ValueError` is raised if any value cannot be converted. DataFrames already containing numeric types are unaffected.
  - `find_similar_signals` now correctly handles DataFrames indexed by `pandas.Timestamp` values.

