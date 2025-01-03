# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic


class CollectionResourceType(str, enum.Enum):
    """Type of resource added to a collection"""

    Dataset = "dataset"
    File = "file"


class CollectionContentMode(str, enum.Enum):
    """Desired content mode for representing a collection"""

    SummaryOnly = "summary_only"
    References = "references"
    Full = "full"


class CollectionResourceRef(pydantic.BaseModel):
    """Reference to a collection resource"""

    resource_type: CollectionResourceType
    resource_id: str
    resource_version: typing.Optional[str] = None


class CollectionRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a collection"""

    collection_id: str
    name: typing.Optional[str] = None
    description: typing.Optional[str] = None
    resources: dict[CollectionResourceType, list[typing.Any]] = pydantic.Field(
        default_factory=dict
    )
    missing: dict[CollectionResourceType, list[CollectionResourceRef]] = pydantic.Field(
        default_factory=dict
    )
    tags: list[str] = []
    version: int
    created: datetime.datetime
    created_by: str
    updated: datetime.datetime
    updated_by: str
    org_id: str


class CollectionChangeSet(pydantic.BaseModel):
    """Changeset for updating a collection"""

    added_resources: list[CollectionResourceRef] = pydantic.Field(default_factory=list)
    added_tags: list[str] = pydantic.Field(default_factory=list)
    removed_resources: list[CollectionResourceRef] = pydantic.Field(
        default_factory=list
    )
    removed_tags: list[str] = pydantic.Field(default_factory=list)
    field_changes: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class CollectionChangeRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a collection change record"""

    collection_id: str
    from_version: int
    to_version: int
    change_set: CollectionChangeSet
    applied: datetime.datetime
    applied_by: str
