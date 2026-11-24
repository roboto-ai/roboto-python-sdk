# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Datasets: containers of files in a directory structure, usually from one robot activity such as a flight.

Use :py:class:`~roboto.domain.datasets.Dataset` to create and find datasets, and to upload and download their files.
"""

from .dataset import Dataset
from .operations import (
    CreateDatasetIfNotExistsRequest,
    CreateDatasetRequest,
    CreateDirectoryRequest,
    DeleteDirectoriesRequest,
    QueryDatasetFilesRequest,
    QueryDatasetsRequest,
    RenameDirectoryRequest,
    UpdateDatasetRequest,
)
from .record import DatasetRecord

__all__ = (
    "CreateDatasetRequest",
    "CreateDatasetIfNotExistsRequest",
    "CreateDirectoryRequest",
    "Dataset",
    "DatasetRecord",
    "DeleteDirectoriesRequest",
    "QueryDatasetFilesRequest",
    "QueryDatasetsRequest",
    "RenameDirectoryRequest",
    "UpdateDatasetRequest",
)
