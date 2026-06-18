# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import pydantic

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
    """The body of a read-plan request: the logical read question to resolve into a physical plan."""

    model_config = pydantic.ConfigDict(frozen=True)

    start_time: int
    """Inclusive window lower bound, absolute Unix-epoch nanoseconds."""

    end_time: int
    """Inclusive window upper bound, absolute Unix-epoch nanoseconds."""

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

    @pydantic.model_validator(mode="after")
    def _window_ordered(self) -> ReadPlanRequest:
        if self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
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
