# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

import pydantic

from ..domain.datasets import CreateDatasetRequest


class UploadConfigFileDatasetSection(CreateDatasetRequest):
    org_id: typing.Optional[str] = None


class UploadConfigFileUploadSection(pydantic.BaseModel):
    delete_uploaded_files: typing.Optional[bool] = None
    exclude_patterns: typing.Optional[typing.List[str]] = None


class UploadConfigFile(pydantic.BaseModel):
    version: typing.Literal["v1"] = "v1"

    dataset: UploadConfigFileDatasetSection = pydantic.Field(
        default_factory=UploadConfigFileDatasetSection
    )
    upload: UploadConfigFileUploadSection = pydantic.Field(
        default_factory=UploadConfigFileUploadSection
    )


class UploadAgentConfig(pydantic.BaseModel):
    version: typing.Literal["v1"] = "v1"

    delete_uploaded_files: bool = pydantic.Field(default=False)
    search_paths: list[pathlib.Path]
    upload_config_filename: str = ".roboto_upload.json"
