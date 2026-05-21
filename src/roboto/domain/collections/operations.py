# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional, Union

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType
from roboto.updates import CustomFieldChangeset

from .record import CollectionResourceRef, CollectionResourceType


class CreateCollectionRequest(pydantic.BaseModel):
    """Request payload to create a collection"""

    description: Optional[str] = None
    name: Optional[str] = None
    resource_type: CollectionResourceType = CollectionResourceType.File
    resources: Optional[list[CollectionResourceRef]] = None
    tags: Optional[list[str]] = None

    custom_fields: Optional[dict[str, Any]] = None
    """Initial values for Ready custom fields on this collection.

    Each key must be the name of a :py:class:`~roboto.domain.custom_fields.CustomField`
    that is :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` for the
    caller's org and the :py:class:`~roboto.domain.custom_fields.TargetEntityType.Collection`
    entity type; each value must satisfy the field's declared type. Names that are
    undefined or not ``Ready``, and values that don't match the field's type, are
    rejected with a structured error.
    """


class UpdateCollectionRequest(pydantic.BaseModel):
    """Request payload to update a collection"""

    add_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet
    add_tags: Union[list[str], NotSetType] = NotSet
    description: Optional[Union[NotSetType, str]] = NotSet
    name: Optional[Union[NotSetType, str]] = NotSet
    remove_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet
    remove_tags: Union[list[str], NotSetType] = NotSet

    custom_fields_changeset: Optional[CustomFieldChangeset] = None
    """Changes to apply to Ready custom-field values on this collection.

    Each referenced field name must be a
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` custom field
    for this collection's org and the
    :py:class:`~roboto.domain.custom_fields.TargetEntityType.Collection`
    entity type; each ``set_fields`` value must satisfy the field's declared type.
    Names that are undefined or not ``Ready`` are rejected with a structured
    error. Field names not mentioned by the changeset are left unchanged.
    """

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
