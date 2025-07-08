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

from . import (
    ComputeRequirements,
    ContainerParameters,
)
from ...pydantic import (
    validate_nonzero_gitpath_specs,
)
from ...query import ConditionType
from .trigger_record import (
    TriggerEvaluationCause,
    TriggerForEachPrimitive,
)


class CreateTriggerRequest(pydantic.BaseModel):
    """Request payload to create a new trigger.

    Contains all the configuration needed to create a trigger that automatically
    invokes actions when specific conditions are met.
    """

    action_digest: typing.Optional[str] = None
    """Optional specific version digest of the action to invoke. If not provided, uses the latest version."""

    action_name: str
    """Name of the action to invoke when the trigger fires."""

    action_owner_id: typing.Optional[str] = None
    """Organization ID that owns the target action. If not provided, searches in the caller's organization."""

    additional_inputs: typing.Optional[list[str]] = None
    """Optional additional file patterns to include in action invocations beyond the required inputs."""

    causes: typing.Optional[list[TriggerEvaluationCause]] = None
    """List of events that can cause this trigger to be evaluated. If not provided, uses default causes."""
    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Optional compute requirement overrides for action invocations."""

    condition: typing.Optional[ConditionType] = None
    """Optional condition that must be met for the trigger to fire.

    Can filter based on metadata, file properties, etc.
    """

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Optional container parameter overrides for action invocations."""

    enabled: bool = True
    """Whether the trigger should be active immediately after creation."""

    for_each: TriggerForEachPrimitive
    """Granularity of execution - Dataset or DatasetFile."""

    name: str = pydantic.Field(pattern=r"[\w\-]+", max_length=256)
    """Unique name for the trigger (alphanumeric, hyphens, underscores only, max 256 characters)."""
    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    """Parameter values to pass to the action when invoked."""

    required_inputs: list[str]
    """List of file patterns that must be present for the trigger to fire. Uses glob patterns like '**/*.bag'."""

    service_user_id: typing.Optional[str] = None
    """Optional service user ID for authentication."""

    timeout: typing.Optional[int] = None
    """Optional timeout override for action invocations in minutes."""

    @pydantic.field_validator("required_inputs")
    def validate_required_inputs(cls, value: list[str]) -> list[str]:
        return validate_nonzero_gitpath_specs(value)

    @pydantic.field_validator("additional_inputs")
    def validate_additional_inputs(
        cls, value: typing.Optional[list[str]]
    ) -> typing.Optional[list[str]]:
        return None if value is None else validate_nonzero_gitpath_specs(value)


class EvaluateTriggersRequest(pydantic.BaseModel):
    """Request payload to manually evaluate specific triggers.

    Used to force evaluation of triggers outside of their normal
    automatic evaluation cycle. This is typically used for testing
    or debugging trigger behavior.

    Note:
        This is primarily used internally by the Roboto platform and
        is not commonly needed by SDK users.
    """

    trigger_evaluation_ids: collections.abc.Iterable[int]
    """Collection of trigger evaluation IDs to process."""


class QueryTriggersRequest(pydantic.BaseModel):
    """Request payload to query triggers with filters.

    Used to search for triggers based on various criteria such as
    name, status, or other attributes.
    """

    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Dictionary of filter criteria to apply to the trigger search."""
    model_config = ConfigDict(extra="ignore")


class TriggerEvaluationsSummaryResponse(pydantic.BaseModel):
    """Response containing summary information about trigger evaluations.

    Provides high-level statistics about trigger evaluation status,
    useful for monitoring and debugging trigger performance.
    """

    count_pending: int
    """Number of trigger evaluations currently pending."""

    last_evaluation_start: typing.Optional[datetime.datetime]
    """Timestamp of the most recent evaluation start, if any evaluations have occurred."""


class UpdateTriggerRequest(pydantic.BaseModel):
    """Request payload to update an existing trigger.

    Contains the changes to apply to a trigger. Only specified fields
    will be updated; others remain unchanged. Uses NotSet sentinel values
    to distinguish between explicit None values and unspecified fields.
    """

    action_name: typing.Union[str, NotSetType] = NotSet
    """New action name to invoke."""

    action_owner_id: typing.Union[str, NotSetType] = NotSet
    """New organization ID that owns the target action."""

    action_digest: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    """New specific version digest of the action."""

    additional_inputs: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    """New additional file patterns to include."""

    causes: typing.Union[list[TriggerEvaluationCause], NotSetType] = NotSet
    """New list of events that can cause trigger evaluation."""
    compute_requirement_overrides: typing.Optional[
        typing.Union[ComputeRequirements, NotSetType]
    ] = NotSet
    """New compute requirement overrides."""

    container_parameter_overrides: typing.Optional[
        typing.Union[ContainerParameters, NotSetType]
    ] = NotSet
    """New container parameter overrides."""

    condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet
    """New condition that must be met for trigger to fire."""

    enabled: typing.Union[bool, NotSetType] = NotSet
    """New enabled status for the trigger."""

    for_each: typing.Union[TriggerForEachPrimitive, NotSetType] = NotSet
    """New execution granularity (Dataset or DatasetFile)."""

    parameter_values: typing.Optional[
        typing.Union[dict[str, typing.Any], NotSetType]
    ] = NotSet
    """New parameter values to pass to the action."""

    required_inputs: typing.Union[list[str], NotSetType] = NotSet
    """New list of required file patterns."""

    timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet
    """New timeout override for action invocations."""

    model_config = ConfigDict(
        extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier
    )
