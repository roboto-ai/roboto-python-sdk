# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing
import urllib.parse

import pydantic

from ..auth import Permissions
from ..http import PaginatedList, RobotoClient
from ..time import utcnow
from .http_resources import (
    CreateImageRepositoryRequest,
    DeleteImageRepositoryRequest,
    DeleteImageRequest,
)
from .record import (
    ContainerImageRecord,
    ContainerImageRepositoryRecord,
)


class ContainerCredentials(pydantic.BaseModel):
    """Temporary ``docker login`` credentials for one repository in Roboto's private image registry.

    ``ImageRegistry.get_temporary_credentials`` returns them. They reach only the repository they were requested for,
    and stop working at ``expiration``.
    """

    username: str
    """Username to pass to ``docker login``."""

    password: str
    """Password to pass to ``docker login``."""

    registry_url: str
    """URL of the registry to log in to, the server argument of ``docker login``."""

    expiration: datetime.datetime
    """Time the credentials expire."""

    def is_expired(self) -> bool:
        """Return whether the credentials have expired, as of now."""
        return utcnow() >= self.expiration

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the credentials as a JSON-compatible dictionary, with ``expiration`` as an ISO 8601 string."""
        return self.model_dump(mode="json")


class RepositoryPurpose(enum.Enum):
    """Purpose of a repository in Roboto's private image registry, which Roboto records when it creates the repository.

    Roboto sets and reads this value itself; no SDK method takes or returns it.
    """

    Executor = "executor"
    """Holds images that actions run in."""


class RepositoryTag(enum.Enum):
    """Key of a label Roboto sets on a repository in its private image registry when it creates the repository.

    These labels are not the image tags that name a repository's images. Roboto sets and reads them itself; no SDK
    method takes or returns them.
    """

    CreatedBy = "created_by"
    """Key of the label holding the ID of the user who created the repository."""

    OrgId = "org_id"
    """Key of the label holding the ID of the organization that owns the repository.

    Roboto checks it before the credentials from ``ImageRegistry.get_temporary_credentials`` can reach the repository.
    """

    Purpose = "purpose"
    """Key of the label holding the repository's ``RepositoryPurpose`` value."""


class ImageRepository(typing.TypedDict):
    """Name and URI of a repository in Roboto's private image registry.

    ``ImageRegistry.create_repository`` returns it.
    """

    repository_name: str
    """Name of the repository, as ``<org_id>/<name>`` in lowercase."""

    repository_uri: str
    """URI to push images to and pull them from, without a tag."""


