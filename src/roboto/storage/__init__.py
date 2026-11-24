# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Transfer of file contents between local disk and Roboto, and reads of byte ranges from a file Roboto stores.

To move whole files between local disk and Roboto, use :py:class:`~roboto.storage.FileService`; to read a file at a
URL, such as a signed download URL, fetching only the bytes read and writing nothing to disk, use
:py:class:`~roboto.storage.HttpRangeReader`. Methods such as :py:meth:`~roboto.domain.datasets.Dataset.upload_files`,
:py:meth:`~roboto.domain.files.File.download` and :py:meth:`~roboto.domain.topics.Topic.get_data` move data through
this package, so most code never calls it.
"""

from .api_operations import (
    AbortTransactionsRequest,
    BeginSignedUrlUploadRequest,
    BeginSignedUrlUploadResponse,
    BeginUploadRequest,
    BeginUploadResponse,
    ReportUploadProgressRequest,
    ReportUploadProgressResponseItem,
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
    "ReportUploadProgressResponseItem",
    "RobotoCredentials",
    "SparseBuffer",
    "as_io_bytes",
)
