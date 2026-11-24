# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import datetime
import typing

import pydantic

from ...domain.topics import RepresentationStorageFormat


class RepresentationRecord(pydantic.BaseModel):
    """Data record of a representation: one stored copy of a topic partition's data, in one file format.

    A topic partition is a part of a topic's data that one file holds. A representation holds either every field of
    the partition or, when ``field_id`` is set, one field and the fields nested under it. One partition can have
    several representations that differ in ``storage_format``, ``content_format`` and ``transformations``, such as
    the original image messages and a JPEG encoding of them, and a read chooses among them with
    ``RepresentationSelector``.

    Roboto keeps one record for each representation it stores; no SDK method returns one.
    ``RepresentationSelector.matches`` tests a record against a selector's criteria.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    content_format: typing.Optional[str] = None
    """Content format of the data in the representation's file, or ``None`` when the representation states none.

    Encoded images, for example, have the content format ``"jpeg"`` or ``"png"``.
    """

    created: typing.Optional[datetime.datetime] = None
    """Time the representation was created."""

    created_by: str
    """ID of the user who created the representation."""

    field_id: typing.Optional[str] = None
    """ID of the schema field the representation holds, or ``None`` when it holds every field of the partition.

    A representation that holds one field also holds the fields nested under it.
    """

    file_version: typing.Optional[int] = None
    """Version of the representation's file that was current when Roboto read the representation.

    ``None`` when the file has no current version or the version is unknown. A read plan built from this
    representation reads this version of the file. Roboto ignores this field when it stores a representation.
    """

    fs_node_id: str
    """ID of the file that holds the representation's data."""

    modified: typing.Optional[datetime.datetime] = None
    """Time the representation was last modified."""

    modified_by: str
    """ID of the user who last modified the representation."""

    org_id: str
    """ID of the organization that owns the representation."""

    representation_id: str
    """Unique ID of the representation."""

    size_bytes: typing.Optional[int] = None
    """Size in bytes of the representation's file at ``file_version``, or ``None`` when unknown.

    A read plan built from this representation reports this size for the file. Roboto ignores this field when it
    stores a representation.
    """

    storage_format: RepresentationStorageFormat
    """File format the representation's data is stored in."""

    topic_part_id: str
    """ID of the topic partition whose data the representation holds."""

    transformations: list[str] = pydantic.Field(default_factory=list)
    """Transformations applied to the partition's data to produce this representation, in the order applied.

    Empty for the original data. Each is a ``"<kind>:<param>"`` string, such as ``"downsample:0.5"`` or
    ``"encode:jpeg"``; :py:class:`~roboto.domain.topics.TransformationKind` lists the kinds.
    """


class RepresentationSelector(pydantic.BaseModel):
    """Criteria for choosing which of a topic partition's representations a read uses.

    A representation meets the selector when it meets every criterion set on it; a criterion left ``None`` places
    no requirement. Pass selectors in a ``RepresentationPreference``, which decides which selectors a read tries for
    each field and what happens when none of them covers the requested fields. When the last selector tried sets no
    criteria and still leaves fields uncovered, the read proceeds as ``ReadPlanPartition.scan_tasks`` describes.

    :py:class:`~roboto.domain.topics.RepresentationSelector` is the selector that
    :py:meth:`~roboto.domain.topics.Topic.get_data` takes. This one differs from it in ``content_format`` and
    ``transformations``, as those fields describe.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    storage_format: typing.Optional[RepresentationStorageFormat] = None
    """File format a representation's data must be stored in, or ``None`` for no requirement."""

    content_format: typing.Optional[str] = None
    """Content format a representation must have, such as ``"jpeg"``, or ``None`` for no requirement.

    A representation whose ``content_format`` is ``None`` does not meet a set value.
    """

    transformations: typing.Optional[tuple[str, ...]] = None
    """Transformations a representation must have, or ``None`` for no requirement.

    ``()`` requires a representation with no transformations: the original data. A non-empty tuple requires each
    token to be met by one of the representation's transformations, in any order, and the representation may have
    others too. A token is either:

    - A kind, such as ``"downsample"``, met by any transformation of that kind.
    - A ``"<kind>:<param>"`` string, such as ``"encode:jpeg"``, met only by that exact string.

    ``matches`` compares the strings and accepts any kind. Roboto rejects a read plan request whose token names a
    kind :py:class:`~roboto.domain.topics.TransformationKind` does not list, with ``RobotoInvalidRequestException``.
    """

    @classmethod
    def raw(cls) -> RepresentationSelector:
        """Build a selector that requires the original data: a representation with no transformations."""
        return cls(transformations=())

    def matches(self, representation: RepresentationRecord) -> bool:
        """Return whether ``representation`` meets every criterion set on this selector."""
        if self.storage_format is not None and representation.storage_format != self.storage_format:
            return False
        if self.content_format is not None and representation.content_format != self.content_format:
            return False
        if self.transformations is not None:
            if not self.transformations:
                return not representation.transformations
            return all(
                self.__transform_satisfied(transform, representation.transformations)
                for transform in self.transformations
            )
        return True

    def __transform_satisfied(self, transform: str, descriptors: collections.abc.Sequence[str]) -> bool:
        """Return whether one of ``descriptors`` meets the token ``transform``, as ``transformations`` describes."""
        if ":" in transform:
            return transform in descriptors
        return any(descriptor.split(":", 1)[0] == transform for descriptor in descriptors)