class ImageRegistry:
    """Client for Roboto's private image registry, which holds the container images an organization's actions run in.

    An organization keeps its images in repositories, one image per tag. The ``roboto images`` CLI commands use this
    class to push, pull, list and delete images.

    Args:
        roboto_client: Client to make requests to Roboto with.
    """

    __roboto_client: RobotoClient

    def __init__(self, roboto_client: RobotoClient) -> None:
        self.__roboto_client = roboto_client

    def create_repository(
        self,
        repository_name: str,
        immutable_image_tags: bool = False,
        org_id: typing.Optional[str] = None,
    ) -> ImageRepository:
        """Create a repository in Roboto's private image registry, or return the one that already has this name.

        Push images to the returned ``repository_uri`` with credentials from ``get_temporary_credentials``.

        Args:
            repository_name: Name of the repository, without the organization's prefix. Roboto names the repository
                ``<org_id>/<repository_name>`` in lowercase.
            immutable_image_tags: Whether the repository refuses a push that would point an existing tag at a
                different image. A repository that already exists keeps its own setting.
            org_id: Organization to create the repository in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.

        Returns:
            Name and URI of the repository.
        """
        request_body = CreateImageRepositoryRequest(
            repository_name=repository_name,
            immutable_image_tags=immutable_image_tags,
        )
        response = self.__roboto_client.put(
            "v1/images/repository",
            data=request_body,
            caller_org_id=org_id,
        )
        return response.to_dict(json_path=["data"])

    def delete_image(self, image_uri: str, org_id: typing.Optional[str] = None) -> None:
        """Delete a container image from Roboto's private image registry.

        Deleting by tag removes that tag, and the image with it when that was its last tag. Deleting by digest removes
        the image and every tag on it. Deleting an image that no longer exists, or one outside the organization's
        repositories, succeeds and changes nothing.

        Args:
            image_uri: URI of the image, as ``<repository_uri>:<image_tag>`` or ``<repository_uri>@<digest>``. A URI
                with neither names the ``latest`` tag.
            org_id: Organization that owns the image's repository. Defaults to the organization the caller acts in.
        """
        self.__roboto_client.delete(
            "v1/images/image",
            data=DeleteImageRequest(
                image_uri=image_uri,
            ),
            owner_org_id=org_id,
        )

    def delete_repository(
        self,
        repository_name: str,
        org_id: typing.Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Delete a repository from Roboto's private image registry.

        Deleting a repository that no longer exists, or one outside the organization, succeeds and changes nothing.

        Args:
            repository_name: Name of the repository, as ``<org_id>/<name>``. A name without the organization's prefix
                deletes nothing.
            org_id: Organization that owns the repository. Defaults to the organization the caller acts in.
            force: Whether to delete the repository's images along with it. ``False`` refuses to delete a repository
                that holds any image, tagged or untagged.

        Raises:
            RobotoConflictException: The repository holds images and ``force`` is ``False``.
        """
        self.__roboto_client.delete(
            "v1/images/repository",
            data=DeleteImageRepositoryRequest(
                repository_name=repository_name,
                force=force,
            ),
            owner_org_id=org_id,
        )

    def get_container_image_record(self, org_id: str, image_uri: str) -> ContainerImageRecord:
        """Fetch the record of a tagged image in Roboto's private image registry.

        Args:
            org_id: ID of the organization that owns the image's repository.
            image_uri: URI of the image, as ``<repository_uri>:<image_tag>``. A URI with no tag names the ``latest``
                tag.

        Raises:
            RobotoNotFoundException: The URI is outside Roboto's private image registry, names the image by digest,
                or names a tag that none of the organization's repositories holds.
        """
        url_safe_image_uri = urllib.parse.quote_plus(image_uri)
        response = self.__roboto_client.get(
            f"v1/images/image/record/{org_id}/{url_safe_image_uri}",
            owner_org_id=org_id,
        )
        return response.to_record(ContainerImageRecord)

    def get_temporary_credentials(
        self,
        repository_uri: str,
        permissions: Permissions = Permissions.ReadOnly,
        org_id: typing.Optional[str] = None,
    ) -> ContainerCredentials:
        """Fetch temporary ``docker login`` credentials for one repository in Roboto's private image registry.

        The credentials reach only the repository ``repository_uri`` names.

        Args:
            repository_uri: URI of the repository. A tag or digest on the URI is ignored.
            permissions: What the credentials allow. :py:attr:`~roboto.auth.Permissions.ReadOnly` pulls images;
                :py:attr:`~roboto.auth.Permissions.ReadWrite` also pushes them.
            org_id: Organization to act in. Required when the caller belongs to more than one organization; otherwise
                the caller's only organization.

        Raises:
            RobotoInvalidRequestException: The URI is outside Roboto's private image registry, or no repository has
                it.
            RobotoUnauthorizedException: The repository belongs to another organization, or ``permissions`` is
                ``ReadWrite`` and the caller may not change the organization's actions.
        """
        response = self.__roboto_client.get(
            "v1/images/credentials",
            caller_org_id=org_id,
            query={
                "repository_uri": repository_uri,
                "permissions": permissions.value,
            },
        )

        return ContainerCredentials.model_validate(response.to_dict(json_path=["data"]))

    def list_images(
        self,
        repository_name: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        org_id: typing.Optional[str] = None,
    ) -> PaginatedList[ContainerImageRecord]:
        """List one page of the organization's tagged images in Roboto's private image registry.

        Each tag has its own record, so an image with two tags appears twice; untagged images are left out. Pass the
        page's ``next_token`` as ``page_token`` to fetch the next page; it is ``None`` on the last page.

        Args:
            repository_name: Name of the repository to list images from, as ``<org_id>/<name>``. ``None`` lists
                images from every repository the organization owns. A name that matches none of them returns an
                empty page.
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at
                the first page.
            org_id: Organization to act in. Required when the caller belongs to more than one organization; otherwise
                the caller's only organization.
        """
        qs_params = dict()
        if repository_name:
            qs_params["repository_name"] = repository_name

        if page_token:
            qs_params["page_token"] = page_token

        response = self.__roboto_client.get(
            "v1/images/image/record/list",
            caller_org_id=org_id,
            query=qs_params,
        )
        return response.to_paginated_list(ContainerImageRecord)

    def list_repositories(
        self,
        page_token: typing.Optional[str] = None,
        org_id: typing.Optional[str] = None,
    ) -> PaginatedList[ContainerImageRepositoryRecord]:
        """List one page of the organization's repositories in Roboto's private image registry, ordered by name.

        Pass the page's ``next_token`` as ``page_token`` to fetch the next page; it is ``None`` on the last page.

        Args:
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at
                the first page.
            org_id: Organization whose repositories to list. Defaults to the organization the caller acts in.
        """
        response = self.__roboto_client.get(
            "v1/images/repository/record/list",
            owner_org_id=org_id,
            query={"page_token": page_token} if page_token else None,
        )
        return response.to_paginated_list(ContainerImageRepositoryRecord)

    def repository_contains_image(
        self,
        repository_name: str,
        image_tag: str,
        org_id: typing.Optional[str] = None,
    ) -> bool:
        """Fetch whether a repository in Roboto's private image registry holds an image with this tag.

        The answer is ``True`` as soon as a push completes. A repository that does not exist, or that belongs to
        another organization, returns ``False``.

        Args:
            repository_name: Name of the repository, as ``<org_id>/<name>``.
            image_tag: Tag of the image.
            org_id: Organization to act in. Required when the caller belongs to more than one organization; otherwise
                the caller's only organization.
        """
        urlsafe_repository_name = urllib.parse.quote_plus(repository_name)
        urlsafe_image_tag = urllib.parse.quote_plus(image_tag)

        response = self.__roboto_client.get(
            f"v1/images/repository/{urlsafe_repository_name}/contains/{urlsafe_image_tag}",
            caller_org_id=org_id,
        )
        contains_image = response.to_dict(json_path=["data", "contains_image"])
        return contains_image
