# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

from ...pydantic import (
    validate_nonzero_gitpath_specs,
)
from ...query import ConditionType
from .action_record import (
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_record import (
    InvocationDataSource,
)


class TriggerForEachPrimitive(str, enum.Enum):
    """Defines the granularity at which a trigger executes.

    Determines whether the trigger creates one invocation per dataset or
    one invocation per file within datasets that match the trigger conditions.
    """

    Dataset = "dataset"
    """Execute one action invocation per dataset that matches the trigger conditions."""

    DatasetFile = "dataset_file"
    """Execute one action invocation per file in datasets that match the trigger conditions."""


class TriggerEvaluationCause(enum.Enum):
    """The cause of a TriggerEvaluationRecord is the reason why the trigger was selected for evaluation.

    Represents the specific event that caused a trigger to be evaluated for
    potential execution. Different causes may result in different trigger
    behavior or input data selection.
    """

    DatasetMetadataUpdate = "dataset_metadata_update"
    """Trigger evaluation caused by changes to dataset metadata."""

    FileUpload = "file_upload"
    """Trigger evaluation caused by new files being uploaded to a dataset."""

    FileIngest = "file_ingest"
    """Trigger evaluation caused by files being ingested into a dataset."""


class TriggerRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a trigger.

    Contains all the configuration and metadata for a trigger, including
    the target action, input requirements, conditions, and execution settings.

    This is the underlying data structure used by the Trigger domain class
    to store and transmit trigger information.
    """

    trigger_id: str
    """Unique identifier for the trigger."""

    name: str
    """Human-readable name for the trigger."""

    org_id: str
    """Organization ID that owns the trigger."""

    created: datetime.datetime
    """Timestamp when the trigger was created."""

    created_by: str
    """User ID who created the trigger."""

    modified: datetime.datetime
    """Timestamp when the trigger was last modified."""

    modified_by: str
    """User ID who last modified the trigger."""

    action: ActionReference
    """Reference to the action that should be invoked."""

    required_inputs: list[str]
    """File patterns that must be present for trigger to fire."""

    service_user_id: str
    """Service user ID for authentication."""
    for_each: TriggerForEachPrimitive = TriggerForEachPrimitive.Dataset
    """Granularity of trigger execution (Dataset or DatasetFile)."""

    enabled: bool = True
    """Whether the trigger is currently active."""

    parameter_values: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Parameter values to pass to the action."""

    additional_inputs: typing.Optional[list[str]] = None
    """Optional additional file patterns to include."""

    causes: typing.Optional[list[TriggerEvaluationCause]] = None
    """List of events that can cause this trigger to be evaluated."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Optional compute requirement overrides."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Optional container parameter overrides."""

    condition: typing.Optional[ConditionType] = None
    """Optional condition that must be met for trigger to fire."""

    timeout: typing.Optional[int] = None
    """Optional timeout override for action execution."""

    @pydantic.field_validator("required_inputs")
    def validate_required_inputs(cls, value: list[str]) -> list[str]:
        return validate_nonzero_gitpath_specs(value)

    @pydantic.field_validator("additional_inputs")
    def validate_additional_inputs(
        cls, value: typing.Optional[list[str]]
    ) -> typing.Optional[list[str]]:
        if value is None or len(value) == 0:
            return []

        return validate_nonzero_gitpath_specs(value)


class TriggerEvaluationStatus(enum.Enum):
    """
    When a trigger is selected for evaluation,
    a trigger evaluation record is created with a status of Pending.
    The evaluation can either run to completion (regardless of its outcome),
    in which case the status is Evaluated, or hit an unexpected exception,
    in which case the status is Failed.
    """

    Pending = "pending"
    Evaluated = "evaluated"
    Failed = "failed"


class TriggerEvaluationOutcome(enum.Enum):
    """
    The outcome of a TriggerEvaluationRecord is the result of the evaluation.
    A trigger can either invoke its associated action (one or many times) or be skipped.
    If skipped, a skip reason is provided.
    """

    InvokedAction = "invoked_action"
    Skipped = "skipped"


class TriggerEvaluationOutcomeReason(enum.Enum):
    """Context for why a trigger evaluation has its TriggerEvaluationOutcome"""

    AlreadyRun = "already_run"
    """
    This trigger has already run its associated action for this dataset and/or file.
    """

    ConditionNotMet = "condition_not_met"
    """
    The trigger's condition is not met.
    """

    NoMatchingFiles = "no_matching_files"
    """
    In the case of a dataset trigger,
    there is no subset of files that, combined, match ALL of the trigger's required inputs.

    In the case of a file trigger,
    there are no files that match ANY of the trigger's required inputs.
    """

    TriggerDisabled = "trigger_disabled"
    """
    The trigger is disabled.
    """


class TriggerEvaluationDataConstraint(pydantic.BaseModel):
    """
    An optional filtering constraint applied to the data considered by a trigger evaluation.

    Each trigger evaluation considers data of a particular data source ID and data source type.
    Typically (and to start, exclusively), this is a dataset ID (and type Dataset).

    In the naive case before the introduction of this class, trigger evaluation for a dataset with 20k files would
    have to scan each file. This constraint allows us to filter the data to a subset during evaluation, e.g. only
    evaluate files from dataset ds_12345 with upload ID tx_123abc
    """

    transaction_id: str | None = None
    """If set, only consider files from this upload."""


class TriggerEvaluationRecord(pydantic.BaseModel):
    """
    Record of a point-in-time evaluation of whether to invoke an action associated with a trigger for a data source.
    """

    trigger_evaluation_id: int  # Auto-generated by the database
    trigger_id: str
    data_source: InvocationDataSource
    data_constraint: typing.Optional[TriggerEvaluationDataConstraint] = None
    evaluation_start: datetime.datetime
    evaluation_end: typing.Optional[datetime.datetime] = None
    status: TriggerEvaluationStatus
    status_detail: typing.Optional[str] = (
        None  # E.g., exception that caused the evaluation to fail
    )
    outcome: typing.Optional[TriggerEvaluationOutcome] = None
    outcome_reason: typing.Optional[TriggerEvaluationOutcomeReason] = None
    cause: typing.Optional[TriggerEvaluationCause] = None
