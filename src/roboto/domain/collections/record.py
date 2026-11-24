# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...pydantic.serializers import field_serializer_custom_field_values


class CollectionResourceType(StrEnum):
    """Type of resource a collection holds."""

    Dataset = "dataset"
    Event = "event"
    File = "file"
    Session = "session"


class CollectionContentMode(StrEnum):
    """Amount of detail about a collection's members that a read of the collection returns."""

    SummaryOnly = "summary_only"
    """The collection's fields without its members.

    Leaves ``CollectionRecord.resources`` empty.
    """

    References = "references"
    """A ``CollectionResourceRef`` for each member.

    Leaves out the events the caller cannot read.
    """

    Full = "full"
    """Each member's full record.

    Lists the members Roboto cannot return in ``CollectionRecord.missing``.
    Fetching one collection in this mode fails with ``RobotoInvalidRequestException`` when the response would be too
    large; read it with ``References`` instead.
    """


class CollectionResourceRef(pydantic.BaseModel):
    """Reference to one member of a collection, by its type and ID."""

    resource_type: CollectionResourceType
    """Type of the resource. Roboto rejects adding a resource whose type differs from the collection's."""

    resource_id: str
    """ID of the resource, such as ``ds_12345`` for a dataset."""

    resource_version: typing.Optional[str] = None
    """Version of the resource the caller gave when adding the reference, or ``None`` if none was given.

    Roboto stores it with the reference, but a ``CollectionContentMode.Full`` read returns each member as it is now,
    whatever this value.
    """


class CollectionRecord(pydantic.BaseModel):
    """Data record of a collection, as the Roboto API returns it.

    A collection is a versioned container that groups resources of one type: datasets, files, events, or sessions.
    :py:class:`~roboto.domain.collections.Collection` wraps this record with methods that act on the collection, and
    exposes it as :py:attr:`~roboto.domain.collections.Collection.record`.
    """

    collection_id: str
    """Unique ID of the collection, beginning with ``cl_``."""

    name: typing.Optional[str] = None
    """Human-readable name of the collection, or ``None`` if it has none. Roboto does not require names to be unique."""

    description: typing.Optional[str] = None
    """Human-readable description of the collection, or ``None`` if it has none."""

    resource_type: CollectionResourceType = CollectionResourceType.File
    """Type of resource the collection holds.

    Fixed when the collection is created. Roboto rejects adding a resource of any other type with
    ``RobotoInvalidRequestException``.
    """

    resources: dict[CollectionResourceType, list[typing.Any]] = pydantic.Field(default_factory=dict)
    """Members of the collection, keyed by resource type.

    What each entry holds depends on the ``CollectionContentMode`` the collection was read with:

    - ``Full``: a dictionary of the member's record, such as a :py:class:`~roboto.domain.datasets.DatasetRecord`.
    - ``References``: a dictionary of a ``CollectionResourceRef``.
    - ``SummaryOnly``: nothing; the map is empty.

    :py:attr:`~roboto.domain.collections.Collection.datasets`,
    :py:attr:`~roboto.domain.collections.Collection.events`, :py:attr:`~roboto.domain.collections.Collection.files`
    and :py:attr:`~roboto.domain.collections.Collection.sessions` return the members' IDs from either form.
    """

    missing: dict[CollectionResourceType, list[CollectionResourceRef]] = pydantic.Field(default_factory=dict)
    """Members a ``CollectionContentMode.Full`` read does not show.

    Keyed by resource type. These are the members that no longer exist, the datasets, events and sessions in another
    organization, and the datasets, files and events the caller cannot read. Empty in the other content modes.
    """

    resource_count: int = 0
    """Number of members the collection holds, in every content mode.

    Set in ``CollectionContentMode.SummaryOnly`` reads too. Counts the members that ``missing`` lists or that a
    ``CollectionContentMode.References`` read leaves out, so it can be higher than the number of entries in
    ``resources``.
    """

    tags: list[str] = []
    """Tags on the collection."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the custom fields the organization defines for collections, keyed by field name.

    Every collection custom field in the :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state
    appears as a key, mapped to ``None`` when the collection has no value for it. Fields in any other state are
    absent, so the map is empty when no collection custom field is in that state.
    """

    version: int
    """Version of the collection: ``0`` when it is created, and one higher after each update.

    Roboto sets it; no request does. :py:meth:`~roboto.domain.collections.Collection.changes` yields a
    ``CollectionChangeRecord`` for each update.
    """

    created: datetime.datetime
    """Time the collection was created."""

    created_by: str
    """ID of the user who created the collection."""

    updated: datetime.datetime
    """Time the collection was last updated, or the time it was created if it has never been updated."""

    updated_by: str
    """ID of the user who last updated the collection, or who created it if it has never been updated."""

    org_id: str
    """ID of the organization that owns the collection."""

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)


class CollectionChangeSet(pydantic.BaseModel):
    """Changes that one update made to a collection.

    Carried in ``CollectionChangeRecord.change_set``.
    """

    added_resources: list[CollectionResourceRef] = pydantic.Field(default_factory=list)
    """Resources the update added, as the caller gave them, including any that were already members."""

    added_tags: list[str] = pydantic.Field(default_factory=list)
    """Tags the update added."""

    removed_resources: list[CollectionResourceRef] = pydantic.Field(default_factory=list)
    """Resources the update removed, as the caller gave them, including any that were not members."""

    removed_tags: list[str] = pydantic.Field(default_factory=list)
    """Tags the update removed."""

    field_changes: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """New values of the ``name`` and ``description`` the update set, keyed by field name.

    Holds only the fields the update set. Changes to custom fields are not recorded.
    """


class CollectionChangeRecord(pydantic.BaseModel):
    """Data record of one update to a collection, as the Roboto API returns it.

    :py:meth:`~roboto.domain.collections.Collection.changes` yields these, oldest first.
    """

    collection_id: str
    """ID of the collection the update changed."""

    from_version: int
    """Version of the collection before the update."""

    to_version: int
    """Version of the collection the update produced, one higher than ``from_version``."""

    change_set: CollectionChangeSet
    """What the update changed."""

    applied: datetime.datetime
    """Time the update was applied."""

    applied_by: str
    """ID of the user who made the update."""
