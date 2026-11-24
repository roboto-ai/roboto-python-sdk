# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Files: data items uploaded or imported to a dataset, or added to a device, device type, or organization.

To find and download a file, use :py:class:`~roboto.domain.files.File`; to upload and list the files of a dataset,
device, device type, or organization, use :py:class:`~roboto.domain.files.FileSystem`.
"""

from .file import File
from .file_system import FileSystem
from .lazy_lookup_file import LazyLookupFile
from .operations import (
    CreateDirectoryRequest,
    CreateLinkRequest,
    DeleteDirectoriesRequest,
    DeleteFileRequest,
    DirectoryContentsPage,
    FileRecordRequest,
    ImportFileRequest,
    QueryDatasetFilesRequest,
    QueryFilesRequest,
    RenameDirectoryRequest,
    RenameFileRequest,
    SignedUrlResponse,
    UpdateFileRecordRequest,
)
from .record import (
    DirectoryRecord,
    FileRecord,
    FileStatus,
    FileStorageType,
    FileTag,
    FSType,
    IngestionStatus,
    is_directory,
    is_file,
)

__all__ = (
    "CreateDirectoryRequest",
    "CreateLinkRequest",
    "DeleteDirectoriesRequest",
    "DeleteFileRequest",
    "DirectoryContentsPage",
    "DirectoryRecord",
    "FSType",
    "File",
    "FileRecord",
    "FileRecordRequest",
    "FileStatus",
    "FileStorageType",
    "FileSystem",
    "FileTag",
    "ImportFileRequest",
    "IngestionStatus",
    "LazyLookupFile",
    "QueryDatasetFilesRequest",
    "QueryFilesRequest",
    "RenameDirectoryRequest",
    "RenameFileRequest",
    "SignedUrlResponse",
    "UpdateFileRecordRequest",
    "is_directory",
    "is_file",
)
