# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import typing

import pydantic
from pydantic import ConfigDict, ValidationInfo

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
    TriggerForEachPrimitive,
)


class CreateTriggerRequest(pydantic.BaseModel):
    action_digest: typing.Optional[str] = None
    action_name: str
    action_owner_id: typing.Optional[str] = None
    additional_inputs: typing.Optional[list[str]] = None
    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    condition: typing.Optional[ConditionType] = None
    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    for_each: TriggerForEachPrimitive
    name: str = pydantic.Field(pattern=r"[\w\-]+", max_length=256)
    parameter_values: typing.Optional[dict[str, typing.Any]] = None
    required_inputs: list[str]
    service_user_id: typing.Optional[str] = None
    timeout: typing.Optional[int] = None

    @pydantic.field_validator("required_inputs")
    def validate_required_inputs(cls, value: list[str]) -> list[str]:
        return validate_nonzero_gitpath_specs(value)

    @pydantic.field_validator("additional_inputs")
    def validate_additional_inputs(
        cls, value: typing.Optional[list[str]]
    ) -> typing.Optional[list[str]]:
        return None if value is None else validate_nonzero_gitpath_specs(value)


class QueryTriggersRequest(pydantic.BaseModel):
    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class UpdateTriggerRequest(pydantic.BaseModel):
    action_name: typing.Union[str, NotSetType] = NotSet
    action_owner_id: typing.Union[str, NotSetType] = NotSet
    action_digest: typing.Optional[typing.Union[str, NotSetType]] = NotSet
    additional_inputs: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet
    compute_requirement_overrides: typing.Optional[
        typing.Union[ComputeRequirements, NotSetType]
    ] = NotSet
    container_parameter_overrides: typing.Optional[
        typing.Union[ContainerParameters, NotSetType]
    ] = NotSet
    condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet
    enabled: typing.Union[bool, NotSetType] = NotSet
    for_each: typing.Union[TriggerForEachPrimitive, NotSetType] = NotSet
    parameter_values: typing.Optional[
        typing.Union[dict[str, typing.Any], NotSetType]
    ] = NotSet
    required_inputs: typing.Union[list[str], NotSetType] = NotSet
    timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=NotSetType.openapi_schema_modifier
    )


class EvaluateTriggerPrincipalType(str, enum.Enum):
    Dataset = "dataset"
    File = "file"


class EvaluateTriggerScope(str, enum.Enum):
    Dataset = "dataset"
    DatasetFiles = "dataset_files"
    File = "file"


class EvaluateTriggersRequest(pydantic.BaseModel):
    principal_id: str
    principal_type: EvaluateTriggerPrincipalType
    evaluation_scope: EvaluateTriggerScope

    @staticmethod
    def is_valid_combination(
        principal_type: EvaluateTriggerPrincipalType,
        evaluation_scope: EvaluateTriggerScope,
    ) -> bool:
        return (principal_type, evaluation_scope) in [
            (EvaluateTriggerPrincipalType.File, EvaluateTriggerScope.File),
            (EvaluateTriggerPrincipalType.Dataset, EvaluateTriggerScope.Dataset),
            (EvaluateTriggerPrincipalType.Dataset, EvaluateTriggerScope.DatasetFiles),
        ]

    @pydantic.field_validator("evaluation_scope")
    def validate_evaluation_scope(
        cls, evaluation_scope: EvaluateTriggerScope, info: ValidationInfo
    ) -> EvaluateTriggerScope:
        principal_type = typing.cast(
            EvaluateTriggerPrincipalType, info.data.get("principal_type")
        )
        if not cls.is_valid_combination(principal_type, evaluation_scope):
            raise ValueError(
                f"'{principal_type}', '{evaluation_scope}' is not a valid tuple of "
                + "principal_type, evaluation_scope"
            )

        return evaluation_scope
