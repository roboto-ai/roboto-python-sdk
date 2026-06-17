# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic models for the inputs an achieve-tool receives from the LLM.

Each model captures the exact JSON shape the LLM submits when invoking the
achieve-tool for a goal of the corresponding :class:`GoalType`. The models
are shared between the server-side handlers (which validate the LLM's
``tool_use`` ``input`` against them) and the SDK-side
:mod:`roboto.ai.goals.results` ``GoalResult`` discriminated union (which
re-hydrates the same shape from the persisted message stream).

Vocabulary-aware constraints (e.g. "label must be one of the goal's declared
labels", "event name must be in the goal's event vocabulary") are not
expressible at the static-model level because they depend on the goal
instance; the server-side handler enforces them as a second pass after this
structural validation. The SDK does not enforce them at all — historical
``tool_use`` inputs have already passed both Bedrock's schema check and the
handler's vocab check at the time they were persisted.
"""

from typing import Optional

import pydantic


def _strip_check(value: str, *, field_name: str) -> str:
    """Reject whitespace-only strings.

    pydantic's ``min_length=1`` accepts ``"  "`` because it counts
    characters, not non-whitespace ones. The achieve-tool contract has
    always rejected whitespace-only inputs as equivalent to empty — keep
    that invariant here.
    """
    if not value.strip():
        raise ValueError(f"{field_name} must contain non-whitespace characters.")
    return value


class DatasetSummaryAchieveInput(pydantic.BaseModel):
    """Input the LLM submits to achieve a :class:`GoalType.DATASET_SUMMARY` goal."""

    summary: str = pydantic.Field(min_length=1)
    """The full natural-language summary to persist for the dataset.

    Must contain non-whitespace characters; the achieve-tool rejects pure
    whitespace as equivalent to empty.
    """

    @pydantic.field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        return _strip_check(value, field_name="summary")


class LabelDecision(pydantic.BaseModel):
    """One per-label deliberation entry inside a :class:`DatasetTriageAchieveInput`.

    Every label in the goal's ``label_vocabulary`` must appear exactly once
    across the parent ``label_decisions`` list — that constraint is enforced
    by the server-side handler after structural validation, since the
    vocabulary is goal-instance-specific.
    """

    label: str
    """The vocabulary label this decision concerns. Must match one of the
    goal's ``label_vocabulary`` keys (enforced by the handler against the
    declaring goal)."""

    applies: pydantic.StrictBool
    """Whether the label applies to the dataset. ``True`` decisions become
    tags on the dataset; ``False`` decisions are recorded in the tool-use
    log but not persisted on the dataset itself.

    Strictly typed to reject pydantic's default truthy-string coercion —
    the historical achieve-tool contract required a JSON boolean, not a
    boolean-coerced string or integer.
    """

    justification: str = pydantic.Field(min_length=1)
    """Brief reasoning for the decision, citing concrete observations from
    the dataset. Required even when ``applies`` is ``False`` so the
    deliberation is captured."""

    confidence: float = pydantic.Field(ge=0.0, le=1.0)
    """Subjective confidence in the decision, from 0.0 (no confidence) to
    1.0 (certain). Recorded but not used to gate persistence."""

    @pydantic.field_validator("justification")
    @classmethod
    def _justification_not_blank(cls, value: str) -> str:
        return _strip_check(value, field_name="justification")


class DatasetTriageAchieveInput(pydantic.BaseModel):
    """Input the LLM submits to achieve a :class:`GoalType.DATASET_TRIAGE` goal."""

    label_decisions: list[LabelDecision] = pydantic.Field(min_length=1)
    """One :class:`LabelDecision` per entry in the goal's ``label_vocabulary``.

    Vocabulary completeness — every label declared on the goal appears
    exactly once, with no duplicates — is enforced by the server-side
    handler. This model only validates the structural shape of each
    decision.
    """


class EventSpec(pydantic.BaseModel):
    """One event the LLM proposes inside a :class:`CreateEventsAchieveInput`.

    The ``name`` must come from the parent goal's ``event_vocabulary`` and
    every ``tags`` entry from the goal's ``tag_vocabulary``; both checks
    live in the server-side handler because they depend on the goal
    instance.
    """

    name: str
    """The kind of event. Must be one of the goal's declared event
    vocabulary names (enforced by the handler)."""

    start_time: pydantic.StrictInt
    """Event start, in nanoseconds since the Unix epoch.

    Strictly typed: pydantic would otherwise coerce stringified integers
    and (notably) booleans — ``True`` would silently parse as timestamp 1.
    The historical achieve-tool contract required a JSON integer."""

    end_time: pydantic.StrictInt
    """Event end, in nanoseconds since the Unix epoch. Must be greater
    than or equal to :attr:`start_time`.

    Strictly typed for the same reason as :attr:`start_time`."""

    description: Optional[str] = None
    """Optional longer explanation of what the event captures."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags attached to this event. Each must be one of the goal's
    declared tag vocabulary keys (enforced by the handler). Empty by
    default."""

    target_id: Optional[str] = None
    """Identifier of the Roboto entity this event is attached to. The
    server-side handler infers the entity type from the id prefix
    (``ds_`` / ``fl_`` / ``tp_`` / ``mp_``) and enforces that the target
    descends from the goal's dataset.

    Optional rather than required so the SDK can re-hydrate
    ``CreateEventsGoalResult`` from persisted tool-use records written
    before per-event target scoping was added — those carry no
    ``target_id`` on each spec. Current-day records always carry a
    non-empty value; the handler rejects ``None`` on new invocations
    via a corrective tool-failure response."""

    @pydantic.model_validator(mode="after")
    def _end_after_start(self) -> "EventSpec":
        # ``mode="after"`` is deliberate: per-field ``StrictInt`` validation
        # must fire first so a non-int (or a bool) doesn't silently slip past
        # this check and produce a confusing comparison error. Do not switch
        # to ``mode="before"`` without also re-implementing the strict int
        # check inside this validator.
        if self.end_time < self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) is before start_time ({self.start_time}); "
                "use end_time == start_time for an instantaneous event."
            )
        return self


class CreateEventsAchieveInput(pydantic.BaseModel):
    """Input the LLM submits to achieve a :class:`GoalType.CREATE_EVENTS` goal."""

    events: list[EventSpec]
    """The events to create. May be empty if the agent found no intervals
    matching the declared event types."""
