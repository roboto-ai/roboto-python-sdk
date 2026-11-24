# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType

from ...pydantic import (
    validate_nonzero_gitpath_specs,
)
from ...query import ConditionType
from . import (
    ComputeRequirements,
    ContainerParameters,
)
from .trigger_record import (
    TriggerEvaluationCause,
    TriggerForEachPrimitive,
)


class CreateTriggerRequest(pydantic.BaseModel):
    """Deprecated. Request body for :py:meth:`~roboto.domain.actions.Trigger.create`, in the legacy trigger model.

    To create a trigger with the current model, use :py:meth:`~roboto.domain.triggers.Trigger.create`, which sends
    :py:class:`~roboto.domain.triggers.CreateTriggerRequest`.

    Building it raises ``pydantic.ValidationError`` when:

    - ``name`` is empty, is longer than 256 characters, or holds a character other than a letter, digit, underscore,
      or hyphen.
    - ``required_inputs`` is empty or holds only blank patterns.
    - ``additional_inputs`` is empty or holds only blank patterns.
    """

    action_digest: typing.Optional[str] = None
    """Digest of the action version to invoke. ``None`` invokes the latest version."""

    action_name: str
    """Name of the action to invoke, unique within the organization that owns it."""

    action_owner_id: typing.Optional[str] = None
    """ID of the organization that owns the action. ``None`` means the organization the trigger is created in."""

    additional_inputs: typing.Optional[list[str]] = None
    """File patterns for more files to pass to each invocation, beyond those ``required_inputs`` matches.

    ``None`` adds none. A list must contain at least one non-blank pattern.
    """

    causes: typing.Optional[list[TriggerEvaluationCause]] = None
    """Kinds of change that make Roboto evaluate the trigger. ``None`` evaluates it when files are uploaded."""
    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Compute requirements that override the action's for each invocation. ``None`` uses the action's own."""

    condition: typing.Optional[ConditionType] = None
    """Condition a dataset or file must satisfy for the trigger to invoke the action. ``None`` sets none.

    A condition can test, for example, the dataset's or file's metadata.
    """

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Container parameters that override the action's for each invocation. ``None`` uses the action's own."""

    enabled: bool = True
    """Whether the trigger is enabled as soon as it is created."""

    for_each: TriggerForEachPrimitive
    """Whether the trigger starts one invocation per dataset or one per matching file."""

    name: str = pydantic.Field(pattern=r"^[\w\-]+$", max_length=256)
    """Human-readable name of the trigger, unique within its organization.

    Letters, digits, underscores, and hyphens only, at most 256 characters.
    """
    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    """Values to pass to the action's parameters, keyed by parameter name. ``None`` passes none."""

    required_inputs: list[str]
    """File patterns, such as ``**/*.bag``, that select the files the trigger invokes the action on.

    With ``for_each`` set to :py:attr:`~roboto.domain.actions.TriggerForEachPrimitive.Dataset`, the dataset's files
    together must match every pattern; with :py:attr:`~roboto.domain.actions.TriggerForEachPrimitive.DatasetFile`,
    each file that matches any pattern gets its own invocation. The list must contain at least one non-blank pattern.
    """

    service_user_id: typing.Optional[str] = None
    """Deprecated. Roboto ignores it: a trigger's invocations run as its organization's service user."""

    timeout: typing.Optional[int] = None
    """Maximum run time of each invocation, in minutes, overriding the action's. ``None`` uses the action's own."""

    @pydantic.field_validator("required_inputs")
    def validate_required_inputs(cls, value: list[str]) -> list[str]:
        """Reject an empty list, or one whose patterns are all blank."""
        return validate_nonzero_gitpath_specs(value)

    @pydantic.field_validator("additional_inputs")
    def validate_additional_inputs(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        """Reject an empty list, or one whose patterns are all blank; ``None`` passes."""
        return None if value is None else validate_nonzero_gitpath_specs(value)


class EvaluateTriggersRequest(pydantic.BaseModel):
    """Request body holding the IDs of trigger evaluations to process.

    No SDK method or Roboto route uses this model.
    """

    trigger_evaluation_ids: collections.abc.Iterable[int]
    """IDs of the trigger evaluations to process."""


class QueryTriggersRequest(pydantic.BaseModel):
    """Request body holding filter criteria for triggers.

    No SDK method or Roboto route uses this model. To list an organization's triggers, use
    :py:meth:`~roboto.domain.triggers.Trigger.list`.
    """

    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Filter criteria for triggers."""
    model_config = ConfigDict(extra="ignore")


class TriggerEvaluationsSummaryResponse(pydantic.BaseModel):
    """Response body of ``GET /v1/triggers/dataset/id/{dataset_id}/evaluations/summary``.

    Summary of one dataset's trigger evaluations.
    """

    count_pending: int
    """Number of the dataset's trigger evaluations that are pending."""

    last_evaluation_start: typing.Optional[datetime.datetime]
    """Time the dataset's most recent trigger evaluation started, or ``None`` if none has."""


class UpdateTriggerRequest(pydantic.BaseModel):
    """Deprecated. Request body for :py:meth:`~roboto.domain.actions.Trigger.update`, in the legacy trigger model.

    Each field left unset (``NotSet``) leaves that setting of the trigger unchanged. To update a trigger with the
    current model, use :py:meth:`~roboto.domain.triggers.Trigger.update`, which sends
    :py:class:`~roboto.domain.triggers.UpdateTriggerRequest`.
    """

    action_name: typing.Union[str, NotSetType] = NotSet
    """Name of the action to invoke, unique within the organization that owns it."""

    action_owner_id: typing.Union[str, NotSetType] = NotSet
    """ID of the organization that owns the action."""

    action_digest: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """Digest of the action version to invoke. ``None`` invokes the latest version."""

    additional_inputs: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """File patterns for more files to pass to each invocation, beyond those ``required_inputs`` matches.

    ``None`` clears them.
    """

    causes: typing.Union[list[TriggerEvaluationCause], NotSetType] = NotSet
    """Kinds of change that make Roboto evaluate the trigger."""
    compute_requirement_overrides: typing.Optional[typing.Union[ComputeRequirements, NotSetType]] = NotSet
    """Compute requirements that override the action's for each invocation.

    ``None`` clears the override, so invocations use the action's own.
    """

    container_parameter_overrides: typing.Optional[typing.Union[ContainerParameters, NotSetType]] = NotSet
    """Container parameters that override the action's for each invocation.

    ``None`` clears the override, so invocations use the action's own.
    """

    condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet
    """Condition a dataset or file must satisfy for the trigger to invoke the action. ``None`` clears it."""

    enabled: typing.Union[bool, NotSetType] = NotSet
    """Whether the trigger is enabled."""

    for_each: typing.Union[TriggerForEachPrimitive, NotSetType] = NotSet
    """Whether the trigger starts one invocation per dataset or one per matching file."""

    parameter_values: typing.Optional[typing.Union[dict[str, typing.Any], NotSetType]] = NotSet
    """Values to pass to the action's parameters, keyed by parameter name. ``None`` clears them."""

    required_inputs: typing.Union[list[str], NotSetType] = NotSet
    """File patterns that select the files the trigger invokes the action on.

    Matched as described on ``CreateTriggerRequest.required_inputs``.
    """

    timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet
    """Maximum run time of each invocation, in minutes, overriding the action's.

    ``None`` clears the override, so invocations use the action's own.
    """

    model_config = ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)
