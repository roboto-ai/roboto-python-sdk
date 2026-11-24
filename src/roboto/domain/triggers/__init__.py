# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Triggers: rules that run targets, such as invoking an action, on matching platform events or on a schedule.

Use :py:class:`~roboto.domain.triggers.Trigger`, which replaces the deprecated
:py:class:`~roboto.domain.actions.Trigger`, to create, find, update, and dry-run triggers, including those the
deprecated class cannot express.
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
    session_event_root,
)
from .operations import (
    MAX_TRIGGER_NAME_LENGTH,
    TRIGGER_NAME_PATTERN,
    CreateTriggerRequest,
    UpdateTriggerRequest,
)
from .query_templates import (
    iter_query_templates,
    map_query_templates,
    substitute_query_template,
)
from .record import (
    ManagedBy,
    ManagedByKind,
    TriggerRecord,
)
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
    ActionInvocationSpec,
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
    "ActionInvocationSpec",
    "MAX_TRIGGER_NAME_LENGTH",
    "TRIGGER_NAME_PATTERN",
    "ConditionLeafTrace",
    "ConditionMatcher",
    "CreateTriggerRequest",
    "DispatchSlotTrace",
    "EventNamespace",
    "iter_query_templates",
    "map_query_templates",
    "substitute_query_template",
    "EventSubscription",
    "PlatformEventSamplesResponse",
    "InvokeActionTarget",
    "ManagedBy",
    "ManagedByKind",
    "NamespaceSource",
    "session_event_root",
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
