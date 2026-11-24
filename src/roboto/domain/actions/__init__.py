# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Actions: reusable functions to process, transform or analyze data in Roboto.

Use :py:class:`~roboto.domain.actions.Action` to create, find, and invoke actions,
:py:class:`~roboto.domain.actions.Invocation` to follow one run of an action, and
:py:class:`~roboto.domain.triggers.Trigger`, which replaces the deprecated :py:class:`~roboto.domain.actions.Trigger`
and :py:class:`~roboto.domain.actions.ScheduledTrigger`, to invoke actions on platform events or on a schedule.
"""

from .action import Action
from .action_config import ActionConfig
from .action_operations import (
    CreateActionRequest,
    SetActionAccessibilityRequest,
    UpdateActionRequest,
)
from .action_record import (
    Accessibility,
    ActionParameter,
    ActionParameterChangeset,
    ActionRecord,
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
    ExecutorContainer,
)
from .invocation import Invocation
from .invocation_operations import (
    CancelActiveInvocationsRequest,
    CancelActiveInvocationsResponse,
    CreateInvocationRequest,
    SetContainerInfoRequest,
    SetLogsLocationRequest,
    UpdateInvocationStatus,
)
from .invocation_record import (
    ActionProvenance,
    DataSelector,
    ExecutableProvenance,
    FileSelector,
    InvocationDataSource,
    InvocationDataSourceType,
    InvocationInput,
    InvocationProvenance,
    InvocationRecord,
    InvocationSource,
    InvocationStatus,
    InvocationStatusRecord,
    InvocationUploadDestination,
    LogRecord,
    LogsLocation,
    SourceProvenance,
    UploadDestinationType,
)
from .launch_requirements import (
    EgressPosture,
    InputKind,
    InputRequirement,
    LaunchRequirements,
    OutputChannel,
)
from .scheduled_trigger import (
    ScheduledTrigger,
    TriggerSchedule,
)
from .scheduled_trigger_operations import (
    CreateScheduledTriggerRequest,
    UpdateScheduledTriggerRequest,
)
from .scheduled_trigger_record import (
    ScheduledTriggerRecord,
)
from .stats import ActionStatsRecord
from .trigger import Trigger
from .trigger_operations import (
    CreateTriggerRequest,
    EvaluateTriggersRequest,
    QueryTriggersRequest,
    TriggerEvaluationsSummaryResponse,
    UpdateTriggerRequest,
)
from .trigger_record import (
    TriggerEvaluationCause,
    TriggerEvaluationDataConstraint,
    TriggerEvaluationOutcome,
    TriggerEvaluationOutcomeReason,
    TriggerEvaluationRecord,
    TriggerEvaluationStatus,
    TriggerForEachPrimitive,
    TriggerRecord,
)
from .trigger_view import (
    TriggerOnEvent,
    TriggerOnSchedule,
    TriggerType,
    TriggerView,
)

__all__ = (
    "Accessibility",
    "Action",
    "ActionConfig",
    "ActionParameter",
    "ActionParameterChangeset",
    "ActionProvenance",
    "ActionRecord",
    "ActionReference",
    "ActionStatsRecord",
    "CancelActiveInvocationsResponse",
    "CancelActiveInvocationsRequest",
    "ComputeRequirements",
    "ContainerParameters",
    "CreateActionRequest",
    "CreateInvocationRequest",
    "CreateScheduledTriggerRequest",
    "CreateTriggerRequest",
    "DataSelector",
    "EgressPosture",
    "EvaluateTriggersRequest",
    "ExecutableProvenance",
    "ExecutorContainer",
    "FileSelector",
    "InputKind",
    "InputRequirement",
    "LaunchRequirements",
    "OutputChannel",
    "Invocation",
    "InvocationDataSource",
    "InvocationDataSourceType",
    "InvocationInput",
    "InvocationProvenance",
    "InvocationRecord",
    "InvocationSource",
    "InvocationStatus",
    "InvocationStatusRecord",
    "InvocationUploadDestination",
    "LogsLocation",
    "LogRecord",
    "QueryTriggersRequest",
    "ScheduledTrigger",
    "ScheduledTriggerRecord",
    "SetActionAccessibilityRequest",
    "SetContainerInfoRequest",
    "SetLogsLocationRequest",
    "SourceProvenance",
    "Trigger",
    "TriggerEvaluationCause",
    "TriggerEvaluationDataConstraint",
    "TriggerEvaluationOutcome",
    "TriggerEvaluationOutcomeReason",
    "TriggerEvaluationRecord",
    "TriggerEvaluationStatus",
    "TriggerEvaluationsSummaryResponse",
    "TriggerForEachPrimitive",
    "TriggerOnEvent",
    "TriggerOnSchedule",
    "TriggerRecord",
    "TriggerSchedule",
    "TriggerType",
    "TriggerView",
    "UpdateActionRequest",
    "UpdateInvocationStatus",
    "UpdateScheduledTriggerRequest",
    "UpdateTriggerRequest",
    "UploadDestinationType",
)
