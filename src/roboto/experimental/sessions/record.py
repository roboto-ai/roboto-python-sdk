# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...pydantic.serializers import field_serializer_custom_field_values


class SessionRecord(pydantic.BaseModel):
    """Wire-format row for a session: an operational time window of a Device such as a drone flight,
    a vehicle drive, or a robot run.

    A Session unifies the recordings and auxiliary data produced during its window;
    it may span many files or cover only a slice of one.

    ``min_timestamp_ns`` and ``max_timestamp_ns`` span every file the Session holds: each file supplies the
    time window stated for it or, without one, the time span of the data the Session takes from it. The
    platform recomputes them in the same write as any change to the Session's files or to the anchors of
    their data, so the row never disagrees with its contents.
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
    """Latest time covered by the Session, in Unix-epoch nanoseconds. ``None`` while none of its files
    supplies a time: the Session holds no files, or only files added without a time window whose topic data
    has no time span registered yet."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """User-supplied metadata.

    Sessions cannot be filtered or sorted by ``metadata`` keys;
    for queryable structured attributes, define a custom field on the ``Session`` entity type.
    """

    min_timestamp_ns: typing.Optional[int] = None
    """Earliest time covered by the Session, in Unix-epoch nanoseconds. ``None`` while none of its files
    supplies a time: the Session holds no files, or only files added without a time window whose topic data
    has no time span registered yet."""

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

    @pydantic.field_serializer("custom_fields", when_used="json")
    def _serialize_custom_fields(self, custom_fields: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return field_serializer_custom_field_values(custom_fields)


class SessionFileRecord(pydantic.BaseModel):
    """Wire-format row for one file a Session holds, and the part of the file it holds.

    Time window contract (``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``):

    1. Set together or both ``None``; a window with only one bound is rejected on write.
    2. When both are ``None``, the Session holds the file's whole recorded time window.
    3. When both are set, ``min_wall_clock_timestamp_ns <= max_wall_clock_timestamp_ns``. Consumers
       iterating session data must keep only the file's data inside the closed interval
       ``[min_wall_clock_timestamp_ns, max_wall_clock_timestamp_ns]``.
    4. Values are nanoseconds since the Unix epoch, measured the same way as the parent Session's own bounds.
       A caller states this window in the file's own timestamps, on
       :py:class:`~roboto.experimental.sessions.SessionFile`; the platform adds the anchor covering the data
       the window names and reports the sum here, alongside the ``unix_epoch_offset_ns`` it added.

    Data range contract (``data_range``):

    1. ``None`` means the Session holds the whole file.
    2. ``(start, end)``: ``start`` is the first covered position; ``end`` is one past the last, with
       ``0 <= start < end``. Values are in the file's own units: stored-row positions (counted from 0), or
       nanoseconds of media time for video.
    3. Used when one file is shared by several sessions; the range names the slice of the file that belongs
       to this session.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When this file was added to the session."""

    created_by: str
    """User ID or service account that added this file to the session."""

    data_range: typing.Optional[tuple[int, int]] = None
    """The slice of the file the Session holds, as ``(start, end)`` in the file's own units, or ``None`` when
    it holds the whole file. ``start`` is the first covered position; ``end`` is one past the last."""

    fs_node_id: str
    """Identifier of the file."""

    max_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Upper bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file up to the end of its recorded time window;
    paired with ``min_wall_clock_timestamp_ns``."""

    min_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Lower bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file from the beginning of its recorded time window;
    paired with ``max_wall_clock_timestamp_ns``."""

    modified: typing.Optional[datetime.datetime] = None
    """When this file's place in the session was last modified."""

    modified_by: str
    """User ID or service account that last modified this file's place in the session."""

    session_id: str
    """Identifier of the session holding this file."""

    unix_epoch_offset_ns: typing.Optional[int] = None
    """Wall-clock instant of stored time 0 for the file's data the Session holds, in nanoseconds since the
    Unix epoch: what the platform added to the file's own timestamps to reach
    ``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``, and what to subtract to read any
    other instant back in the file's own timestamps. ``None`` when that data includes nothing registered,
    and when it sits at more than one instant, which leaves no single offset to report."""


class SessionFileView(pydantic.BaseModel):
    """One row of the ``GET /v1/sessions/id/<session_id>/files`` response: a file's place in a Session joined
    with display fields of the file itself.

    These fields come from the session's composition: ``file_id``, the optional time window
    ``min_wall_clock_timestamp_ns`` / ``max_wall_clock_timestamp_ns`` in Unix-epoch nanoseconds, the optional
    ``data_range`` slice (the window and the slice both under the contracts documented on
    :py:class:`SessionFileRecord`), and the ``unix_epoch_offset_ns`` the platform added to reach that window.
    Every other field is read from the file itself when the files are listed, and describes the file rather
    than its place in the session: ``created`` is when the file was created, not when it joined the session.
    None of those fields is part of a write.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When the file was created."""

    data_range: typing.Optional[tuple[int, int]] = None
    """The slice of the file the Session holds, as ``(start, end)`` in the file's own units, or ``None`` when
    it holds the whole file. ``start`` is the first covered position; ``end`` is one past the last."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset that contains the file."""

    file_id: str
    """Stable, unique identifier of the file."""

    max_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Upper bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file up to the end of its recorded time window;
    paired with ``min_wall_clock_timestamp_ns``."""

    min_wall_clock_timestamp_ns: typing.Optional[int] = None
    """Lower bound (inclusive) of the part of the file the Session holds, in Unix-epoch nanoseconds.
    ``None`` means the Session holds the file from the beginning of its recorded time window;
    paired with ``max_wall_clock_timestamp_ns``."""

    modified: typing.Optional[datetime.datetime] = None
    """When the file was last modified."""

    name: typing.Optional[str] = None
    """Name of the file (the final segment of ``relative_path``)."""

    origination: typing.Optional[str] = None
    """Provenance of the file, e.g. an invocation id or upload source."""

    relative_path: typing.Optional[str] = None
    """Path of the file within its dataset."""

    size: typing.Optional[int] = None
    """Size of the file in bytes."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the file."""

    unix_epoch_offset_ns: typing.Optional[int] = None
    """Wall-clock instant of stored time 0 for the file's data the Session holds, in nanoseconds since the
    Unix epoch: what the platform added to the file's own timestamps to reach
    ``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``, and what to subtract to read any
    other instant back in the file's own timestamps. ``None`` when that data includes nothing registered,
    and when it sits at more than one instant, which leaves no single offset to report."""
