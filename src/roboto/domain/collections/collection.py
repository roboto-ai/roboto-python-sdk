# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
from typing import Optional, Union

from ...auth import (
    EditAccessRequest,
    GetAccessResponse,
)
from ...http import RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from .operations import (
    CreateCollectionRequest,
    UpdateCollectionRequest,
)
from .record import (
    CollectionChangeRecord,
    CollectionContentMode,
    CollectionRecord,
    CollectionResourceRef,
    CollectionResourceType,
)


class Collection:
    """
    A higher-level container for grouping datasets together. Collections can also be used
    to group files from several distinct datasets together.
    """

    __record: CollectionRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        collection_id: str,
        version: Optional[int] = None,
        content_mode: CollectionContentMode = CollectionContentMode.Full,
        roboto_client: typing.Optional["RobotoClient"] = None,
    ) -> "Collection":
        roboto_client = RobotoClient.defaulted(roboto_client)

        query: dict[str, typing.Any] = {"content_mode": content_mode.value}

        if version is not None:
            query["version"] = version

        record = roboto_client.get(
            f"v1/collections/id/{collection_id}", query=query
        ).to_record(CollectionRecord)

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def create(
        cls,
        description: Optional[str] = None,
        name: Optional[str] = None,
        resources: Optional[list[CollectionResourceRef]] = None,
        dataset_ids: typing.Optional[collections.abc.Collection[str]] = None,
        file_ids: typing.Optional[collections.abc.Collection[str]] = None,
        tags: Optional[list[str]] = None,
        roboto_client: typing.Optional["RobotoClient"] = None,
        caller_org_id: Optional[str] = None,
    ) -> "Collection":
        roboto_client = RobotoClient.defaulted(roboto_client)

        normalized_resources = resources or []
        if dataset_ids:
            normalized_resources.extend(
                [
                    CollectionResourceRef(
                        resource_type=CollectionResourceType.Dataset,
                        resource_id=dataset_id,
                    )
                    for dataset_id in dataset_ids
                ]
            )

        if file_ids:
            normalized_resources.extend(
                [
                    CollectionResourceRef(
                        resource_type=CollectionResourceType.File, resource_id=file_id
                    )
                    for file_id in file_ids
                ]
            )

        request = CreateCollectionRequest(
            name=name,
            description=description,
            resources=normalized_resources,
            tags=tags,
        )

        record = roboto_client.post(
            "v1/collections/create", data=request, caller_org_id=caller_org_id
        ).to_record(CollectionRecord)

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def list_all(
        cls,
        roboto_client: typing.Optional["RobotoClient"] = None,
        owner_org_id: Optional[str] = None,
        content_mode: CollectionContentMode = CollectionContentMode.SummaryOnly,
    ) -> collections.abc.Generator["Collection", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        spec = QuerySpecification()
        query_params = {"content_mode": content_mode.value}

        while True:
            paginated_result = roboto_client.post(
                "v1/collections/search",
                query=query_params,
                data=spec.model_dump(mode="json"),
                owner_org_id=owner_org_id,
                idempotent=True,
            ).to_paginated_list(CollectionRecord)

            for record in paginated_result.items:
                yield cls(record=record, roboto_client=roboto_client)
            if paginated_result.next_token:
                spec.after = paginated_result.next_token
            else:
                break

    def __init__(
        self,
        record: CollectionRecord,
        roboto_client: typing.Optional["RobotoClient"] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def created(self) -> datetime.datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def collection_id(self) -> str:
        return self.__record.collection_id

    @property
    def datasets(self) -> list[str]:
        return [
            resource.get("resource_id", resource.get("dataset_id"))
            for resource in self.__record.resources.get(
                CollectionResourceType.Dataset, []
            )
        ]

    @property
    def files(self) -> list[str]:
        return [
            resource.get("resource_id", resource.get("file_id"))
            for resource in self.__record.resources.get(CollectionResourceType.File, [])
        ]

    @property
    def record(self) -> CollectionRecord:
        return self.__record

    @property
    def updated(self) -> datetime.datetime:
        return self.__record.updated

    @property
    def updated_by(self) -> str:
        return self.__record.updated_by

    def add_dataset(self, dataset_id: str) -> "Collection":
        return self.update(
            add_resources=[
                CollectionResourceRef(
                    resource_id=dataset_id, resource_type=CollectionResourceType.Dataset
                )
            ]
        )

    def add_file(self, file_id: str) -> "Collection":
        return self.update(
            add_resources=[
                CollectionResourceRef(
                    resource_id=file_id, resource_type=CollectionResourceType.File
                )
            ]
        )

    def changes(
        self, from_version: Optional[int] = None, to_version: Optional[int] = None
    ) -> collections.abc.Generator["CollectionChangeRecord", None, None]:
        query: dict[str, typing.Any] = {}

        if from_version:
            query["from_version"] = from_version

        if to_version:
            query["to_version"] = to_version

        # Currently this only returns a single page
        paginated_results = self.__roboto_client.get(
            f"v1/collections/id/{self.collection_id}/changes", query=query
        ).to_paginated_list(CollectionChangeRecord)

        for record in paginated_results.items:
            yield record

    def delete(self):
        self.__roboto_client.delete(f"v1/collections/id/{self.collection_id}")

    def get_access(self) -> GetAccessResponse:
        return self.__roboto_client.get(
            f"v1/collections/{self.collection_id}/access"
        ).to_record(GetAccessResponse)

    def edit_access(self, edit: EditAccessRequest) -> GetAccessResponse:
        return self.__roboto_client.put(
            f"v1/collections/{self.collection_id}/access", data=edit
        ).to_record(GetAccessResponse)

    def remove_dataset(self, dataset_id: str) -> "Collection":
        return self.update(
            remove_resources=[
                CollectionResourceRef(
                    resource_id=dataset_id, resource_type=CollectionResourceType.Dataset
                )
            ]
        )

    def remove_file(self, file_id: str) -> "Collection":
        return self.update(
            remove_resources=[
                CollectionResourceRef(
                    resource_id=file_id, resource_type=CollectionResourceType.File
                )
            ]
        )

    def update(
        self,
        add_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet,
        add_tags: Union[list[str], NotSetType] = NotSet,
        description: Optional[Union[NotSetType, str]] = NotSet,
        name: Optional[Union[NotSetType, str]] = NotSet,
        remove_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet,
        remove_tags: Union[list[str], NotSetType] = NotSet,
    ) -> "Collection":
        request = remove_not_set(
            UpdateCollectionRequest(
                name=name,
                description=description,
                add_tags=add_tags,
                remove_tags=remove_tags,
                add_resources=add_resources,
                remove_resources=remove_resources,
            )
        )

        self.__record = self.__roboto_client.put(
            f"v1/collections/id/{self.collection_id}", data=request
        ).to_record(CollectionRecord)

        return self
