# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import datetime
import pathlib
import typing

import pydantic

from ..domain.datasets import CreateDatasetRequest

UPLOAD_COMPLETE_FILENAME = ".roboto_upload_complete.json"
UPLOAD_IN_PROGRESS_FILENAME = ".roboto_upload_in_progress.json"


class UploadConfigFileDatasetSection(CreateDatasetRequest):
    """Upload agent config file dataset section"""

    org_id: typing.Optional[str] = None

    add_to_collections: typing.Optional[typing.List[str]] = None
    """An optional list of collection IDs to attempt to add this dataset to."""


class UploadConfigFileUploadSection(pydantic.BaseModel):
    """Upload agent config file upload section"""

    delete_uploaded_files: typing.Optional[bool] = None
    exclude_patterns: typing.Optional[typing.List[str]] = None
    include_patterns: typing.Optional[typing.List[str]] = None


class UploadConfigFile(pydantic.BaseModel):
    """Upload agent config file"""

    version: typing.Literal["v1"] = "v1"

    dataset: UploadConfigFileDatasetSection = pydantic.Field(
        default_factory=UploadConfigFileDatasetSection
    )
    upload: UploadConfigFileUploadSection = pydantic.Field(
        default_factory=UploadConfigFileUploadSection
    )


class UploadAgentConfig(pydantic.BaseModel):
    """Upload agent configuration"""

    version: typing.Literal["v1"] = "v1"

    default_org_id: typing.Optional[str] = None
    """
    The org ID to use when creating datasets via --merge-uploads, or other operations which may have an ambiguous org.
    """

    delete_empty_directories: bool = False
    """
    If set to true, directories which are empty (or only contain a .roboto_upload_complete.json) after being uploaded
    will be automatically deleted. This is most useful if combined with delete_upload_files=True
    """

    delete_uploaded_files: bool = False
    """
    If set to true, will delete files from disk after they've been successfully uploaded to Roboto.
    """

    search_paths: list[pathlib.Path]
    """
    Directories to recursively scan for files to upload.
    """

    upload_config_filename: str = ".roboto_upload.json"
    """
    The name of the upload marker file to look for.
    """


class UploadInProgressFile(pydantic.BaseModel):
    """Upload agent in progress file"""

    version: typing.Literal["v1"] = "v1"
    dataset_id: str
    started: datetime.datetime


class UploadCompleteFile(pydantic.BaseModel):
    """Upload agent complete file"""

    version: typing.Literal["v1"] = "v1"
    dataset_id: str
    completed: datetime.datetime
