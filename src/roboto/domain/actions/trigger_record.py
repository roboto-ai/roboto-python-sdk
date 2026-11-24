# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import typing

import pydantic

from ...compat import StrEnum
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


class TriggerForEachPrimitive(StrEnum):
    """How often a trigger invokes its action: once per dataset, or once per file."""

    Dataset = "dataset"
    """One invocation of the action for each dataset whose files match every one of the trigger's required inputs."""

    DatasetFile = "dataset_file"
    """One invocation of the action for each file that matches any of the trigger's required inputs."""


class TriggerEvaluationCause(enum.Enum):
    """Platform event that causes Roboto to evaluate a trigger, deciding whether to invoke its action."""

    DatasetMetadataUpdate = "dataset_metadata_update"
    """Change to a dataset's metadata."""

    FileUpload = "file_upload"
    """Upload of files to a dataset."""

    FileIngest = "file_ingest"
    """Ingestion of a file in a dataset."""

    FileMetadataUpdate = "file_metadata_update"
    """Change to a file's metadata or tags."""

    RecurringSchedule = "recurring_schedule"
    """Due time on a scheduled trigger's schedule.

    Roboto sets this cause on the evaluations of scheduled triggers, and rejects a trigger created or updated with it.
    To invoke an action on a recurring schedule, use :py:class:`~roboto.domain.actions.ScheduledTrigger`.
    """


