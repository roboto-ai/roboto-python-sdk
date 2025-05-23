# 0.20.1
## No Breaking Changes

## Features Added
  - [CLI] Actions that don't take inputs can now be invoked from the command-line by leaving out the arguments `--dataset-id` and `--input-data`. For actions that take inputs, both arguments must be provided as before.
  - Add subset of audit fields to `RepresentationRecord` to enable determination of "latest" representation of topic data.
  - Add ability to pass `caller_org_id` to `File::import_batch`, which is necessary to exercise bring-your-own-bucket file imports for users belonging to multiple orgs.

## Bugs Fixed

