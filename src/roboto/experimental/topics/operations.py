# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import pydantic

from ...int64 import INT64_MAX, INT64_MIN
from ...time import _EpochNanosecondsFromTime
from .record import RepresentationSelector


class FieldAddress(pydantic.BaseModel):
    """Address of a topic schema field and every field nested under it, by the field's path or its ID.

    Set exactly one of ``path`` and ``field_id``. Building it with both or neither raises ``pydantic.ValidationError``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    path: typing.Optional[tuple[str, ...]] = None
    """Components of the field's path in the schema, in order from the schema root; ``()`` addresses the root.

    Each component is a separate string, so a component may itself contain a ``.``."""

    field_id: typing.Optional[str] = None
    """ID of the field, beginning with ``sf_``, which Roboto resolves to the field's path."""

    @pydantic.model_validator(mode="after")
    def _exactly_one(self) -> FieldAddress:
        # Compare with None: path=() addresses the schema root, so an empty path counts as set.
        if (self.path is None) == (self.field_id is None):
            raise ValueError("FieldAddress must set exactly one of 'path' or 'field_id'")
        return self


class RepresentationOverride(pydantic.BaseModel):
    """Selector of stored representations for one field subtree, in place of the preference's default and fallbacks.

    Carried in ``RepresentationPreference.overrides``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    field: FieldAddress
    """Address of the subtree this override covers."""

    selector: RepresentationSelector
    """Selector for every field in that subtree, and the only one tried for them."""


class RepresentationPreference(pydantic.BaseModel):
    """Choice of which stored representations of a topic's data to read, per field subtree.

    A representation is one stored form of a partition's data, such as the original recording or a JPEG-encoded copy,
    and a partition is the part of a topic's data stored in one file, or in one slice of a file several sessions share.
    For each field, ``selectors_for`` returns the selectors to try, in order: the selector of the deepest override
    covering the field, alone, or else ``default`` followed by ``fallbacks``.

    Each partition takes the first selector whose matching representations hold every requested field. With
    overrides, each subtree that ``default`` governs chooses separately. A choice reads one selector's matching
    representations; it never combines partial coverage from different selectors.

    When no selector's representations hold every requested field, the last selector tried decides:

    - A last selector that sets a criterion fails the read with ``RobotoInvalidRequestException``.
    - A last selector that sets no criteria reads each subtree that some representation holds from that
      representation, and leaves the remaining fields without coverage, as ``ReadPlanPartition.scan_tasks`` describes.

    No selector admits a representation that fails its criteria. Which of several matching representations Roboto
    reads may change between versions of Roboto.

    Examples:
        Read each partition's stored JPEG, or its stored PNG, or whatever it holds:

        >>> preference = RepresentationPreference(
        ...     default=RepresentationSelector(content_format="jpeg"),
        ...     fallbacks=(RepresentationSelector(content_format="png"), RepresentationSelector()),
        ... )
    """

    model_config = pydantic.ConfigDict(frozen=True)

    default: RepresentationSelector = RepresentationSelector()
    """Selector tried first for any field no override covers.

    Left unset, it sets no criteria and admits every representation."""

    fallbacks: tuple[RepresentationSelector, ...] = ()
    """Selectors tried in order after ``default``, partition by partition, for fields no override covers.

    Defaults to none."""

    overrides: tuple[RepresentationOverride, ...] = ()
    """Selectors for particular field subtrees.

    For each field, the override with the deepest subtree covering it applies. Defaults to none."""

    def selector_for(self, field_path: tuple[str, ...]) -> RepresentationSelector:
        """Return the selector tried first for the field at ``field_path``.

        It is the first selector ``selectors_for`` returns, and the call raises what that method raises.

        Args:
            field_path: Components of the field's path in the schema, in order from the schema root.
        """
        return self.selectors_for(field_path)[0]

    def selectors_for(self, field_path: tuple[str, ...]) -> tuple[RepresentationSelector, ...]:
        """Return the selectors to try for the field at ``field_path``, most preferred first.

        An override applies when its subtree's path is a prefix of ``field_path``. Among the overrides that apply, the
        one with the longest path wins, and the first listed wins a tie; its selector is the only one returned. A field
        no override covers gets ``default`` and then ``fallbacks``. The override's address alone decides this, so an
        override whose selector equals ``default`` still gets no fallbacks.

        Args:
            field_path: Components of the field's path in the schema, in order from the schema root.

        Raises:
            ValueError: An override addresses its subtree by ``field_id``. Resolving a field ID to a path takes the
                topic schema, which this model does not hold, so give every override's address as a ``path``.
        """
        chosen: typing.Optional[RepresentationSelector] = None
        chosen_depth = -1
        for override in self.overrides:
            subtree_path = override.field.path
            if subtree_path is None:
                raise ValueError(
                    "selectors_for requires every override to address its subtree by path; "
                    f"resolve field_id {override.field.field_id!r} to its path form first"
                )
            if field_path[: len(subtree_path)] == subtree_path and len(subtree_path) > chosen_depth:
                chosen = override.selector
                chosen_depth = len(subtree_path)
        return (self.default, *self.fallbacks) if chosen is None else (chosen,)


class ReadPlanRequest(pydantic.BaseModel):
    """Request body for ``Topic.get_data_as_record_batches``: the read of a topic's data for Roboto to plan.

    Roboto answers with a ``ReadPlan`` naming the stored files to fetch and how to read them. ``Topic.get_data`` and
    ``Topic.get_data_as_df`` read through ``Topic.get_data_as_record_batches``.

    ``session_id``, ``file_id``, ``dataset_id`` and ``device_id`` are restrictions: each limits the read to the topic's
    data in one session, file, dataset or device. Every restriction the request names narrows the read, and
    restrictions named together intersect.

    Building it raises ``pydantic.ValidationError`` when:

    - ``start_time`` or ``end_time`` is outside the range ``start_time`` states.
    - ``end_time`` is before ``start_time``.
    - ``start_time`` or ``end_time`` is ``None`` and the request names no restriction.
    - Both ``schema_id`` and ``schema_checksum`` are set, or both ``timeline_source_id`` and ``timeline_source_name``.
    - ``fields_include`` or ``fields_exclude`` is an empty tuple. An empty tuple asks for no subtrees, so it is
      rejected rather than read as every field; pass ``None`` instead.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start_time: typing.Optional[int] = pydantic.Field(default=None, ge=INT64_MIN, le=INT64_MAX)
    """Inclusive start of the time range, in nanoseconds since the Unix epoch.

    Must be from :py:const:`~roboto.int64.INT64_MIN` to :py:const:`~roboto.int64.INT64_MAX` (1677-09-21 to
    2262-04-11 UTC), the range of timestamps Roboto stores.

    May be ``None`` only when the request names a restriction; the read then has no lower limit. A bound given with a
    restriction narrows the read further and never extends it past what the restriction holds."""

    end_time: typing.Optional[int] = pydantic.Field(default=None, ge=INT64_MIN, le=INT64_MAX)
    """Inclusive end of the time range, in the same form and range as ``start_time``.

    May be ``None`` on the same terms as ``start_time``; the read then has no upper limit."""

    fields_include: typing.Optional[tuple[FieldAddress, ...]] = None
    """Field subtrees to read; ``None`` reads every field."""

    fields_exclude: typing.Optional[tuple[FieldAddress, ...]] = None
    """Field subtrees to leave out of the read; ``None`` leaves out none."""

    prefer: typing.Optional[RepresentationPreference] = None
    """Which stored representations to read, per field subtree.

    ``None`` is the same as ``RepresentationPreference()``, which admits every representation."""

    schema_id: typing.Optional[str] = None
    """ID of the topic schema to read under, beginning with ``ts_``.

    ``None``, with no ``schema_checksum``, uses the one schema of the topic's data in the time range. When that data
    has more than one schema, Roboto raises ``RobotoInvalidRequestException``, and the request must name one."""

    schema_checksum: typing.Optional[str] = None
    """Checksum of the topic schema to read under, in place of ``schema_id``; ``None`` names no schema by checksum."""

    timeline_source_id: typing.Optional[str] = None
    """ID of the timeline source that places each partition's data in time.

    ``None``, with no ``timeline_source_name``, uses the timeline source the schema marks as its default."""

    timeline_source_name: typing.Optional[str] = None
    """Name of the timeline source that places each partition's data in time, in place of ``timeline_source_id``.

    ``None`` names no source by name."""

    session_id: typing.Optional[str] = None
    """ID of the session to restrict the read to, beginning with ``se_``.

    The read takes the topic's data in the session's files, each over the part of its time span the session holds.
    ``None`` adds no session restriction."""

    file_id: typing.Optional[str] = None
    """ID of the file whose data on the topic the read is restricted to; ``None`` adds no file restriction."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset whose files' data on the topic the read is restricted to.

    ``None`` adds no dataset restriction."""

    device_id: typing.Optional[str] = None
    """ID of the device whose files' data on the topic the read is restricted to; ``None`` adds no device restriction.

    A file belongs to the device it names, or, when it names none, to the device its dataset names."""

    accepts_element_selection: bool = False
    """Whether the client sending the request can read a plan that selects single elements of a named array.

    When true, ``fields_include`` and ``fields_exclude`` may address one element of a named array as the array's
    path plus the element's name. When false, Roboto refuses such an address as it refuses any path absent from the
    schema, with ``RobotoInvalidRequestException``."""

    @pydantic.model_validator(mode="after")
    def _window_ordered(self) -> ReadPlanRequest:
        if self.start_time is not None and self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return self

    @pydantic.model_validator(mode="after")
    def _both_bounds_unless_a_scope_is_named(self) -> ReadPlanRequest:
        names_a_scope = (
            self.session_id is not None
            or self.file_id is not None
            or self.dataset_id is not None
            or self.device_id is not None
        )
        if (self.start_time is None or self.end_time is None) and not names_a_scope:
            raise ValueError(
                "start_time and end_time are required unless the request names a session_id, file_id, dataset_id or "
                "device_id"
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
        if self.fields_include is not None and not self.fields_include:
            raise ValueError("'fields_include' must name at least one subtree; pass None to project every field")
        if self.fields_exclude is not None and not self.fields_exclude:
            raise ValueError("'fields_exclude' must name at least one subtree; pass None to drop none")
        return self


class SetTopicUnixOffsetRequest(pydantic.BaseModel):
    """Request body for ``Topic.set_unix_offset``: the wall-clock anchor for one session's data on one topic.

    ``Topic.set_unix_offset`` describes which data the write reaches. Building it raises ``pydantic.ValidationError``
    when ``unix_epoch_offset_ns`` is not a :py:const:`~roboto.time.Time`, is zero or before the Unix epoch, or is
    greater than :py:const:`~roboto.int64.INT64_MAX`. To return the data to an offset of 0, use
    ``Topic.clear_unix_offset``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    session_id: str
    """ID of the session whose data on the topic is anchored, beginning with ``se_``.

    The session's files decide which of the topic's stored data the write reaches; the topic's data in files outside
    the session keeps the anchor it has."""

    unix_epoch_offset_ns: _EpochNanosecondsFromTime
    """Wall-clock instant of stored time 0 for the session's data on the topic, in nanoseconds since the Unix epoch.

    Each stored timestamp then reads as ``stored_time_ns + unix_epoch_offset_ns``. Must be after the Unix epoch and at
    most ``INT64_MAX``. Building the model also accepts any ``Time``, converted as
    :py:func:`~roboto.time.to_epoch_nanoseconds` converts it; convert with that function first to satisfy a type
    checker."""

    @pydantic.field_validator("unix_epoch_offset_ns")
    @classmethod
    def _offset_positive_and_within_int64(cls, value: int) -> int:
        if value == 0:
            raise ValueError(
                "unix_epoch_offset_ns must be positive; to return the session's data on this topic to "
                "an offset of 0, clear its anchor instead with Topic.clear_unix_offset() "
                "(DELETE /v2/topics/id/<topic_id>/unix-offset?session_id=<session_id>)"
            )
        if not 0 < value <= INT64_MAX:
            raise ValueError("unix_epoch_offset_ns must be a time after the Unix epoch and below 2**63 ns")
        return value
