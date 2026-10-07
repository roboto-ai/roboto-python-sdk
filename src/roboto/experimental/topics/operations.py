# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import pydantic

from ...domain.topics.record import _INT64_MAX
from ...time import _EpochNanosecondsFromTime
from .record import RepresentationSelector


class FieldAddress(pydantic.BaseModel):
    """Addresses a schema field, and the subtree nested under it, by exactly one of two forms.

    A ``path`` names the field by its ``path_in_schema`` components directly (no
    string delimiter, so a component may itself contain a ``.``); a ``field_id``
    names it opaquely and resolves server-side to the same path. Either form
    designates the field and every field nested under it.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    path: typing.Optional[tuple[str, ...]] = None
    """The field's ``path_in_schema`` components; ``()`` addresses the schema root."""

    field_id: typing.Optional[str] = None
    """The field's opaque id (``sf_*``)."""

    @pydantic.model_validator(mode="after")
    def _exactly_one(self) -> FieldAddress:
        # `is None` is load-bearing: path=() is a valid (root) address, not "unset".
        if (self.path is None) == (self.field_id is None):
            raise ValueError("FieldAddress must set exactly one of 'path' or 'field_id'")
        return self


class RepresentationOverride(pydantic.BaseModel):
    """Applies a representation selector to one field subtree, overriding the request default."""

    model_config = pydantic.ConfigDict(frozen=True)

    field: FieldAddress
    """The subtree this override covers."""

    selector: RepresentationSelector
    """The selector to apply within that subtree."""


class RepresentationPreference(pydantic.BaseModel):
    """Selects which stored variant of each field to read, per subtree.

    A ``default`` selector applies to every field unless a more specific
    ``override`` covers it. Where several overrides cover a field, the one whose
    addressed subtree is the longest prefix of the field's path wins; this rule
    is :py:meth:`selector_for`.

    The governing selector and its matching rule are contract: a selector
    never substitutes a non-matching variant, and a read fails when a
    selector that sets any criterion is satisfied by no stored representation
    for a requested field — the plan never silently omits a field an explicit
    requirement covers. Which of the representations that satisfy the
    selector the service ultimately schedules is service policy and may
    change between releases.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    default: RepresentationSelector = RepresentationSelector()
    """The selector applied to any field no override covers; matches anything when unset."""

    overrides: tuple[RepresentationOverride, ...] = ()
    """Per-subtree selector overrides, resolved longest-matching-prefix wins."""

    def selector_for(self, field_path: tuple[str, ...]) -> RepresentationSelector:
        """Resolve the selector that governs the field at ``field_path``, longest-matching-prefix wins.

        An override applies when its addressed subtree path is a prefix of
        ``field_path``; among applicable overrides the deepest subtree wins,
        and a field no override covers gets ``default``.

        Args:
            field_path: The ``path_in_schema`` components of the field whose
                selector is being resolved.

        Returns:
            The governing selector.

        Raises:
            ValueError: An override addresses its subtree by ``field_id``.
                Resolving a ``field_id`` to a path takes the schema, which this
                value object does not hold; resolve every override address to
                its ``path`` form first.
        """
        chosen = self.default
        chosen_depth = -1
        for override in self.overrides:
            subtree_path = override.field.path
            if subtree_path is None:
                raise ValueError(
                    "selector_for requires every override to address its subtree by path; "
                    f"resolve field_id {override.field.field_id!r} to its path form first"
                )
            if field_path[: len(subtree_path)] == subtree_path and len(subtree_path) > chosen_depth:
                chosen = override.selector
                chosen_depth = len(subtree_path)
        return chosen


class ReadPlanRequest(pydantic.BaseModel):
    """The body of a read-plan request: the logical read question to resolve into a physical plan.

    ``session_id``, ``file_id``, ``dataset_id`` and ``device_id`` are restrictions: each limits the read to the topic's
    data in one session, file, dataset or device. Every restriction the request names narrows the read, and
    restrictions named together intersect.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start_time: typing.Optional[int] = None
    """Inclusive window lower bound, absolute Unix-epoch nanoseconds.

    May be ``None`` only when the request names a ``file_id``, ``dataset_id`` or ``device_id``; the bound then
    defaults to the earliest time of the topic's data within the request's restrictions, across every timeline
    source. An explicit bound narrows the read and never widens it."""

    end_time: typing.Optional[int] = None
    """Inclusive window upper bound, absolute Unix-epoch nanoseconds.

    May be ``None`` on the same terms as ``start_time``; the bound then defaults to the latest time of the topic's
    data within the request's restrictions."""

    fields_include: typing.Optional[tuple[FieldAddress, ...]] = None
    """Field subtrees to project; ``None`` projects every field."""

    fields_exclude: typing.Optional[tuple[FieldAddress, ...]] = None
    """Field subtrees to drop from the projection; ``None`` drops none."""

    prefer: typing.Optional[RepresentationPreference] = None
    """Per-subtree representation preference; ``None`` applies default selection everywhere."""

    schema_id: typing.Optional[str] = None
    """Schema to use, by id, or ``None`` to default to the sole in-window schema."""

    schema_checksum: typing.Optional[str] = None
    """Schema to use, by checksum, or ``None``."""

    timeline_source_id: typing.Optional[str] = None
    """Timeline source to resolve partition extents with, by id, or ``None``."""

    timeline_source_name: typing.Optional[str] = None
    """Timeline source to resolve partition extents with, by name, or ``None``."""

    session_id: typing.Optional[str] = None
    """Limits the read to the topic's data in this Session's files, each over the part of its time span the Session
    holds; ``None`` adds no session restriction."""

    file_id: typing.Optional[str] = None
    """Limits the read to the topic's data in this file; ``None`` adds no file restriction."""

    dataset_id: typing.Optional[str] = None
    """Limits the read to the topic's data in this dataset's files; ``None`` adds no dataset restriction."""

    device_id: typing.Optional[str] = None
    """Limits the read to the topic's data in this device's files; ``None`` adds no device restriction.

    A file belongs to the device it names, or, when it names none, to the device its dataset names."""

    @pydantic.model_validator(mode="after")
    def _window_ordered(self) -> ReadPlanRequest:
        if self.start_time is not None and self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return self

    @pydantic.model_validator(mode="after")
    def _bounds_given_or_defaultable(self) -> ReadPlanRequest:
        names_file_dataset_or_device = (
            self.file_id is not None or self.dataset_id is not None or self.device_id is not None
        )
        if (self.start_time is None or self.end_time is None) and not names_file_dataset_or_device:
            raise ValueError(
                "start_time and end_time are required unless the request names a file_id, dataset_id or device_id"
            )
        return self

    @pydantic.model_validator(mode="after")
    def _alternate_identifiers_mutually_exclusive(self) -> ReadPlanRequest:
        if self.schema_id is not None and self.schema_checksum is not None:
            raise ValueError("specify at most one of 'schema_id' or 'schema_checksum'")
        if self.timeline_source_id is not None and self.timeline_source_name is not None:
            raise ValueError("specify at most one of 'timeline_source_id' or 'timeline_source_name'")
        return self

    @pydantic.model_validator(mode="after")
    def _filters_non_empty(self) -> ReadPlanRequest:
        # an empty tuple is a contradiction ("include no subtrees"),
        # not a request to project everything, so it is rejected rather than silently widened to the whole schema.
        if self.fields_include is not None and not self.fields_include:
            raise ValueError("'fields_include' must name at least one subtree; pass None to project every field")
        if self.fields_exclude is not None and not self.fields_exclude:
            raise ValueError("'fields_exclude' must name at least one subtree; pass None to drop none")
        return self


