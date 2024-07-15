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
    username: str
    password: str
    registry_url: str
    expiration: datetime.datetime

    def is_expired(self) -> bool:
        return utcnow() >= self.expiration

    def to_dict(self) -> dict[str, typing.Any]:
        return self.model_dump(mode="json")


class RepositoryPurpose(enum.Enum):
    Executor = "executor"


class RepositoryTag(enum.Enum):
    CreatedBy = "created_by"
    OrgId = "org_id"
    Purpose = "purpose"  # RepositoryPurpose


class ImageRepository(typing.TypedDict):
    repository_name: str
    repository_uri: str


class ImageRegistry:
    __roboto_client: RobotoClient

    def __init__(self, roboto_client: RobotoClient) -> None:
        self.__roboto_client = roboto_client

    def create_repository(
        self,
        repository_name: str,
        immutable_image_tags: bool = False,
        org_id: typing.Optional[str] = None,
    ) -> ImageRepository:
        """
        Create a repository for a container image in Roboto's private image registry.
        Images with different tags can be pushed to the same repository.

        Args:
            repository_name: The name of the repository to create.
            immutable_image_tags: Whether to allow image tags to be overwritten. If set to True,
                then any attempt to overwrite an existing image tag will error.

        Returns:
            A dictionary contains the `repository_name` and `repository_uri` of the created repository.
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
        """
        Delete a container image from Roboto's private registry.

        Args:
            image_uri: The full URI of the image to delete.
            org_id: ID of organization owning the provided image.
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
        """
        Delete a container image from Roboto's private registry.

        Args:
            repository_name: The name of the repository to delete.
            org_id: ID of organization owning the provided image.
            force: Delete all images in the repository before deleting the repository if the repository is not empty.
        """
        self.__roboto_client.delete(
            "v1/images/repository",
            data=DeleteImageRepositoryRequest(
                repository_name=repository_name,
                force=force,
            ),
            owner_org_id=org_id,
        )

    def get_container_image_record(
        self, org_id: str, image_uri: str
    ) -> ContainerImageRecord:
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
        urlsafe_repository_name = urllib.parse.quote_plus(repository_name)
        urlsafe_image_tag = urllib.parse.quote_plus(image_tag)

        response = self.__roboto_client.get(
            f"v1/images/repository/{urlsafe_repository_name}/contains/{urlsafe_image_tag}",
            caller_org_id=org_id,
        )
        contains_image = response.to_dict(json_path=["data", "contains_image"])
        return contains_image
