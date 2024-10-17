# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class ContainerUploadCredentials(pydantic.BaseModel):
    """Container upload credentials"""

    username: str
    password: str
    registry_url: str
    image_uri: str


class CreateImageRepositoryRequest(pydantic.BaseModel):
    """Request payload to create an image repository"""

    repository_name: str
    immutable_image_tags: bool


class CreateImageRepositoryResponse(pydantic.BaseModel):
    """Response payload to create an image repository"""

    repository_name: str
    repository_uri: str


class DeleteImageRequest(pydantic.BaseModel):
    """Request payload to delete an image"""

    image_uri: str


class DeleteImageRepositoryRequest(pydantic.BaseModel):
    """Request payload to delete an image repository"""

    repository_name: str
    """The name of the repository to delete."""

    force: bool = False
    """Delete all images in the repository before deleting the repository if the repository is not empty."""


class RepositoryContainsImageResponse(pydantic.BaseModel):
    """Response payload to repository contains image"""

    contains_image: bool


class SetImageRepositoryImmutableTagsRequest(pydantic.BaseModel):
    """Request payload to set image repository tags"""

    repository_name: str
    immutable_image_tags: bool
