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
    """Request body for :py:meth:`~roboto.domain.collections.Collection.create`."""

    description: Optional[str] = None
    """Human-readable description of the collection."""

    name: Optional[str] = None
    """Human-readable name of the collection. Roboto does not require names to be unique."""

    resource_type: CollectionResourceType = CollectionResourceType.File
    """Type of resource the collection holds. It cannot change after the collection is created."""

    resources: Optional[list[CollectionResourceRef]] = None
    """Resources the collection starts with. ``None`` creates an empty collection.

    Each resource must be of ``resource_type``, or the request fails with
    :py:class:`~roboto.exceptions.RobotoInvalidRequestException`, and must exist, or it fails with
    :py:class:`~roboto.exceptions.RobotoNotFoundException`.
    """

    tags: Optional[list[str]] = None
    """Tags to set on the collection."""

    custom_fields: Optional[dict[str, Any]] = None
    """Initial values for the collection's custom fields, keyed by field name. ``None`` sets none.

    Each name must be a :py:class:`~roboto.domain.custom_fields.CustomField` defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Collection` in the organization the collection is created
    in, with status :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each value must match that
    field's declared type. Otherwise the request fails with
    :py:class:`~roboto.exceptions.RobotoIllegalArgumentException`.
    """


class UpdateCollectionRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.collections.Collection.update`.

    A field left at its default (``NotSet`` or ``None``) is unchanged. Every update creates a new version of the
    collection, which :py:meth:`~roboto.domain.collections.Collection.changes` lists.
    """

    add_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet
    """Resources to add to the collection.

    Each resource must be of the collection's resource type, or the request fails with
    :py:class:`~roboto.exceptions.RobotoInvalidRequestException`, and must exist, or it fails with
    :py:class:`~roboto.exceptions.RobotoNotFoundException`. A resource also listed in ``remove_resources`` ends up
    in the collection.
    """

    add_tags: Union[list[str], NotSetType] = NotSet
    """Tags to add to the collection. A tag also listed in ``remove_tags`` ends up removed."""

    description: Optional[Union[NotSetType, str]] = NotSet
    """Human-readable description of the collection. ``None`` clears it."""

    name: Optional[Union[NotSetType, str]] = NotSet
    """Human-readable name of the collection. ``None`` clears it."""

    remove_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet
    """Resources to remove from the collection."""

    remove_tags: Union[list[str], NotSetType] = NotSet
    """Tags to remove from the collection."""

    custom_fields_changeset: Optional[CustomFieldChangeset] = None
    """Changes to the collection's custom-field values. ``None`` leaves them unchanged.

    Each field name the changeset references must be a custom field defined for
    :py:attr:`~roboto.domain.custom_fields.TargetEntityType.Collection` in the collection's organization, with status
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`, and each ``set_fields`` value must match that
    field's declared type. Otherwise the request fails with
    :py:class:`~roboto.exceptions.RobotoIllegalArgumentException`. See
    :py:class:`~roboto.updates.CustomFieldChangeset`.
    """

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
