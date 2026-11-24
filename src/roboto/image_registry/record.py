# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class ContainerImageRepositoryRecord(pydantic.BaseModel):
    """Data record of a container image repository, as the Roboto API returns it.

    A container image repository holds the images an organization pushes to Roboto's private image registry, one image
    per tag. :py:meth:`~roboto.image_registry.ImageRegistry.list_repositories` returns these records.
    """

    org_id: str
    """ID of the organization that owns the repository."""

    repository_name: str
    """Name of the repository, as ``<org_id>/<name>`` in lowercase."""

    repository_uri: str
    """URI to push images to and pull them from, without a tag."""

    arn: str
    """Amazon Resource Name (ARN) of the repository."""


class ContainerImageRecord(pydantic.BaseModel):
    """Data record of a container image, as :py:meth:`~roboto.image_registry.ImageRegistry.list_images` returns it.

    :py:meth:`~roboto.image_registry.ImageRegistry.get_container_image_record` also returns it. Each record names a
    tagged image in Roboto's private image registry, so an image with several tags has one record per tag.
    """

    org_id: str
    """ID of the organization that owns the image's repository."""

    repository_name: str
    """Name of the repository that holds the image, as ``<org_id>/<name>`` in lowercase."""

    image_tag: str
    """Tag this record names the image by."""

    image_uri: str
    """URI of the image, as ``<repository_uri>:<image_tag>``, which an action can name as its container image.

    :py:meth:`~roboto.image_registry.ImageRegistry.get_container_image_record` returns the URI it was given.
    """
