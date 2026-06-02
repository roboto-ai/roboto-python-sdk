# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
import typing

import pydantic

from ..domain.topics import RepresentationStorageFormat


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

    field_id: typing.Optional[str] = None
    """
    The field this representation is narrowed to, covering that field and the fields nested under it.
    ``None`` when the representation covers every field in the partition.
    """

    fs_node_id: str
    """Identifier of the file backing this representation."""

    modified: typing.Optional[datetime.datetime] = None
    modified_by: str
    org_id: str
    representation_id: str
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
