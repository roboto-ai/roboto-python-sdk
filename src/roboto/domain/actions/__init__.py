# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Actions domain module for the Roboto SDK.

This module provides the core domain entities and operations for working with Actions,
Invocations, and Triggers in the Roboto platform. Actions are reusable functions that
process, transform, or analyze data. Invocations represent executions of actions, and
Triggers automatically invoke actions when specific events or conditions occur.

The main classes in this module are:

- :py:class:`~roboto.domain.actions.Action`: A reusable function to process data
- :py:class:`~roboto.domain.actions.Invocation`: An execution instance of an action
- :py:class:`~roboto.domain.actions.Trigger`: A rule that automatically invokes actions
- :py:class:`~roboto.domain.actions.ScheduledTrigger`: A trigger that invokes an action periodically

Examples:
    Basic action invocation:

    >>> from roboto.domain.actions import Action, InvocationSource
    >>> action = Action.from_name("my_action", owner_org_id="my-org")
    >>> invocation = action.invoke(
    ...     invocation_source=InvocationSource.Manual,
    ...     parameter_values={"param1": "value1"}
    ... )
    >>> invocation.wait_for_terminal_status()

    Creating a trigger:

    >>> from roboto.domain.actions import Trigger, TriggerForEachPrimitive
    >>> trigger = Trigger.create(
    ...     name="auto_process",
    ...     action_name="my_action",
    ...     required_inputs=["**/*.bag"],
    ...     for_each=TriggerForEachPrimitive.Dataset
    ... )
"""

from .action import Action
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
    "EvaluateTriggersRequest",
    "ExecutableProvenance",
    "ExecutorContainer",
    "FileSelector",
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
