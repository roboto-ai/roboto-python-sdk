# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class ContainerUploadCredentials(pydantic.BaseModel):
    """Credentials to push one container image to Roboto's private image registry.

    No SDK method or Roboto route uses this model.
    :py:meth:`~roboto.image_registry.ImageRegistry.get_temporary_credentials` returns
    :py:class:`~roboto.image_registry.ContainerCredentials` instead.
    """

    username: str
    """User name to sign in to the registry with."""

    password: str
    """Password to sign in to the registry with."""

    registry_url: str
    """URL of the registry to sign in to."""

    image_uri: str
    """URI of the image to push."""


class CreateImageRepositoryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.image_registry.ImageRegistry.create_repository`."""

    repository_name: str
    """Name of the repository to create, without the organization prefix.

    Roboto names the repository ``<org_id>/<repository_name>`` in lowercase. When that repository already exists,
    Roboto returns it unchanged.
    """

    immutable_image_tags: bool
    """Whether the repository refuses a push that would move an existing tag to another image.

    Ignored when the repository already exists.
    """


class CreateImageRepositoryResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.image_registry.ImageRegistry.create_repository`."""

    repository_name: str
    """Name of the repository, as ``<org_id>/<name>`` in lowercase."""

    repository_uri: str
    """URI to push images to and pull them from, without a tag."""


class DeleteImageRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.image_registry.ImageRegistry.delete_image`."""

    image_uri: str
    """URI of the image to delete, as ``<repository_uri>:<image_tag>`` or ``<repository_uri>@<digest>``.

    A URI with neither a tag nor a digest names the ``latest`` tag. Deleting by digest removes the image and every tag
    on it.
    """


class DeleteImageRepositoryRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.image_registry.ImageRegistry.delete_repository`."""

    repository_name: str
    """Name of the repository to delete, as ``<org_id>/<name>``.

    A name that does not begin with the caller's organization ID deletes nothing.
    """

    force: bool = False
    """Whether to delete the images in the repository along with it.

    Without it, deleting a repository that holds any image, tagged or not, raises ``RobotoConflictException``.
    """


class RepositoryContainsImageResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.image_registry.ImageRegistry.repository_contains_image`."""

    contains_image: bool
    """Whether the repository holds an image with the requested tag.

    ``False`` when the repository belongs to another organization.
    """


class SetImageRepositoryImmutableTagsRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/images/repository/image-tag-mutability``."""

    repository_name: str
    """Name of the repository to update, as ``<org_id>/<name>``.

    A name that does not begin with the caller's organization ID raises ``RobotoNotFoundException``.
    """

    immutable_image_tags: bool
    """Whether the repository refuses a push that would move an existing tag to another image."""
