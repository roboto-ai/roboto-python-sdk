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
    """One stored variant of a topic partition's data, optionally narrowed to a subset of its fields.

    A representation pairs a stored file with the data of a single topic partition.
    ``field_id`` narrows it to one field and the fields nested under it;
    ``None`` covers every field in the partition.

    The same partition can have several representations that differ in ``storage_format``,
    ``content_format``, and ``transformations``.
    A consumer picks the one whose attributes suit it: a viewer of image data, for example,
    may prefer a JPEG- or PNG-encoded variant over the untransformed original.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    content_format: typing.Optional[str] = None
    """
    The format of the data inside the stored file.
    For image data, this may be the image encoding (e.g. ``"jpeg"``, ``"png"``) on a transformed variant.
    ``None`` when unspecified.
    """

    created: typing.Optional[datetime.datetime] = None
    created_by: str
    """Identity of the user who created this representation."""

    field_id: typing.Optional[str] = None
    """
    The field this representation is narrowed to, covering that field and the fields nested under it.
    ``None`` when the representation covers every field in the partition.
    """

    file_version: typing.Optional[int] = None
    """
    The version of this representation's file that was current when the service read the representation. A read plan
    built from this representation names this version as the one to read. ``None`` when the file has no current
    version or the version is unknown. A write ignores this field.
    """

    fs_node_id: str
    """Identifier of the file backing this representation."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    org_id: str
    """Identifier of the org that owns this representation."""

    representation_id: str
    """Unique identifier of this representation."""

    size_bytes: typing.Optional[int] = None
    """Size in bytes of the file backing this representation, at :py:attr:`file_version`; ``None`` when unknown.

    A read plan built from this representation reports this size for the file. A write ignores this field.
    """

    storage_format: RepresentationStorageFormat
    """Container the representation data is stored in (e.g. MCAP, Parquet)."""

    topic_part_id: str
    """Identifier of the topic partition this representation belongs to."""

    transformations: list[str] = pydantic.Field(default_factory=list)
    """
    The transformations applied to the source data to produce this variant, in the order applied.
    Empty on the untransformed original.

    Each entry is a ``"<kind>:<param>"`` string whose ``<kind>`` is a
    :py:class:`~roboto.domain.topics.TransformationKind` member, e.g. ``["downsample:0.5", "encode:jpeg"]``.
    """


class RepresentationSelector(pydantic.BaseModel):
    """Describes the stored variants a representation choice accepts.

    The optional criteria ``storage_format``, ``content_format``, and
    ``transformations`` constrain the corresponding attributes of
    :py:class:`RepresentationRecord`. A variant must meet every criterion
    that is set; ``None`` places no requirement on that attribute.

    :py:class:`~roboto.experimental.topics.RepresentationPreference`
    determines which selectors are tried and whether missing coverage is
    refused. Missing coverage under a last selector with no criteria has the
    meaning documented by
    :py:attr:`~roboto.experimental.topics.ReadPlanPartition.scan_tasks`.

    Successor to :py:class:`roboto.domain.topics.RepresentationSelector`,
    used by :py:meth:`~roboto.domain.topics.Topic.get_data`.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    storage_format: typing.Optional[RepresentationStorageFormat] = None
    """Required container (e.g. MCAP, Parquet) by scalar equality; ``None`` does not constrain it."""

    content_format: typing.Optional[str] = None
    """Required content encoding (e.g. ``"jpeg"``) by scalar equality; ``None`` does not constrain it.

    There is no legacy carve-out: a representation whose ``content_format`` is ``None``
    does not satisfy an explicit request.
    """

    transformations: typing.Optional[tuple[str, ...]] = None
    """Required transformations; ``None`` does not constrain, ``()`` requires the untransformed original.

    A non-empty tuple is all-of: every token must be satisfied by some descriptor on the
    representation, which may carry additional transformations. A token is either a bare
    kind (e.g. ``"downsample"``), satisfied by any descriptor whose kind prefix equals it,
    or a full ``"<kind>:<param>"`` descriptor (e.g. ``"encode:jpeg"``), satisfied only by
    an exact match. The grammar is open string matching; the recognized vocabulary
    (:py:class:`~roboto.domain.topics.TransformationKind`) is enforced by the service at
    the request boundary, which rejects a token naming an unrecognized kind.
    """

    @classmethod
    def raw(cls) -> RepresentationSelector:
        """Select the untransformed original (a representation with no transformations)."""
        return cls(transformations=())

    def matches(self, representation: RepresentationRecord) -> bool:
        """Return whether ``representation`` satisfies every set axis of this selector."""
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
        """Return whether a single transformation token is satisfied by a representation's descriptors.

        A ``"<kind>:<param>"`` token must match a descriptor exactly; a bare-kind token is
        satisfied by any descriptor whose kind prefix equals it. Matching is pure string
        matching — vocabulary enforcement happens server-side, at the request boundary.
        """
        if ":" in transform:
            return transform in descriptors
        return any(descriptor.split(":", 1)[0] == transform for descriptor in descriptors)
