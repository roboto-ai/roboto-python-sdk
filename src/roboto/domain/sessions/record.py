# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...warnings import experimental


@experimental
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

    max_timestamp_ns: typing.Optional[int] = None
    """Upper bound of the session's aggregate timestamps, in Unix-epoch nanoseconds.
    ``None`` until the session has at least one file contribution."""

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


@experimental
class SessionFileRecord(pydantic.BaseModel):
    """Wire-format row for one file's contribution to a Session, optionally clipped to a sub-range of
    the file's recorded time.

    The clipping range is expressed in Unix-epoch nanoseconds,
    the same coordinate system as the parent Session's aggregate bounds.

    Range contract:

    1. ``range_min_timestamp_ns`` and ``range_max_timestamp_ns`` are set together or both ``None``;
       half-open windows are not a supported product concept and are rejected on write.
    2. When both are ``None``, the file contributes its whole recorded time window.
    3. When both are set, ``range_min_timestamp_ns <= range_max_timestamp_ns``, and consumers
       iterating session data must clamp the file's data to that
       ``[range_min_timestamp_ns, range_max_timestamp_ns]`` window.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    created: typing.Optional[datetime.datetime] = None
    """When this file was added to the session."""

    created_by: str
    """User ID or service account that added this file to the session."""

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
