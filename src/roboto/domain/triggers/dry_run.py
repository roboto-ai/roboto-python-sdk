# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
    """Gate a trigger dry-run result is for: a check a trigger must pass to run its targets for a platform event.

    The members are listed in the order Roboto checks the gates.
    """

    Subscribed = "subscribed"
    """Whether the trigger fires for the event's type.

    The type must be one of the trigger's subscribed platform events, or
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.ScheduleFired` for a schedule-fired trigger.
    """

    Enabled = "enabled"
    """Whether the trigger is enabled."""

    Condition = "condition"
    """Whether the trigger's condition holds for the event. Passes when the trigger has no condition."""

    TargetPrefilter = "target_prefilter"
    """Whether at least one of the trigger's targets accepts the event.

    For example, an action target accepts the event when its required-input patterns match a file.
    """

    AlreadyFired = "already_fired"
    """Whether at least one target that accepts the event has not yet run for it at the trigger's ``once_per``.
    Fails when every accepting target already has."""


class TriggerDryRunGateStatus(StrEnum):
    """Outcome of one gate in a trigger dry run."""

    Passed = "passed"
    """The trigger meets this gate."""

    Failed = "failed"
    """The trigger does not meet this gate, so Roboto checks no later gate."""

    NotEvaluated = "not_evaluated"
    """An earlier gate failed, so Roboto did not check this one."""


class ConditionLeafTrace(pydantic.BaseModel):
    """One comparison in a trigger's condition, with the value the dry run's event supplied for its field.

    Carried in ``TriggerDryRunGate.condition_leaves``.
    """

    field: str
    """Field the comparison reads, as written in the trigger's condition."""

    comparator: Comparator
    """Comparator the comparison applies."""

    expected: typing.Optional[typing.Any] = None
    """Value the comparison tests the field against."""

    actual: typing.Optional[typing.Any] = None
    """Value the event supplied for ``field``, or ``None`` if the field did not resolve.

    A field does not resolve when the record it names is missing, the key is absent, or the field names a topic or
    message path, which no platform event supplies.
    """

    passed: bool
    """Whether this comparison, taken on its own, held for the event."""


class TargetAcceptanceTrace(pydantic.BaseModel):
    """One target's decision on whether to accept the dry run's event.

    Carried in ``TriggerDryRunGate.targets``.
    """

    target_id: str
    """ID of the target within the trigger."""

    target_type: TriggerTargetType
    """Kind of target: invoking an action, starting an agent, or sending a Slack message."""

    accepted: bool
    """Whether the target accepts the event. A target that raised an error while Roboto checked it does not."""

    reason: typing.Optional[str] = None
    """Why the target declined, such as which required-input pattern no file matched, or the error it raised.
    ``None`` when the target accepted, or when Roboto cannot say more than that it declined."""


class DispatchSlotTrace(pydantic.BaseModel):
    """Dispatch slot of one target that accepts the dry run's event, showing whether the target already ran for it.

    A dispatch is one attempt to run one target for one platform event, as recorded by
    :py:class:`~roboto.domain.triggers.TriggerDispatchRecord`. A trigger runs each target at most once for each value of
    its ``once_per``, such as once per file, so each target has one slot per idempotency token, which at most one
    dispatch holds.

    Carried in ``TriggerDryRunGate.dispatches``.
    """

    target_id: str
    """ID of the target within the trigger."""

    occupied: bool
    """Whether a dispatch that has not failed holds the slot, so the trigger would skip the target for this event.

    A failed dispatch leaves the slot free for the trigger to try again.
    """

    status: typing.Optional[TriggerDispatchStatus] = None
    """Status of the dispatch in the slot, or ``None`` if the slot is empty."""

    result_ref: typing.Optional[str] = None
    """What the dispatch in the slot produced: an invocation ID, an agent thread ID, or a Slack message timestamp.
    ``None`` if the slot is empty or the dispatch produced nothing."""