class SetTopicUnixOffsetRequest(pydantic.BaseModel):
    """Request body for ``POST /v2/topics/id/<topic_id>/unix-offset``.

    Anchors one Session's data on one topic to wall-clock time. See
    :py:meth:`~roboto.experimental.topics.Topic.set_unix_offset` for the write's reach.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    session_id: str
    """Session whose data is anchored. Its files decide which of the topic's stored data the write reaches;
    the topic's data in files outside the Session keeps the anchor it already has."""

    unix_epoch_offset_ns: _EpochNanosecondsFromTime
    """Wall-clock instant of stored time 0 for the Session's data on this topic, in nanoseconds since the Unix epoch;
    each stored timestamp then reads as ``stored_time_ns + unix_epoch_offset_ns``. Must fall after the Unix epoch,
    and must fit in the signed 64-bit integer the platform stores it in.
    Also accepts any :py:data:`roboto.time.Time` at runtime, read as :py:func:`roboto.time.to_epoch_nanoseconds`
    reads it; convert with that function first to satisfy a type checker."""

    @pydantic.field_validator("unix_epoch_offset_ns")
    @classmethod
    def _offset_positive_and_within_int64(cls, value: int) -> int:
        if value == 0:
            raise ValueError(
                "unix_epoch_offset_ns must be positive; to return the session's data on this topic to "
                "an offset of 0, clear its anchor instead with Topic.clear_unix_offset() "
                "(DELETE /v2/topics/id/<topic_id>/unix-offset?session_id=<session_id>)"
            )
        if not 0 < value <= _INT64_MAX:
            raise ValueError("unix_epoch_offset_ns must be a time after the Unix epoch and below 2**63 ns")
        return value
