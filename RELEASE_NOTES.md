# 0.35.1
### Simplified File Transfer API

File upload and download operations have been simplified. The high-level methods `Dataset.download_files()`, `Dataset.upload_files()`, and `File.download()` remain the recommended interfaces for file transfers. Implementation details that were previously exposed—such as credential management, progress monitoring factories, and upload transaction orchestration—have been moved into internal infrastructure and are no longer part of the public API.

**If you were using the high-level methods**, no changes are required beyond noting that `File.download()` now accepts a simpler `print_progress: bool` parameter instead of `credential_provider` and `progress_monitor_factory`.

**If you were using lower-level utilities directly**, migrate to the high-level methods above, or use `FileService` from `roboto.fs` if you need more control.

**Removed from public API:**

  - `FileDownloader` class: use `Dataset.download_files()`, `File.download()`, or `FileService` directly instead
  - Credential types (`CredentialProvider`, `DatasetCredentials`, `S3Credentials`, `UploadCredentials`)
  - Upload transaction types (`BeginManifestTransactionRequest`, `BeginManifestTransactionResponse`, `ReportTransactionProgressRequest`)
  - `File` static methods (`construct_s3_obj_arn()`, `construct_s3_obj_uri()`, `generate_s3_client()`): internal utilities no longer needed
  - `Dataset` internals (`_complete_manifest_transaction()`, `_create_manifest_transaction()`, `_flush_manifest_item_completions()`, `UPLOAD_REPORTING_BATCH_COUNT`, `UPLOAD_REPORTING_MIN_BATCH_SIZE`)
  - Modules: `roboto.domain.files.file_creds`, `roboto.domain.files.file_downloader`, `roboto.domain.files.file_service`, `roboto.domain.files.progress`

## Features Added
  - Added generic file upload API endpoints (`/v1/files/upload/*`) that support uploading files to any association type (datasets, topics, etc.), replacing the dataset-specific upload endpoints.

## Bugs Fixed
  - CLI version checker now queries GitHub Releases instead of PyPI, ensuring users are only prompted to upgrade to CLI versions that are actually published and available.

