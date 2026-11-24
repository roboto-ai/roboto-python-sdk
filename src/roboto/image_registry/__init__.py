# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Roboto's private image registry: repositories of the container images an organization pushes for its actions to run.

Use :py:class:`~roboto.image_registry.ImageRegistry` to create repositories, fetch temporary credentials to push and
pull images, list images, and delete images and repositories.
"""

from .http_resources import (
    ContainerUploadCredentials,
    CreateImageRepositoryRequest,
    CreateImageRepositoryResponse,
    DeleteImageRepositoryRequest,
    DeleteImageRequest,
    RepositoryContainsImageResponse,
    SetImageRepositoryImmutableTagsRequest,
)
from .image_registry import (
    ContainerCredentials,
    ImageRegistry,
    ImageRepository,
    RepositoryPurpose,
    RepositoryTag,
)
from .record import (
    ContainerImageRecord,
    ContainerImageRepositoryRecord,
)

__all__ = (
    "ContainerCredentials",
    "ContainerImageRecord",
    "ContainerImageRepositoryRecord",
    "ContainerUploadCredentials",
    "CreateImageRepositoryRequest",
    "CreateImageRepositoryResponse",
    "DeleteImageRequest",
    "DeleteImageRepositoryRequest",
    "ImageRegistry",
    "ImageRepository",
    "RepositoryContainsImageResponse",
    "RepositoryPurpose",
    "RepositoryTag",
    "SetImageRepositoryImmutableTagsRequest",
)
