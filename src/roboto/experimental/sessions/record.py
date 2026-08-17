# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic


class SessionRecord(pydantic.BaseModel):
    """Wire-format row for a session: an operational time window of a Device such as a drone flight,
    a vehicle drive, or a robot run.

    A Session unifies the recordings and auxiliary data produced during its window;
    it may span many files or cover only a slice of one.

    ``min_timestamp_ns`` and ``max_timestamp_ns`` are service-maintained aggregate bounds over the
    Session's contributions, recomputed by the service in the same transaction as any composition
    write (add/remove files), so the row never disagrees with its contents.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When the session was created."""

    created_by: str
    """User ID or service account that created the session."""

    custom_fields: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values for the custom fields defined on Sessions in this org.

    Every ``Ready`` custom field defined for ``(org_id, Session)`` appears as a
    key; values that have not been set surface as ``None`` rather than being
    absent. Empty when no custom fields are defined for the org.
    """

    description: typing.Optional[str] = None
    """Optional description of the Session."""

    max_timestamp_ns: typing.Optional[int] = None
    """Upper bound of the session's aggregate timestamps, in Unix-epoch nanoseconds.
    ``None`` until the session has at least one file contribution."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """User-supplied metadata.

    Sessions cannot be filtered or sorted by ``metadata`` keys;
    for queryable structured attributes, define a custom field on the ``Session`` entity type.
    """

    min_timestamp_ns: typing.Optional[int] = None
    """Lower bound of the session's aggregate timestamps, in Unix-epoch nanoseconds.
    ``None`` until the session has at least one file contribution."""

    modified: typing.Optional[datetime.datetime] = None
    """When the Session was last modified."""

    modified_by: str
    """User ID or service account that last modified the Session."""

    name: typing.Optional[str] = pydantic.Field(default=None, max_length=120)
    """A short, human-readable name for the Session. If provided, must be 120 characters or less."""

    org_id: str
    """Organization that owns the Session."""

    session_id: str
    """Stable, unique identifier for the Session."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """User-supplied tags.

    Sessions can be filtered by tag membership (e.g., ``tags CONTAINS '<tag>'``)
    but are not sortable by tag.
    """


class SessionFileRecord(pydantic.BaseModel):
    """Wire-format row for one file's contribution to a Session.

    Time window contract (``range_min_timestamp_ns`` and ``range_max_timestamp_ns``):

    1. Set together or both ``None``; a window with only one bound is rejected on write.
    2. When both are ``None``, the file contributes its whole recorded time window.
    3. When both are set, ``range_min_timestamp_ns <= range_max_timestamp_ns``. Consumers iterating
       session data must keep only the file's data inside the closed interval
       ``[range_min_timestamp_ns, range_max_timestamp_ns]``.
    4. Values are nanoseconds since the Unix epoch, measured the same way as the parent Session's own bounds.

    Data range contract (``data_range``):

    1. ``None`` means the contribution covers the whole file.
    2. ``(start, end)``: ``start`` is the first covered position; ``end`` is one past the last, with
       ``0 <= start < end``. Values are in the file's own units — stored-row positions (counted from
       0) for tabular files, nanoseconds of media time for video.
    3. Used when one file is shared by several sessions; the range names the slice of the
       file that belongs to this session.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When this file was added to the session."""

    created_by: str
    """User ID or service account that added this file to the session."""

    data_range: typing.Optional[tuple[int, int]] = None
    """The slice of the file covered by this contribution, as ``(start, end)`` in the file's own
    units, or ``None`` when the contribution covers the whole file. ``start`` is the first covered
    position; ``end`` is one past the last."""

    fs_node_id: str
    """Identifier of the contributing file."""

    modified: typing.Optional[datetime.datetime] = None
    """When this file's contribution was last modified."""

    modified_by: str
    """User ID or service account that last modified this file's contribution."""

    range_max_timestamp_ns: typing.Optional[int] = None
    """Upper bound (inclusive) of the file's contribution, in Unix-epoch nanoseconds.
    ``None`` means the contribution extends to the end of the file's recorded time window;
    paired with ``range_min_timestamp_ns``."""

    range_min_timestamp_ns: typing.Optional[int] = None
    """Lower bound (inclusive) of the file's contribution, in Unix-epoch nanoseconds.
    ``None`` means the contribution starts at the beginning of the file's recorded time window;
    paired with ``range_max_timestamp_ns``."""

    session_id: str
    """Identifier of the session this file contributes to."""


class SessionFileView(pydantic.BaseModel):
    """One row of the ``GET /v1/sessions/id/<session_id>/files`` response: a file's
    contribution to a Session joined with display fields of the file itself.

    The contribution fields (``file_id`` plus the optional time window,
    ``range_min_timestamp_ns`` / ``range_max_timestamp_ns`` in Unix-epoch
    nanoseconds, and the optional ``data_range`` slice, both under
    the contracts documented on :py:class:`SessionFileRecord`) come from the
    session's composition; every other field is a read-only projection the
    service resolves from the file row at listing time. The projected fields describe the file — e.g.
    ``created`` is when the file was created, not when it joined the session —
    and are never part of a write.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When the contributing file was created."""

    data_range: typing.Optional[tuple[int, int]] = None
    """The slice of the file covered by this contribution, as ``(start, end)`` in the file's own
    units, or ``None`` when the contribution covers the whole file. ``start`` is the first covered
    position; ``end`` is one past the last."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset that contains the contributing file."""

    file_id: str
    """Stable, unique identifier of the contributing file."""

    modified: typing.Optional[datetime.datetime] = None
    """When the contributing file was last modified."""

    name: typing.Optional[str] = None
    """Filename of the contributing file (the final segment of ``relative_path``)."""

    origination: typing.Optional[str] = None
    """Provenance of the contributing file, e.g. an invocation id or upload source."""

    range_max_timestamp_ns: typing.Optional[int] = None
    """Upper bound (inclusive) of the file's contribution, in Unix-epoch nanoseconds.
    ``None`` means the contribution extends to the end of the file's recorded time window;
    paired with ``range_min_timestamp_ns``."""

    range_min_timestamp_ns: typing.Optional[int] = None
    """Lower bound (inclusive) of the file's contribution, in Unix-epoch nanoseconds.
    ``None`` means the contribution starts at the beginning of the file's recorded time window;
    paired with ``range_max_timestamp_ns``."""

    relative_path: typing.Optional[str] = None
    """Path of the contributing file within its dataset."""

    size: typing.Optional[int] = None
    """Size of the contributing file in bytes."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the contributing file."""
