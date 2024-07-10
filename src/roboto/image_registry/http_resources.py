# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class ContainerUploadCredentials(pydantic.BaseModel):
    username: str
    password: str
    registry_url: str
    image_uri: str


class CreateImageRepositoryRequest(pydantic.BaseModel):
    repository_name: str
    immutable_image_tags: bool


class CreateImageRepositoryResponse(pydantic.BaseModel):
    repository_name: str
    repository_uri: str


class DeleteImageRequest(pydantic.BaseModel):
    image_uri: str


class DeleteImageRepositoryRequest(pydantic.BaseModel):
    repository_name: str
    """The name of the repository to delete."""

    force: bool = False
    """Delete all images in the repository before deleting the repository if the repository is not empty."""


class RepositoryContainsImageResponse(pydantic.BaseModel):
    contains_image: bool


class SetImageRepositoryImmutableTagsRequest(pydantic.BaseModel):
    repository_name: str
    immutable_image_tags: bool
