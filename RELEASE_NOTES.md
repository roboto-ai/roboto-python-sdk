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
  - Added placeholder implementation for working with topic data ingested as Parquet in the SDK. Attempting to fetch Parquet-ingested data currently raises a `NotImplementedError`.
  - Added `roboto datasets import-external-file` CLI command for importing files from customer S3 buckets into Roboto datasets.

## Bugs Fixed