class TriggerRecord(pydantic.BaseModel):
    """Deprecated. Data record of a trigger in the legacy trigger model, as the Roboto API returns it.

    :py:class:`~roboto.domain.triggers.Trigger` replaces this model, and reads and edits every trigger, including those
    this model cannot express. A trigger is a rule that invokes an action when files are uploaded or ingested, or when
    file or dataset metadata changes, and the data meets the trigger's condition.
    :py:class:`~roboto.domain.actions.Trigger`, also deprecated, wraps this record with methods that act on the trigger.

    Building one raises ``pydantic.ValidationError`` unless at least one ``required_inputs`` pattern is neither empty
    nor only whitespace, and when ``additional_inputs`` is a non-empty list whose every pattern is empty or only
    whitespace.
    """

    trigger_id: str
    """Unique ID of the trigger."""

    name: str
    """Human-readable name of the trigger, unique within its organization."""

    org_id: str
    """ID of the organization that owns the trigger."""

    created: datetime.datetime
    """Time the trigger was created."""

    created_by: str
    """ID of the user who created the trigger."""

    modified: datetime.datetime
    """Time the trigger was last modified."""

    modified_by: str
    """ID of the user who last modified the trigger."""

    action: ActionReference
    """Action the trigger invokes. A reference without a digest invokes the action's latest version."""

    required_inputs: list[str]
    """Gitignore-style patterns for the files the trigger requires, and passes to the action as its input data.

    With ``for_each`` set to ``TriggerForEachPrimitive.Dataset``, the trigger invokes its action when each pattern
    matches at least one file in the dataset. With ``TriggerForEachPrimitive.DatasetFile``, it invokes the action once
    for each file that matches any pattern. At least one pattern must be neither empty nor only whitespace.
    """

    service_user_id: str
    """ID of the service user the trigger invokes its action as."""

    for_each: TriggerForEachPrimitive = TriggerForEachPrimitive.Dataset
    """Whether the trigger invokes its action once per dataset or once per file."""

    enabled: bool = True
    """Whether the trigger is enabled. A disabled trigger never invokes its action."""

    parameter_values: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values for the action's parameters, keyed by parameter name, that each invocation receives."""

    additional_inputs: typing.Optional[list[str]] = None
    """Gitignore-style patterns for more files to pass to the action as input data.

    Unlike ``required_inputs``, no file has to match them for the trigger to invoke its action. ``None`` or an empty
    list adds no files.
    """

    causes: typing.Optional[list[TriggerEvaluationCause]] = None
    """Platform events that cause Roboto to evaluate the trigger.

    A trigger created without any is evaluated on file uploads.
    """

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Compute requirements that replace the action's own in each invocation, or ``None`` to use the action's."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Container parameters that replace the action's own in each invocation, or ``None`` to use the action's."""

    condition: typing.Optional[ConditionType] = None
    """Condition the data must meet for the trigger to invoke its action, or ``None`` if the trigger has none."""

    timeout: typing.Optional[int] = None
    """Maximum run time of each invocation, in minutes, or ``None`` to use the action's timeout."""

    @pydantic.field_validator("required_inputs")
    def validate_required_inputs(cls, value: list[str]) -> list[str]:
        """Reject ``required_inputs`` unless at least one pattern is neither empty nor only whitespace.

        Pydantic calls this while it builds the record.
        """
        return validate_nonzero_gitpath_specs(value)

    @pydantic.field_validator("additional_inputs")
    def validate_additional_inputs(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        """Replace ``None`` with an empty list, and reject a list whose every pattern is empty or only whitespace.

        Pydantic calls this while it builds the record.
        """
        if value is None or len(value) == 0:
            return []

        return validate_nonzero_gitpath_specs(value)


class TriggerEvaluationStatus(enum.Enum):
    """Progress of a trigger evaluation.

    An evaluation starts as ``Pending``. It becomes ``Evaluated`` when the trigger invokes its action, and ``Failed``
    when an error stops it. Roboto records an evaluation only when a trigger goes to invoke its action, so new
    evaluations are never ``Evaluated`` without invoking it. Older evaluations can also be ``Evaluated`` with the
    outcome ``TriggerEvaluationOutcome.Skipped``.
    """

    Pending = "pending"
    Evaluated = "evaluated"
    Failed = "failed"


class TriggerEvaluationOutcome(enum.Enum):
    """Result of a trigger evaluation: the trigger invoked its action, once or more, or skipped it.

    New evaluations are only ever ``InvokedAction``; ``Skipped`` appears only on older evaluations.
    """

    InvokedAction = "invoked_action"
    Skipped = "skipped"


class TriggerEvaluationOutcomeReason(enum.Enum):
    """Reason a trigger evaluation was skipped.

    Only older evaluations carry one, because new evaluations are never ``TriggerEvaluationOutcome.Skipped``.
    """

    AlreadyRun = "already_run"
    """The trigger already invoked its action for this dataset or file."""

    ConditionNotMet = "condition_not_met"
    """The data does not meet the trigger's condition."""

    NoMatchingFiles = "no_matching_files"
    """No files match the trigger's required inputs.

    For a trigger that runs once per dataset, no set of the dataset's files matches every required input. For a
    trigger that runs once per file, no file matches any required input.
    """

    TriggerDisabled = "trigger_disabled"
    """The trigger is disabled."""


class TriggerEvaluationDataConstraint(pydantic.BaseModel):
    """Limit on which of a data source's files a trigger evaluation considers.

    Carried in ``TriggerEvaluationRecord.data_constraint``.
    """

    transaction_id: typing.Optional[str] = None
    """ID of the upload whose files the evaluation considers, or ``None`` to consider files from any upload."""

    file_id: typing.Optional[str] = None
    """ID of the one file the evaluation considers, or ``None`` to consider every file."""


class TriggerEvaluationRecord(pydantic.BaseModel):
    """Deprecated. Data record of one evaluation of a trigger, as the Roboto API returns it.

    The record belongs to the legacy trigger model; :py:class:`~roboto.domain.triggers.Trigger` reads and edits every
    trigger. An evaluation decides, at one point in time, whether a trigger invokes its action for a data source.
    Returned by :py:meth:`~roboto.domain.actions.Trigger.get_evaluations`, and also by
    :py:meth:`~roboto.domain.actions.Trigger.latest_evaluation` and
    :py:meth:`~roboto.domain.actions.Trigger.get_evaluations_for_dataset`.
    """

    trigger_evaluation_id: int
    """Unique ID of the evaluation."""

    trigger_id: str
    """ID of the trigger evaluated."""

    data_source: InvocationDataSource
    """Data source the evaluation considered, usually a dataset."""

    data_constraint: typing.Optional[TriggerEvaluationDataConstraint] = None
    """Limit on which of the data source's files the evaluation considered, or ``None`` if it considered them all."""

    evaluation_start: datetime.datetime
    """Time the evaluation started."""

    evaluation_end: typing.Optional[datetime.datetime] = None
    """Time the evaluation finished, or ``None`` if it has not."""

    status: TriggerEvaluationStatus
    """Progress of the evaluation."""

    status_detail: typing.Optional[str] = None
    """Detail on the status, such as the error that made the evaluation fail, or ``None`` if there is none."""

    outcome: typing.Optional[TriggerEvaluationOutcome] = None
    """Result of the evaluation, or ``None`` while it is pending or when it failed."""

    outcome_reason: typing.Optional[TriggerEvaluationOutcomeReason] = None
    """Reason the evaluation was skipped, or ``None`` if it was not.

    New evaluations are never skipped, so only older evaluations have one.
    """

    cause: typing.Optional[TriggerEvaluationCause] = None
    """Platform event that caused the evaluation, or ``None`` when that platform event has no matching cause."""
