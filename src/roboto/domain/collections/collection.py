# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
from typing import Optional, Union
import warnings

from ...api_version import RobotoApiVersion
from ...auth import (
    AccessGrant,
    EditAccessRequest,
    EditRecordAccessRequest,
    GetAccessResponse,
    RecordAccessResponse,
)
from ...http import RobotoClient
from ...http.constants import API_VERSION_HEADER
from ...query import (
    QuerySpecification,
    SortDirection,
)
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...updates import CustomFieldChangeset
from ...warnings import experimental
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

_TUPLE_ACCESS_API_VERSION_HEADERS = {API_VERSION_HEADER: RobotoApiVersion.v2026_11_05.value}
"""Headers that pin a request to API version 2026-11-05.

That is the last version whose collection access route takes and returns tuples. ``Collection.get_access`` and
``Collection.edit_access`` send them.
"""


class Collection:
    """A collection: a versioned group of resources of one type, such as datasets or files from several datasets.

    A collection belongs to one organization and holds datasets, files, events, or sessions, whichever type it is
    created with. Each update to a collection creates a new version, and ``changes`` lists what each update changed.

    A collection shows each caller only the datasets and files they may read. Read with
    :py:attr:`~roboto.domain.collections.CollectionContentMode.Full`, a dataset or file the caller may not read is
    listed in the record's ``missing`` resources; read with
    :py:attr:`~roboto.domain.collections.CollectionContentMode.References`, and in ``changes``, it is left out.
    ``datasets`` and ``files`` hold only the members shown.

    Get a ``Collection`` from ``create``, ``from_id``, or ``list_all``. To wrap a
    :py:class:`~roboto.domain.collections.CollectionRecord` already fetched from Roboto, build a ``Collection`` from it
    directly. Each instance holds a copy of the collection's record: methods that change the collection update that
    copy from Roboto's response.

    Args:
        record: Record of the collection.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
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
        """Fetch a collection by its ID.

        Args:
            collection_id: ID of the collection, beginning with ``cl_``.
            version: Version of the collection to fetch: ``0`` is the collection as it was created, and each update
                adds one. ``None`` fetches the current version.
            content_mode: How much of each member to return. Defaults to each member's full record.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No collection has this ID.
            RobotoInvalidRequestException: ``content_mode`` is
                :py:attr:`~roboto.domain.collections.CollectionContentMode.Full` and the response would be too large.
                Fetch the collection with :py:attr:`~roboto.domain.collections.CollectionContentMode.References`
                instead.

        Examples:
            Fetch the current version of a collection:

            >>> collection = Collection.from_id("cl_12345")
            >>> print(collection.name, collection.resource_count)

            Fetch the collection as it was when it was created, with a reference to each member:

            >>> from roboto.domain.collections import CollectionContentMode
            >>> original = Collection.from_id("cl_12345", version=0, content_mode=CollectionContentMode.References)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        query: dict[str, typing.Any] = {"content_mode": content_mode.value}

        if version is not None:
            query["version"] = version

        record = roboto_client.get(f"v1/collections/id/{collection_id}", query=query).to_record(CollectionRecord)

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def create(
        cls,
        description: Optional[str] = None,
        name: Optional[str] = None,
        resource_type: CollectionResourceType = CollectionResourceType.File,
        resources: Optional[list[CollectionResourceRef]] = None,
        dataset_ids: typing.Optional[collections.abc.Collection[str]] = None,
        event_ids: typing.Optional[collections.abc.Collection[str]] = None,
        file_ids: typing.Optional[collections.abc.Collection[str]] = None,
        session_ids: typing.Optional[collections.abc.Collection[str]] = None,
        tags: Optional[list[str]] = None,
        custom_fields: Optional[dict[str, typing.Any]] = None,
        roboto_client: typing.Optional["RobotoClient"] = None,
        caller_org_id: Optional[str] = None,
    ) -> "Collection":
        """Create a collection.

        The collection starts with ``resources`` followed by the resources the ``*_ids`` arguments name. Every one of
        them must be of ``resource_type``, which defaults to files: to create a collection of datasets, pass
        ``resource_type=CollectionResourceType.Dataset`` along with ``dataset_ids``.

        Args:
            description: Human-readable description of the collection.
            name: Human-readable name of the collection. Roboto does not require names to be unique.
            resource_type: Type of resource the collection holds. It cannot change after the collection is created.
            resources: Resources the collection starts with. ``None`` adds none.
            dataset_ids: IDs of datasets the collection starts with.
            event_ids: IDs of events the collection starts with.
            file_ids: IDs of files the collection starts with.
            session_ids: IDs of sessions the collection starts with.
            tags: Tags to set on the collection.
            custom_fields: Initial values for the collection's custom fields, keyed by field name. Each name must be a
                custom field defined for collections in the organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type. ``None`` sets none.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            caller_org_id: Organization to create the collection in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.

        Returns:
            The new collection, with each member's full record.

        Raises:
            RobotoInvalidRequestException: A resource is not of ``resource_type``.
            RobotoNotFoundException: A resource does not exist, or is an event or session in another organization.
            RobotoIllegalArgumentException: A ``custom_fields`` name is not a ready custom field for collections, or
                its value does not match the field's type.

        Examples:
            Create a collection of two datasets:

            >>> from roboto.domain.collections import CollectionResourceType
            >>> collection = Collection.create(
            ...     name="Highway test drives",
            ...     resource_type=CollectionResourceType.Dataset,
            ...     dataset_ids=["ds_12345", "ds_67890"],
            ...     tags=["highway"],
            ... )

            Create a collection of files from different datasets:

            >>> collection = Collection.create(
            ...     name="Calibration logs",
            ...     file_ids=["fl_12345", "fl_67890"],
            ... )
        """
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

        if event_ids:
            normalized_resources.extend(
                [
                    CollectionResourceRef(resource_type=CollectionResourceType.Event, resource_id=event_id)
                    for event_id in event_ids
                ]
            )

        if file_ids:
            normalized_resources.extend(
                [
                    CollectionResourceRef(resource_type=CollectionResourceType.File, resource_id=file_id)
                    for file_id in file_ids
                ]
            )

        if session_ids:
            normalized_resources.extend(
                [
                    CollectionResourceRef(resource_type=CollectionResourceType.Session, resource_id=session_id)
                    for session_id in session_ids
                ]
            )

        request = CreateCollectionRequest(
            name=name,
            description=description,
            resource_type=resource_type,
            resources=normalized_resources,
            tags=tags,
            custom_fields=custom_fields,
        )

        record = roboto_client.post("v1/collections/create", data=request, caller_org_id=caller_org_id).to_record(
            CollectionRecord
        )

        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def list_all(
        cls,
        roboto_client: typing.Optional["RobotoClient"] = None,
        owner_org_id: Optional[str] = None,
        content_mode: CollectionContentMode = CollectionContentMode.SummaryOnly,
        sort_by: Optional[str] = None,
        sort_direction: Optional[SortDirection] = None,
    ) -> collections.abc.Generator["Collection", None, None]:
        """List the collections in an organization.

        Fetches one page of results at a time as the generator advances.

        Args:
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            owner_org_id: Organization whose collections to list. Defaults to the organization the caller acts in.
            content_mode: How much of each collection's members to return. Defaults to none, so ``datasets`` and the
                other member properties are empty and only ``resource_count`` describes the members.
            sort_by: Collection field to sort by, such as ``created``, ``name``, ``updated`` or ``resource_count``.
                ``None`` uses Roboto's default order.
            sort_direction: Direction to sort in. Used only when ``sort_by`` is set.

        Yields:
            Collections in the organization.

        Examples:
            List every collection in the organization:

            >>> for collection in Collection.list_all():
            ...     print(collection.collection_id, collection.name, collection.resource_count)

            List the most recently updated collections first:

            >>> from roboto.query import SortDirection
            >>> for collection in Collection.list_all(sort_by="updated", sort_direction=SortDirection.Descending):
            ...     print(collection.collection_id, collection.updated)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        spec = QuerySpecification()

        if sort_by:
            spec.sort_by = sort_by
            spec.sort_direction = sort_direction

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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Collection):
            return False
        return self.record == other.record

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
        """Time the collection was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the collection."""
        return self.__record.created_by

    @property
    def collection_id(self) -> str:
        """Unique ID of the collection, beginning with ``cl_``."""
        return self.__record.collection_id

    @property
    def name(self) -> typing.Optional[str]:
        """Human-readable name of the collection, or ``None`` if it has none.

        :py:attr:`~roboto.domain.collections.CollectionRecord.name` says whether names must be unique.
        """
        return self.__record.name

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the collection, or ``None`` if it has none."""
        return self.__record.description

    @staticmethod
    def _resource_id(resource: typing.Any, id_field: str) -> str | None:
        # A record parsed from a Roboto response holds each member as a dict, because resources is typed
        # list[Any]. A record built in code, as tests do, can hold model objects instead. Either form carries
        # resource_id (a reference) or id_field, such as dataset_id (a member's full record).
        if isinstance(resource, dict):
            return typing.cast(str | None, resource.get("resource_id", resource.get(id_field)))

        return typing.cast(str | None, getattr(resource, "resource_id", getattr(resource, id_field, None)))

    @property
    def datasets(self) -> list[str]:
        """IDs of the datasets in the collection.

        Empty when the collection was read with :py:attr:`~roboto.domain.collections.CollectionContentMode.SummaryOnly`.
        After a :py:attr:`~roboto.domain.collections.CollectionContentMode.Full` read, leaves out the members
        :py:attr:`~roboto.domain.collections.CollectionRecord.missing` lists.
        """
        return [
            resource_id
            for resource in self.__record.resources.get(CollectionResourceType.Dataset, [])
            if (resource_id := self._resource_id(resource, "dataset_id")) is not None
        ]

    @property
    def events(self) -> list[str]:
        """IDs of the events in the collection.

        Empty when the collection was read with :py:attr:`~roboto.domain.collections.CollectionContentMode.SummaryOnly`.
        Leaves out the events the caller cannot read, and, after a
        :py:attr:`~roboto.domain.collections.CollectionContentMode.Full` read, the members ``record.missing`` lists.
        """
        return [
            resource_id
            for resource in self.__record.resources.get(CollectionResourceType.Event, [])
            if (resource_id := self._resource_id(resource, "event_id")) is not None
        ]

    @property
    def files(self) -> list[str]:
        """IDs of the files in the collection.

        Empty when the collection was read with :py:attr:`~roboto.domain.collections.CollectionContentMode.SummaryOnly`.
        After a :py:attr:`~roboto.domain.collections.CollectionContentMode.Full` read, leaves out the members
        ``record.missing`` lists.
        """
        return [
            resource_id
            for resource in self.__record.resources.get(CollectionResourceType.File, [])
            if (resource_id := self._resource_id(resource, "file_id")) is not None
        ]

    @property
    def sessions(self) -> list[str]:
        """IDs of the sessions in the collection.

        Empty when the collection was read with :py:attr:`~roboto.domain.collections.CollectionContentMode.SummaryOnly`.
        After a :py:attr:`~roboto.domain.collections.CollectionContentMode.Full` read, leaves out the members
        ``record.missing`` lists.
        """
        return [
            resource_id
            for resource in self.__record.resources.get(CollectionResourceType.Session, [])
            if (resource_id := self._resource_id(resource, "session_id")) is not None
        ]

    @property
    def record(self) -> CollectionRecord:
        """Record of the collection that this instance holds."""
        return self.__record

    @property
    def resource_count(self) -> int:
        """Number of members the collection holds, in every content mode.

        :py:attr:`~roboto.domain.collections.CollectionRecord.resource_count` says which members it counts. It can be
        higher than the number of IDs ``datasets`` and the other member properties return.
        """
        return self.__record.resource_count

    @property
    @experimental
    def custom_fields(self) -> dict[str, typing.Any]:
        """Values of the custom fields the organization defines for collections, keyed by field name.

        :py:attr:`~roboto.domain.collections.CollectionRecord.custom_fields` says which fields appear as keys. A
        :py:attr:`~roboto.domain.custom_fields.CustomFieldType.Timestamp` value is an ISO 8601 string.
        """
        return self.__record.custom_fields

    @property
    def updated(self) -> datetime.datetime:
        """Time the collection was last updated, or the time it was created if it has never been updated."""
        return self.__record.updated

    @property
    def updated_by(self) -> str:
        """ID of the user who last updated the collection, or who created it if it has never been updated."""
        return self.__record.updated_by

    def add_dataset(self, dataset_id: str) -> "Collection":
        """Add a dataset to the collection.

        Adding a dataset that is already a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            dataset_id: ID of the dataset to add.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: The collection does not hold datasets.
            RobotoNotFoundException: No dataset has this ID.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.add_dataset("ds_12345")
        """
        return self.update(
            add_resources=[CollectionResourceRef(resource_id=dataset_id, resource_type=CollectionResourceType.Dataset)]
        )

    def add_event(self, event_id: str) -> "Collection":
        """Add an event to the collection.

        Adding an event that is already a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            event_id: ID of the event to add.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: The collection does not hold events.
            RobotoNotFoundException: No event has this ID, or the event belongs to another organization, or the
                caller cannot read it.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.add_event("ev_12345")
        """
        return self.update(
            add_resources=[CollectionResourceRef(resource_id=event_id, resource_type=CollectionResourceType.Event)]
        )

    def add_file(self, file_id: str) -> "Collection":
        """Add a file to the collection.

        Adding a file that is already a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            file_id: ID of the file to add.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: The collection does not hold files.
            RobotoNotFoundException: No file has this ID.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.add_file("fl_12345")
        """
        return self.update(
            add_resources=[CollectionResourceRef(resource_id=file_id, resource_type=CollectionResourceType.File)]
        )

    def add_session(self, session_id: str) -> "Collection":
        """Add a session to the collection.

        Adding a session that is already a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            session_id: ID of the session to add.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: The collection does not hold sessions.
            RobotoNotFoundException: No session has this ID, or the session belongs to another organization.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.add_session("se_12345")
        """
        return self.update(
            add_resources=[CollectionResourceRef(resource_id=session_id, resource_type=CollectionResourceType.Session)]
        )

    def changes(
        self, from_version: Optional[int] = None, to_version: Optional[int] = None
    ) -> collections.abc.Generator["CollectionChangeRecord", None, None]:
        """Yield the collection's revision history, oldest change first.

        Each update to the collection is one change, from one version to the next; version ``0`` is the collection as
        it was created. Each change leaves out the added and removed datasets, files and events the caller cannot read.

        Args:
            from_version: Version to start from: yields the changes applied to this version or later. ``0`` starts at
                the collection's creation. ``None`` leaves this end open.
            to_version: Version to stop at: yields the changes that produced this version or earlier. ``0`` yields
                nothing, because no change produces version ``0``. ``None`` leaves this end open.

        Yields:
            One :py:class:`~roboto.domain.collections.CollectionChangeRecord` for each update in the range.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> for change in collection.changes(from_version=2):
            ...     print(change.to_version, change.change_set.added_resources)
        """
        query: dict[str, typing.Any] = {}

        if from_version is not None:
            query["from_version"] = from_version

        if to_version is not None:
            query["to_version"] = to_version

        # Roboto returns every change in the range in one page, with no next_token.
        paginated_results = self.__roboto_client.get(
            f"v1/collections/id/{self.collection_id}/changes", query=query
        ).to_paginated_list(CollectionChangeRecord)

        for record in paginated_results.items:
            yield record

    def delete(self):
        """Delete the collection. This cannot be undone.

        Deletes none of its members. Deleting a collection that no longer exists succeeds and changes nothing.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.delete()
        """
        self.__roboto_client.delete(f"v1/collections/id/{self.collection_id}")

    def get_access(self) -> GetAccessResponse:
        """Deprecated. Fetch who this collection is shared with, as tuples.

        Use ``get_record_access`` instead, which returns the collection's restriction and grants. Calling this method
        issues a ``DeprecationWarning``. It sends API version 2026-11-05, the last version whose access route returns
        tuples.

        Returns:
            Every tuple on the collection, as :py:attr:`~roboto.auth.GetAccessResponse.relations` describes.
        """
        warnings.warn(
            "Collection.get_access is deprecated; use Collection.get_record_access, which reads the grant shape of "
            "API version 2026-11-19.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.__roboto_client.get(
            f"v1/collections/{self.collection_id}/access", headers=dict(_TUPLE_ACCESS_API_VERSION_HEADERS)
        ).to_record(GetAccessResponse)

    def edit_access(self, edit: EditAccessRequest) -> GetAccessResponse:
        """Deprecated. Add and remove the tuples that share this collection.

        Use ``edit_record_access`` instead, which takes grants and the collection's restriction. Calling this method
        issues a ``DeprecationWarning``. It sends API version 2026-11-05, the last version whose access route takes
        tuples. Adding the collection's organization group as ``associated_group`` unrestricts the collection, and
        removing it restricts it. Roboto checks every tuple before it changes anything.

        Args:
            edit: Tuples to add and remove. Each tuple's ``obj`` must be ``collection:<collection_id>`` for this
                collection, and its ``relation`` one of ``viewer``, ``editor``, ``deleter`` or ``associated_group``.

        Returns:
            Every tuple on the collection after the edit, as ``get_access`` returns them.

        Raises:
            RobotoInvalidRequestException: An added tuple names a principal in a form no share takes, the members of
                another organization, or a group other than the collection's organization group as
                ``associated_group``.
            RobotoUnauthorizedException: A tuple names another resource or a relation outside those listed above.
        """
        warnings.warn(
            "Collection.edit_access is deprecated; use Collection.edit_record_access, which sends the grant shape of "
            "API version 2026-11-19.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.__roboto_client.put(
            f"v1/collections/{self.collection_id}/access",
            data=edit,
            headers=dict(_TUPLE_ACCESS_API_VERSION_HEADERS),
        ).to_record(GetAccessResponse)

    def get_record_access(self) -> RecordAccessResponse:
        """Fetch who this collection is shared with.

        Returns:
            Whether members of the collection's organization need a grant to reach it, and its grants.

        Examples:
            >>> from roboto.domain.collections import Collection
            >>> collection = Collection.from_id("cl_12345")
            >>> access = collection.get_record_access()
            >>> for grant in access.grants:
            ...     print(grant.subject.id, grant.role)
        """
        return self.__roboto_client.get(f"v1/collections/{self.collection_id}/access").to_record(RecordAccessResponse)

    def edit_record_access(
        self,
        add: collections.abc.Sequence[AccessGrant] = (),
        remove: collections.abc.Sequence[AccessGrant] = (),
        restricted: Optional[bool] = None,
    ) -> RecordAccessResponse:
        """Change who this collection is shared with.

        The change is applied whole or not at all: grants in ``add`` are added, then grants in ``remove`` are removed,
        then the restriction is set. Sharing a collection does not share the datasets in it.

        A change requires permission to share the collection, which the :py:attr:`~roboto.auth.AccessRole.Editor` and
        :py:attr:`~roboto.auth.AccessRole.Deleter` roles on it give, as does being an admin or owner of its
        organization or, while the collection is unrestricted, a member. A call that changes nothing requires only
        permission to read the collection.

        Args:
            add: Grants to add. A grant to :py:attr:`~roboto.auth.AccessSubjectKind.OrgMembers` may name only the
                collection's organization, and :py:attr:`~roboto.auth.AccessSubjectKind.Everyone` may be given only
                :py:attr:`~roboto.auth.AccessRole.Viewer`.
            remove: Grants to remove, including a grant to another organization's members. Removing a grant the
                collection does not hold changes nothing.
            restricted: ``True`` makes members of the collection's organization need a grant to reach it, ``False``
                lets every member reach it, and ``None`` leaves it as it is.

        Returns:
            Who the collection is shared with after the change.

        Raises:
            RobotoInvalidRequestException: A ``User``, ``Group`` or ``OrgMembers`` subject has no ID, an ``Everyone``
                subject has an ID or a role other than ``Viewer``, a grant in ``add`` names the members of another
                organization, or, on a deployment that decides access from Roboto's own tables, a grant in ``add``
                names a group that is not one of the collection's organization's groups.

        Examples:
            >>> from roboto.auth import AccessGrant, AccessRole, AccessSubject
            >>> from roboto.domain.collections import Collection
            >>> collection = Collection.from_id("cl_12345")
            >>> access = collection.edit_record_access(
            ...     add=[AccessGrant(subject=AccessSubject.user("alex@example.com"), role=AccessRole.Viewer)],
            ...     restricted=True,
            ... )
            >>> access.restricted
            True
        """
        request = EditRecordAccessRequest(add=list(add), remove=list(remove), restricted=restricted)
        return self.__roboto_client.put(f"v1/collections/{self.collection_id}/access", data=request).to_record(
            RecordAccessResponse
        )

    def remove_dataset(self, dataset_id: str) -> "Collection":
        """Remove a dataset from the collection.

        Removing a dataset that is not a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            dataset_id: ID of the dataset to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.remove_dataset("ds_12345")
        """
        return self.update(
            remove_resources=[
                CollectionResourceRef(resource_id=dataset_id, resource_type=CollectionResourceType.Dataset)
            ]
        )

    def remove_file(self, file_id: str) -> "Collection":
        """Remove a file from the collection.

        Removing a file that is not a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            file_id: ID of the file to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.remove_file("fl_12345")
        """
        return self.update(
            remove_resources=[CollectionResourceRef(resource_id=file_id, resource_type=CollectionResourceType.File)]
        )

    def remove_event(self, event_id: str) -> "Collection":
        """Remove an event from the collection.

        Removing an event that is not a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            event_id: ID of the event to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.remove_event("ev_12345")
        """
        return self.update(
            remove_resources=[CollectionResourceRef(resource_id=event_id, resource_type=CollectionResourceType.Event)]
        )

    def remove_session(self, session_id: str) -> "Collection":
        """Remove a session from the collection.

        Removing a session that is not a member changes nothing but still creates a new version.
        It calls ``update``, whose failures also apply.

        Args:
            session_id: ID of the session to remove.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.remove_session("se_12345")
        """
        return self.update(
            remove_resources=[
                CollectionResourceRef(resource_id=session_id, resource_type=CollectionResourceType.Session)
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
        custom_fields_changeset: Optional[CustomFieldChangeset] = None,
    ) -> "Collection":
        """Update the collection's members, tags, name, description, or custom-field values.

        An argument left unset (``NotSet``) leaves that property unchanged. Every update creates a new version of the
        collection, even one that changes nothing.

        Args:
            add_resources: Resources to add. Each must be of the collection's resource type. A resource also listed
                in ``remove_resources`` ends up in the collection.
            add_tags: Tags to add. A tag also listed in ``remove_tags`` ends up removed.
            description: Human-readable description of the collection. ``None`` clears it.
            name: Human-readable name of the collection. ``None`` clears it.
            remove_resources: Resources to remove. Resources that are not members are ignored.
            remove_tags: Tags to remove.
            custom_fields_changeset: Changes to the collection's custom-field values. Each field it names must be a
                custom field defined for collections in the collection's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`. ``None`` leaves them unchanged.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoInvalidRequestException: A resource in ``add_resources`` is not of the collection's resource type.
            RobotoNotFoundException: A resource in ``add_resources`` does not exist, or is an event or session in
                another organization.
            RobotoUnauthorizedException: The caller's credential may only add to collections, and the call sets an
                argument other than ``add_resources`` or ``add_tags``.
            RobotoIllegalArgumentException: ``custom_fields_changeset`` names a field that is not a ready custom
                field for collections, or sets a value that does not match the field's type.

        Examples:
            Rename the collection and tag it:

            >>> collection = Collection.from_id("cl_12345")
            >>> collection.update(name="Highway test drives, 2024", add_tags=["reviewed"])

            Swap one dataset for another:

            >>> from roboto.domain.collections import CollectionResourceRef, CollectionResourceType
            >>> collection.update(
            ...     add_resources=[
            ...         CollectionResourceRef(resource_type=CollectionResourceType.Dataset, resource_id="ds_67890")
            ...     ],
            ...     remove_resources=[
            ...         CollectionResourceRef(resource_type=CollectionResourceType.Dataset, resource_id="ds_12345")
            ...     ],
            ... )
        """
        request = remove_not_set(
            UpdateCollectionRequest(
                name=name,
                description=description,
                add_tags=add_tags,
                remove_tags=remove_tags,
                add_resources=add_resources,
                remove_resources=remove_resources,
                custom_fields_changeset=custom_fields_changeset,
            )
        )

        self.__record = self.__roboto_client.put(f"v1/collections/id/{self.collection_id}", data=request).to_record(
            CollectionRecord
        )

        return self

    @experimental
    def set_custom_field(self, name: str, value: typing.Any) -> "Collection":
        """Set one custom-field value on the collection.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for collections in the collection's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
            value: Value to set. Must match the field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for collections, or ``value`` does not
                match its type.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.set_custom_field("review_status", "approved")
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields={name: value}))

    @experimental
    def clear_custom_field(self, name: str) -> "Collection":
        """Clear one custom-field value on the collection, so it reads as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            name: Name of a custom field defined for collections in the collection's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``name`` is not a ready custom field for collections.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.clear_custom_field("review_status")
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=[name]))

    @experimental
    def set_custom_fields(self, fields: dict[str, typing.Any]) -> "Collection":
        """Set several custom-field values on the collection, replacing any values those fields have.

        It calls ``update``, whose failures also apply.

        Args:
            fields: Values to set, keyed by field name. Each name must be a custom field defined for collections in
                the collection's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
                field's declared type.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for collections, or its value does not
                match the field's type.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.set_custom_fields({"review_status": "approved", "reviewer": "alex"})
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(set_fields=fields))

    @experimental
    def clear_custom_fields(self, names: collections.abc.Sequence[str]) -> "Collection":
        """Clear several custom-field values on the collection, so each reads as ``None``.

        It calls ``update``, whose failures also apply.

        Args:
            names: Names of custom fields defined for collections in the collection's organization, with status
                :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: A name is not a ready custom field for collections.

        Examples:
            >>> collection = Collection.from_id("cl_12345")
            >>> collection.clear_custom_fields(["review_status", "reviewer"])
        """
        return self.update(custom_fields_changeset=CustomFieldChangeset(clear_fields=list(names)))
