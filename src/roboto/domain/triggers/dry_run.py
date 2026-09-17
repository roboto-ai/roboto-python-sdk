# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Wire models for the trigger dry-run endpoint (``POST /v1/triggers/id/{id}/dry-run``).

A dry run answers "would this trigger fire for this event, and if not, why not" by
replaying the evaluator's gates in order — subscribed, enabled, condition, target
prefilter, already fired — against current platform state, without claiming a
dispatch slot or running any target. The response is the structured trace the web
UI's "Test this trigger" stepper and the CLI's ``dry-run`` command render.
"""

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...query import Comparator
from ..platform_events import (
    PlatformEvent,
    PlatformEventType,
)
from .dispatch import TriggerDispatchStatus
from .targets import TriggerTargetType


class TriggerDryRunGateName(StrEnum):
    """The gates the evaluator runs, in evaluation order."""

    Subscribed = "subscribed"
    """Is the trigger subscribed to the event's type?"""

    Enabled = "enabled"
    """Is the trigger enabled?"""

    Condition = "condition"
    """Does the trigger's condition hold for the event?"""

    TargetPrefilter = "target_prefilter"
    """Does at least one target accept the event (pathspec and precondition gates)?"""

    AlreadyFired = "already_fired"
    """Is a dispatch slot still claimable at the trigger's ``once_per``?"""


class TriggerDryRunGateStatus(StrEnum):
    """Outcome of one gate in a dry run."""

    Passed = "passed"

    Failed = "failed"

    NotEvaluated = "not_evaluated"
    """An earlier gate failed, so this one was short-circuited."""


class ConditionLeafTrace(pydantic.BaseModel):
    """One leaf of the trigger's condition, with the actual value it saw."""

    field: str
    """The condition field, as stored on the trigger."""

    comparator: Comparator
    """The leaf's comparator."""

    expected: typing.Optional[typing.Any] = None
    """The value the condition compares against."""

    actual: typing.Optional[typing.Any] = None
    """The value the event's namespace resolved for :attr:`field`; ``None`` when the
    field did not resolve (missing entity, missing key)."""

    passed: bool
    """Whether this leaf held for the event."""


class TargetAcceptanceTrace(pydantic.BaseModel):
    """One target's prefilter decision."""

    target_id: str
    """The target within the trigger."""

    target_type: TriggerTargetType
    """Kind of target."""

    accepted: bool
    """Whether the target's ``accepts`` prefilter passed."""

    reason: typing.Optional[str] = None
    """Why the target declined, where determinable (e.g. which required-input pattern
    had no matching file). ``None`` when accepted or when no finer reason is known."""


class DispatchSlotTrace(pydantic.BaseModel):
    """The state of one target's dispatch slot at the dry run's idempotency token."""

    target_id: str
    """The target within the trigger."""

    occupied: bool
    """Whether a dispatch row occupies the slot (the trigger already fired here)."""

    status: typing.Optional[TriggerDispatchStatus] = None
    """The occupying dispatch's status, when one exists."""

    result_ref: typing.Optional[str] = None
    """What the occupying dispatch produced (invocation id, thread id, Slack ts)."""


class TriggerDryRunGate(pydantic.BaseModel):
    """One gate's result in a dry-run trace.

    ``condition_leaves`` is populated only on the ``condition`` gate, ``targets`` only
    on ``target_prefilter``, and ``idempotency_token``/``dispatches`` only on
    ``already_fired``.
    """

    gate: TriggerDryRunGateName
    """Which gate this is."""

    status: TriggerDryRunGateStatus
    """Whether the gate passed, failed, or was short-circuited."""

    detail: typing.Optional[str] = None
    """Plain-English explanation of the outcome."""

    condition_leaves: typing.Optional[list[ConditionLeafTrace]] = None
    """Per-leaf results with actual values (``condition`` gate only)."""

    targets: typing.Optional[list[TargetAcceptanceTrace]] = None
    """Per-target prefilter decisions (``target_prefilter`` gate only)."""

    idempotency_token: typing.Optional[str] = None
    """The dedup token the event projects onto (``already_fired`` gate only)."""

    dispatches: typing.Optional[list[DispatchSlotTrace]] = None
    """Per-target dispatch-slot state at the token (``already_fired`` gate only)."""


class TriggerDryRunRequest(pydantic.BaseModel):
    """Request payload for a trigger dry run.

    Provide :attr:`event` (a fully-formed platform event to evaluate) or a single
    reference (:attr:`dataset_id`, :attr:`file_id`, :attr:`invocation_id`,
    :attr:`session_id`, :attr:`event_id`, or :attr:`scheduled_for`), from which the server synthesizes
    an event. With an entity reference, :attr:`event_type` optionally picks which of
    the trigger's subscribed event types to synthesize; the default is the trigger's
    first subscribed event type compatible with the reference. A schedule-fired
    trigger needs no reference: the server synthesizes its next scheduled minute.
    """

    event: typing.Optional[PlatformEvent] = None
    """A platform event to evaluate as-is."""

    dataset_id: typing.Optional[str] = None
    """Synthesize an event about this dataset."""

    file_id: typing.Optional[str] = None
    """Synthesize an event about this file."""

    invocation_id: typing.Optional[str] = None
    """Synthesize an event about this invocation."""

    session_id: typing.Optional[str] = None
    """Synthesize an event about this session."""

    event_id: typing.Optional[str] = None
    """Synthesize a platform event about this event (the annotation on your data)."""

    scheduled_for: typing.Optional[datetime.datetime] = None
    """For a schedule-fired trigger: synthesize the occurrence for this scheduled minute
    (UTC). With no reference at all, a schedule-fired trigger is dry-run for its next
    scheduled minute."""

    event_type: typing.Optional[PlatformEventType] = None
    """Which subscribed event type to synthesize for an entity reference."""

    @pydantic.model_validator(mode="after")
    def _exactly_one_subject(self) -> "TriggerDryRunRequest":
        refs = [
            value
            for value in (
                self.dataset_id,
                self.file_id,
                self.invocation_id,
                self.session_id,
                self.event_id,
                self.scheduled_for,
            )
            if value is not None
        ]
        if self.event is not None:
            if refs or self.event_type is not None:
                raise ValueError(
                    "Provide either a full 'event' or one reference "
                    "(dataset_id | file_id | invocation_id | session_id | event_id | scheduled_for, "
                    "with optional event_type), "
                    "not both."
                )
        elif len(refs) > 1:
            raise ValueError(
                "Provide at most one of 'event', 'dataset_id', 'file_id', 'invocation_id', 'session_id', "
                "'event_id', or 'scheduled_for'."
            )
        return self


class TriggerDryRunResponse(pydantic.BaseModel):
    """The structured trace a trigger dry run produces.

    Gates appear in evaluation order. The first failed gate is why the trigger would
    not fire; every gate after it is ``not_evaluated``.
    """

    trigger_id: str
    """The trigger that was dry-run."""

    event_type: PlatformEventType
    """Type of the (given or synthesized) event that was evaluated."""

    would_fire: bool
    """Whether the trigger would dispatch at least one target for this event."""

    verdict: str
    """One plain-English sentence summarizing the outcome."""

    gates: list[TriggerDryRunGate]
    """The gate-by-gate trace, in evaluation order."""


__all__ = [
    "ConditionLeafTrace",
    "DispatchSlotTrace",
    "TargetAcceptanceTrace",
    "TriggerDryRunGate",
    "TriggerDryRunGateName",
    "TriggerDryRunGateStatus",
    "TriggerDryRunRequest",
    "TriggerDryRunResponse",
]