class TriggerDryRunGate(pydantic.BaseModel):
    """Result of one gate in a trigger dry run.

    Each list and token field belongs to one gate of ``TriggerDryRunGateName``: ``condition_leaves`` to ``Condition``,
    ``targets`` to ``TargetPrefilter``, and ``idempotency_token`` and ``dispatches`` to ``AlreadyFired``. They are
    ``None`` on every other gate, and on a gate Roboto did not evaluate.

    Carried in ``TriggerDryRunResponse.gates``.
    """

    gate: TriggerDryRunGateName
    """Gate this result is for."""

    status: TriggerDryRunGateStatus
    """Whether the gate passed, failed, or was not evaluated because an earlier gate failed."""

    detail: typing.Optional[str] = None
    """Plain-English explanation of the outcome, such as which condition field did not match."""

    condition_leaves: typing.Optional[list[ConditionLeafTrace]] = None
    """Result of each comparison in the trigger's condition. Empty when the trigger has no condition."""

    targets: typing.Optional[list[TargetAcceptanceTrace]] = None
    """Each target's decision on whether to accept the event."""

    idempotency_token: typing.Optional[str] = None
    """Token that names the event's file, dataset, or occurrence at the trigger's ``once_per``.

    Events with the same token share one run of each target.
    """

    dispatches: typing.Optional[list[DispatchSlotTrace]] = None
    """Slot of each target that accepts the event, at ``idempotency_token``."""


class TriggerDryRunRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.triggers.Trigger.dry_run`.

    Set ``event`` to evaluate a complete platform event, or at most one reference for Roboto to synthesize a platform
    event from: ``dataset_id``, ``file_id``, ``invocation_id`` or ``event_id`` for a trigger that fires on platform
    events, or ``scheduled_for`` for a schedule-fired trigger. A schedule-fired trigger needs no reference; Roboto then
    synthesizes its next scheduled occurrence. Building a request that sets ``event`` together with a reference or
    ``event_type``, or sets more than one reference, raises ``pydantic.ValidationError``.
    """

    event: typing.Optional[PlatformEvent] = None
    """Platform event to evaluate as given.

    It must belong to the trigger's organization, as must every resource it names.
    """

    dataset_id: typing.Optional[str] = None
    """ID of a dataset to synthesize a platform event about."""

    file_id: typing.Optional[str] = None
    """ID of a file to synthesize a platform event about."""

    invocation_id: typing.Optional[str] = None
    """ID of an invocation to synthesize a platform event about."""

    event_id: typing.Optional[str] = None
    """ID of an event to synthesize a platform event about.

    Roboto synthesizes :py:attr:`~roboto.domain.platform_events.PlatformEventType.EventCreated` for an event on a
    dataset (``ev_``), or :py:attr:`~roboto.domain.platform_events.PlatformEventType.SessionEventCreated` for an event
    on a session (``evt_``).
    """

    scheduled_for: typing.Optional[datetime.datetime] = None
    """Time of the occurrence to synthesize for a schedule-fired trigger, with seconds and smaller units dropped.
    ``None`` synthesizes the schedule's next occurrence."""

    event_type: typing.Optional[PlatformEventType] = None
    """Type of platform event to synthesize from a reference; it must be one the reference can produce.
    ``None`` uses the first of the trigger's subscribed event types that the reference can produce."""

    @pydantic.model_validator(mode="after")
    def _exactly_one_subject(self) -> "TriggerDryRunRequest":
        refs = [
            value
            for value in (
                self.dataset_id,
                self.file_id,
                self.invocation_id,
                self.event_id,
                self.scheduled_for,
            )
            if value is not None
        ]
        if self.event is not None:
            if refs or self.event_type is not None:
                raise ValueError(
                    "Provide either a full 'event' or one reference "
                    "(dataset_id | file_id | invocation_id | event_id | scheduled_for, "
                    "with optional event_type), "
                    "not both."
                )
        elif len(refs) > 1:
            raise ValueError(
                "Provide at most one of 'event', 'dataset_id', 'file_id', 'invocation_id', 'event_id', "
                "or 'scheduled_for'."
            )
        return self


class TriggerDryRunResponse(pydantic.BaseModel):
    """Response body of :py:meth:`~roboto.domain.triggers.Trigger.dry_run`.

    A dry run reports whether a trigger would run its targets for a platform event, and if not, why. It checks the
    trigger's gates against the event and the organization's current data, in the order Roboto checks them when the
    trigger fires, and runs no target. The first failed gate is why the trigger would not fire; every gate after it is
    ``TriggerDryRunGateStatus.NotEvaluated``.
    """

    trigger_id: str
    """ID of the trigger that was dry-run."""

    event_type: PlatformEventType
    """Type of the platform event evaluated, whether the request gave it or Roboto synthesized it."""

    would_fire: bool
    """Whether the trigger would run at least one target for the event: true when every gate passed."""

    verdict: str
    """One plain-English sentence summarizing the outcome, quoting the first failed gate's ``detail`` if any failed."""

    gates: list[TriggerDryRunGate]
    """Result of every gate, in the order Roboto checks them."""


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
