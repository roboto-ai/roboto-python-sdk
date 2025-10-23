# 0.30.0rc1
## Features Added
  - Added an optional `total_count` field to `PaginatedList`

## Bugs Fixed
  - Action parameters passed via `roboto actions invoke --parameter` are now correctly treated as strings, matching the documented behavior.
  - The global `roboto` CLI option `--profile` is now respected when using `roboto actions invoke-local`, enabling switching between Roboto orgs or API keys.

