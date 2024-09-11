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
    enabled: bool = True
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


class EvaluateTriggersRequest(pydantic.BaseModel):
    trigger_evaluation_ids: collections.abc.Iterable[int]


class QueryTriggersRequest(pydantic.BaseModel):
    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class TriggerEvaluationsSummaryResponse(pydantic.BaseModel):
    count_pending: int
    last_evaluation_start: typing.Optional[datetime.datetime]


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
