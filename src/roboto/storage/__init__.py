# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Remote file storage I/O.

Whole-file transfer (upload transactions, download sessions, credentials, and
the object-store abstraction) for moving files in and out of Roboto storage,
plus the range-reader, local cache, and sparse-buffer primitives for streaming
byte-range reads that the format decoders in ``roboto.formats`` build on.
"""

from .api_operations import (
    AbortTransactionsRequest,
    BeginSignedUrlUploadRequest,
    BeginSignedUrlUploadResponse,
    BeginUploadRequest,
    BeginUploadResponse,
    ReportUploadProgressRequest,
)
from .cache import CachePolicy
from .credentials import RobotoCredentials
from .download_session import DownloadableFile
from .file_service import FileService
from .http_range_reader import HttpRangeReader, as_io_bytes
from .sparse_buffer import SparseBuffer

__all__ = (
    "AbortTransactionsRequest",
    "BeginSignedUrlUploadRequest",
    "BeginSignedUrlUploadResponse",
    "BeginUploadRequest",
    "BeginUploadResponse",
    "CachePolicy",
    "DownloadableFile",
    "FileService",
    "HttpRangeReader",
    "ReportUploadProgressRequest",
    "RobotoCredentials",
    "SparseBuffer",
    "as_io_bytes",
)
