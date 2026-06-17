# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Typed, per-goal-type results bundling the achieve-tool invocation.

A :data:`GoalResult` is the typed read shape an SDK caller gets back from
:attr:`AgentThreadGoalView.result` once a goal has reached a terminal state
(``ACHIEVED`` or ``FAILED`` with at least one attempted invocation). It
bundles together:

- The goal's terminal :class:`AgentGoalStatus`.
- The exact :class:`AgentToolUseContent` the LLM submitted to satisfy the
  goal — useful when callers need to introspect the request or correlate
  with downstream effects.
- The corresponding :class:`AgentToolResultContent` (when the runner
  observed one), so callers can see the response the LLM saw.
- Per-goal-type typed fields parsed from ``achieve_tool_use.input`` via the
  shared :mod:`roboto.ai.goals.achieve_inputs` models, so callers get
  ``result.summary``, ``result.label_decisions``, ``result.events`` directly
  instead of reaching into a raw dict.

The discriminated-union pattern mirrors :data:`AgentGoal` exactly: each
concrete subclass declares ``goal_type: Literal[GoalType.X] = GoalType.X``
and the union dispatches on that discriminator.

Validation lives in the SDK, not on the wire — the server emits
``achieve_tool_use_id`` (a pointer into the persisted message stream) and
the SDK rebuilds the :data:`GoalResult` from messages it already holds.
A new goal type therefore needs no API change, only a new subclass here
plus a corresponding entry in :data:`AgentGoal`.
"""

from typing import Annotated, Literal, Optional, Union

import pydantic

# Pull the raw content blocks from the leaf ``core.content`` module rather
# than ``core.record``: ``core.record`` depends on this package (it imports
# ``AgentGoal`` for ``AgentThreadGoalRecord.to_agent_goal``), so importing
# from it here would reintroduce a cycle. ``core.content`` sits below both.
from ..core.content import (
    AgentToolResultContent,
    AgentToolUseContent,
)
from .achieve_inputs import (
    CreateEventsAchieveInput,
    DatasetSummaryAchieveInput,
    DatasetTriageAchieveInput,
)
from .types import AgentGoalStatus, GoalType


class GoalResultBase(pydantic.BaseModel):
    """Shared base for every concrete :data:`GoalResult`.

    Subclasses must declare a literal-typed ``goal_type`` field so the
    discriminated union can dispatch — and must also inherit from the
    matching achieve-input model from :mod:`roboto.ai.goals.achieve_inputs`
    so the parsed typed fields land alongside the raw blocks.
    """

    status: AgentGoalStatus
    """Terminal status of the goal: ``ACHIEVED`` or ``FAILED``."""

    achieve_tool_use: AgentToolUseContent
    """The ``AgentToolUseContent`` the LLM submitted. ``input`` carries the
    raw arguments; the parsed typed fields on the subclass are derived
    from it."""

    achieve_tool_result: Optional[AgentToolResultContent] = None
    """The ``AgentToolResultContent`` the runner observed for the matching
    ``tool_use_id``, if any. ``None`` when the runner persisted a tool_use
    but no corresponding tool_result reached the chunk log before the turn
    terminated."""


class DatasetSummaryGoalResult(GoalResultBase, DatasetSummaryAchieveInput):
    """Result of a :class:`GoalType.DATASET_SUMMARY` achieve-tool invocation.

    Exposes the LLM-submitted ``summary`` directly alongside the raw
    ``achieve_tool_use`` / ``achieve_tool_result`` blocks.
    """

    goal_type: Literal[GoalType.DATASET_SUMMARY] = GoalType.DATASET_SUMMARY
    """Discriminator. Always :attr:`GoalType.DATASET_SUMMARY`."""


class DatasetTriageGoalResult(GoalResultBase, DatasetTriageAchieveInput):
    """Result of a :class:`GoalType.DATASET_TRIAGE` achieve-tool invocation.

    Exposes the full per-label deliberation in ``label_decisions``; use
    :attr:`applied_labels` for the convenience subset that actually became
    tags on the dataset.
    """

    goal_type: Literal[GoalType.DATASET_TRIAGE] = GoalType.DATASET_TRIAGE
    """Discriminator. Always :attr:`GoalType.DATASET_TRIAGE`."""

    @property
    def applied_labels(self) -> list[str]:
        """Labels for which the LLM voted ``applies=True``.

        Matches the set of tags the achieve-tool persisted on the dataset.
        Returned in declaration order, not the (sorted) order in which the
        achieve-tool writes them to the dataset; for stable ordering use
        ``sorted(result.applied_labels)``.
        """
        return [d.label for d in self.label_decisions if d.applies]


class CreateEventsGoalResult(GoalResultBase, CreateEventsAchieveInput):
    """Result of a :class:`GoalType.CREATE_EVENTS` achieve-tool invocation.

    Exposes the list of ``EventSpec`` objects the LLM submitted. The SDK
    does not currently surface the resulting event ids directly from this
    result — callers wanting the created events should query the dataset's
    events using the time bounds in :attr:`events`. (Surfacing event ids
    here would require an API-layer round-trip back to the achieve-tool's
    response payload; YAGNI until a caller needs it.)
    """

    goal_type: Literal[GoalType.CREATE_EVENTS] = GoalType.CREATE_EVENTS
    """Discriminator. Always :attr:`GoalType.CREATE_EVENTS`."""


GoalResult = Annotated[
    Union[DatasetSummaryGoalResult, DatasetTriageGoalResult, CreateEventsGoalResult],
    pydantic.Field(discriminator="goal_type"),
]
"""Closed, Roboto-controlled discriminated union of every typed goal result.

Validated via pydantic discriminator on ``goal_type``. Mirrors the shape
of :data:`AgentGoal` so adding a new goal type means:

1. Add a new ``GoalType`` member.
2. Add a new ``AgentGoal`` subclass in :mod:`roboto.ai.goals.types`.
3. Add a matching achieve-input model in
   :mod:`roboto.ai.goals.achieve_inputs`.
4. Add a new ``GoalResult`` subclass here that inherits from both
   :class:`GoalResultBase` and the new achieve-input model.

No API or wire-schema change is needed because the SDK builds the result
from the persisted message stream via ``achieve_tool_use_id``.
"""
