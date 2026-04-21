# 0.40.0
## Breaking Changes
  - Collections no longer support mixed resource types. Adding a resource whose type doesn't match the collection's `resource_type` raises an error.

## Features Added
  - `Collection.create()` now accepts a `resource_type` parameter (`CollectionResourceType.File` or `CollectionResourceType.Dataset`, defaulting to `File`) to declare whether a collection holds files or datasets. Adding a resource whose type doesn't match raises an error. `CollectionRecord` now includes a `resource_type` field.
  - `roboto collections create` now accepts an optional `--resource-type` flag (`file` or `dataset`). The type is inferred from `--file-id` or `--dataset-id` when not provided. Passing both flags together is an error. Omitting both IDs and `--resource-type` defaults to `file` and emits a warning.

## Bugs Fixed
  - Downloading or uploading files whose S3 key contains a `#` character no longer fails with a 403 error. `urllib.parse.urlparse` treats `#` as a URL fragment delimiter and silently truncates the key, causing the request to target a nonexistent object. `FileRecord.key` and `FileRecord.bucket` are now derived correctly.

