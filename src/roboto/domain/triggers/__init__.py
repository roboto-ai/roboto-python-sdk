# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Triggers: fire on platform events or a schedule, filter with a condition, dispatch targets.

A trigger pairs a firing source — a subscription to one or more platform events (fired
at most once per the subscription's ``once_per``) or a cron schedule — with an optional
condition over the firing's variable namespace and one or more targets to run on a match.

The event catalog describes what each event type exposes — payload model, namespace
roots, supported ``once_per`` values — and drives both save-time validation and evaluation.
Conditions reuse the :class:`~roboto.query.Condition` wire format; target templates
reuse the :mod:`roboto.templating` ``{{...}}`` placeholder syntax.

:class:`roboto.domain.actions.Trigger` is the legacy model of the same thing (one action,
``causes``/``for_each``), deprecated and kept only for existing code; it cannot read a
trigger the current model added capabilities to. :class:`Trigger` here reads them all.
"""

from .conditions import (
    ConditionMatcher,
)
from .dispatch import (
    DispatchSlot,
    TriggerDispatchRecord,
    TriggerDispatchStatus,
)
from .dry_run import (
    ConditionLeafTrace,
    DispatchSlotTrace,
    TargetAcceptanceTrace,
    TriggerDryRunGate,
    TriggerDryRunGateName,
    TriggerDryRunGateStatus,
    TriggerDryRunRequest,
    TriggerDryRunResponse,
)
from .namespace import (
    EventNamespace,
    NamespaceSource,
)
from .operations import (
    MAX_TRIGGER_NAME_LENGTH,
    TRIGGER_NAME_PATTERN,
    CreateTriggerRequest,
    UpdateTriggerRequest,
)
from .record import TriggerRecord
from .samples import (
    PlatformEventSample,
    PlatformEventSamplesResponse,
    SampleNamespaceSource,
    platform_event_sample,
    platform_event_samples,
    sample_schedule_trigger,
    sample_trigger,
    template_paths,
)
from .sources import (
    EventSubscription,
    Schedule,
    TriggerSource,
    TriggerSourceType,
)
from .targets import (
    InvokeActionTarget,
    SendSlackMessageTarget,
    StartAgentTarget,
    TriggerTargetSpec,
    TriggerTargetType,
    target_catalog_manifest,
)
from .trigger import Trigger
from .validation import TriggerValidator

__all__ = [
    "MAX_TRIGGER_NAME_LENGTH",
    "TRIGGER_NAME_PATTERN",
    "ConditionLeafTrace",
    "ConditionMatcher",
    "CreateTriggerRequest",
    "DispatchSlotTrace",
    "EventNamespace",
    "EventSubscription",
    "PlatformEventSamplesResponse",
    "InvokeActionTarget",
    "NamespaceSource",
    "PlatformEventSample",
    "SampleNamespaceSource",
    "Schedule",
    "SendSlackMessageTarget",
    "StartAgentTarget",
    "TargetAcceptanceTrace",
    "Trigger",
    "DispatchSlot",
    "TriggerDispatchRecord",
    "TriggerDispatchStatus",
    "TriggerDryRunGate",
    "TriggerDryRunGateName",
    "TriggerDryRunGateStatus",
    "TriggerDryRunRequest",
    "TriggerDryRunResponse",
    "TriggerRecord",
    "TriggerSource",
    "TriggerSourceType",
    "TriggerTargetSpec",
    "target_catalog_manifest",
    "TriggerTargetType",
    "TriggerValidator",
    "UpdateTriggerRequest",
    "platform_event_sample",
    "platform_event_samples",
    "sample_schedule_trigger",
    "sample_trigger",
    "template_paths",
]
