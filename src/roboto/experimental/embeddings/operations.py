# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...sentinels import NotSet, NotSetType
from .record import (
    EmbeddingLevel,
    EmbeddingSessionCoverage,
    EmbeddingSessionCoverageRecord,
    EmbeddingSpaceKind,
)


class RegisterEmbeddingSpaceRequest(pydantic.BaseModel):
    """Request body for ``EmbeddingSpace.register``.

    Building it raises ``pydantic.ValidationError`` for a ``kind`` other than ``embedding`` or ``map``, or a level
    other than ``window``, ``event`` or ``session``.
    """

    name: str
    """Human-readable name of the space. Several spaces may share one."""

    kind: EmbeddingSpaceKind = "embedding"
    """Kind of space, ``embedding`` or ``map``, as ``EmbeddingSpaceKind`` describes.

    An ``embedding`` space's distances mean similarity; a ``map`` space is a 2-D layout computed from other spaces.
    """

    dim: int
    """Length of every row's vector, from 1 to 4,000. A ``map`` space's is 2."""

    levels: list[EmbeddingLevel]
    """Levels the space's rows may have, as ``EmbeddingLevel`` describes: at least one, none repeated."""

    window_ns: typing.Optional[int] = None
    """Length of every window row, in nanoseconds.

    Required, and positive, when ``levels`` holds ``window``; otherwise ``None``.
    """

    stride_ns: typing.Optional[int] = None
    """Time between the starts of a session's consecutive windows, in nanoseconds.

    Required, and positive, when ``levels`` holds ``window``; otherwise ``None``.
    """

    producer: str
    """Name of the producer that owns the space, such as ``roboto-embed@2`` or ``external``."""

    spec: dict[str, typing.Any]
    """Producer's definition of the space, stored as sent.

    Roboto derives the space's ID from it, so registering the same spec again returns the same space.
    """

    display: typing.Optional[dict[str, typing.Any]] = None
    """Keys readers of the space show when present: ``topics``, ``paths`` and ``description``."""

    producer_state: typing.Optional[dict[str, typing.Any]] = None
    """State the producer reads back on its next run, such as a fitted basis."""


class UpdateEmbeddingSpaceRequest(pydantic.BaseModel):
    """Request body for ``EmbeddingSpace.update``.

    ``EmbeddingSpace.retire`` sends it too. A field left unset (``NotSet``) is unchanged.
    """

    retired: typing.Union[bool, NotSetType] = NotSet
    """Whether the space is retired.

    Readers stop showing a retired space and it takes no new rows, but it keeps the rows it holds.
    """

    display: typing.Union[dict[str, typing.Any], None, NotSetType] = NotSet
    """Keys readers of the space show, as ``RegisterEmbeddingSpaceRequest.display`` describes.

    ``None`` clears them.
    """

    producer_state: typing.Union[dict[str, typing.Any], None, NotSetType] = NotSet
    """State the producer reads back on its next run. ``None`` clears it."""


class CreateEmbeddingBatchRequest(pydantic.BaseModel):
    """Request body for ``POST v1/embeddings/batches``, which starts a batch whose rows are uploaded as a Parquet file.

    Sent by ``EmbeddingSpace.put_rows`` for a batch too large to send in the request itself.
    """

    space_id: str
    """ID of the space the batch writes rows into."""

    sessions: dict[str, EmbeddingSessionCoverage] = pydantic.Field(default_factory=dict)
    """Coverage the batch records, by session ID. When the batch is committed:

    - A session with a ``no_rows_reason`` loses any rows it held in the space. A batch that also carries rows for it
      is rejected.
    - A session with ``replace_levels`` holds, at each of those levels, exactly the rows the batch carries for it, or
      none if the batch carries none.
    - A session the batch carries rows for but does not name keeps the coverage recorded for it before.
    """


class CreateEmbeddingBatchResponse(pydantic.BaseModel):
    """Response body of ``POST v1/embeddings/batches``."""

    batch_id: str
    """Unique ID of the new batch."""

    upload_url: str
    """URL to ``PUT`` the batch's Parquet file to, valid for one hour.

    The URL carries its own authorization, so the upload sends no ``Authorization`` header.
    """


class InlineEmbeddingBatchRequest(pydantic.BaseModel):
    """Request body for ``POST v1/embeddings/batches/inline``, which writes a batch whose rows the request carries.

    Sent by ``EmbeddingSpace.put_rows`` for a batch small enough to send this way.
    Roboto refuses a request body larger than 2 MB.
    """

    space_id: str
    """ID of the space the batch writes rows into."""

    sessions: dict[str, EmbeddingSessionCoverage] = pydantic.Field(default_factory=dict)
    """Coverage the batch records, by session ID, as ``CreateEmbeddingBatchRequest.sessions`` describes."""

    rows: list[dict[str, typing.Any]] = pydantic.Field(default_factory=list)
    """Rows of the batch, one dictionary per row keyed by column name.

    ``vector`` is a list of numbers, or base64 of little-endian float32 values.
    """


class EmbeddingCoverageResponse(pydantic.BaseModel):
    """Response body of ``EmbeddingSpace.coverage``.

    ``EmbeddingSpace.coverage_of`` reads it too.
    """

    space_id: str
    """ID of the space the coverage is in."""

    sessions: dict[str, EmbeddingSessionCoverageRecord] = pydantic.Field(default_factory=dict)
    """Coverage of each requested session that has coverage or rows in the space, by session ID.

    A session left out has not been embedded in the space.
    """
