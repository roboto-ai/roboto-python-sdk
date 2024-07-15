# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...exceptions import RobotoConflictException
from ...http import RobotoClient
from ...query import (
    ConditionType,
    QuerySpecification,
)
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from .action import Action
from .invocation import Invocation
from .invocation_record import (
    ComputeRequirements,
    ContainerParameters,
    InvocationDataSource,
    InvocationSource,
)
from .trigger_operations import (
    CreateTriggerRequest,
    UpdateTriggerRequest,
)
from .trigger_record import (
    TriggerForEachPrimitive,
    TriggerRecord,
)


class Trigger:
    __record: TriggerRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        action_name: str,
        required_inputs: list[str],
        for_each: TriggerForEachPrimitive,
        action_digest: typing.Optional[str] = None,
        action_owner_id: typing.Optional[str] = None,
        additional_inputs: typing.Optional[list[str]] = None,
        compute_requirement_overrides: typing.Optional[ComputeRequirements] = None,
        condition: typing.Optional[ConditionType] = None,
        container_parameter_overrides: typing.Optional[ContainerParameters] = None,
        parameter_values: typing.Optional[dict[str, typing.Any]] = None,
        service_user_id: typing.Optional[str] = None,
        timeout: typing.Optional[int] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Trigger":
        """
        Invoke an action on every new dataset (or every new dataset file) that meets some acceptance criteria.
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateTriggerRequest(
            action_digest=action_digest,
            action_name=action_name,
            action_owner_id=action_owner_id,
            additional_inputs=additional_inputs,
            compute_requirement_overrides=compute_requirement_overrides,
            condition=condition,
            container_parameter_overrides=container_parameter_overrides,
            for_each=for_each,
            name=name,
            parameter_values=parameter_values,
            required_inputs=required_inputs,
            service_user_id=service_user_id,
            timeout=timeout,
        )

        response = roboto_client.post(
            "v1/triggers",
            data=request,
            caller_org_id=caller_org_id,
        )
        record = response.to_record(TriggerRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Trigger":
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get(
            f"v1/triggers/{name}",
            owner_org_id=owner_org_id,
        )
        record = response.to_record(TriggerRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Trigger", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        while True:
            response = roboto_client.post(
                "v1/triggers/query",
                data=spec,
                owner_org_id=owner_org_id,
                idempotent=True,
            )
            paginated_results = response.to_paginated_list(TriggerRecord)
            for record in paginated_results.items:
                yield cls(record, roboto_client)
            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: TriggerRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ):
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def condition(self) -> typing.Optional[ConditionType]:
        return self.__record.condition

    @property
    def created(self) -> datetime.datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def enabled(self) -> bool:
        return self.__record.enabled

    @property
    def for_each(self) -> TriggerForEachPrimitive:
        return self.__record.for_each

    @property
    def name(self):
        return self.__record.name

    @property
    def modified(self) -> datetime.datetime:
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        return self.__record.modified_by

    @property
    def org_id(self):
        return self.__record.org_id

    @property
    def record(self) -> TriggerRecord:
        return self.__record

    @property
    def service_user_id(self) -> typing.Optional[str]:
        return self.__record.service_user_id

    def delete(self):
        self.__roboto_client.delete(
            f"v1/triggers/{self.name}",
            owner_org_id=self.org_id,
        )

    def get_action(self) -> Action:
        return Action.from_name(
            self.__record.action.name,
            digest=self.__record.action.digest,
            owner_org_id=self.__record.action.owner,
            roboto_client=self.__roboto_client,
        )

    def invoke(
        self,
        data_source: InvocationDataSource,
        idempotency_id: typing.Optional[str] = None,
        input_data_override: typing.Optional[list[str]] = None,
    ) -> typing.Optional[Invocation]:
        try:
            return self.get_action().invoke(
                compute_requirement_overrides=self.__record.compute_requirement_overrides,
                container_parameter_overrides=self.__record.container_parameter_overrides,
                data_source_id=data_source.data_source_id,
                data_source_type=data_source.data_source_type,
                input_data=input_data_override or self.__record.required_inputs,
                idempotency_id=idempotency_id,
                invocation_source=InvocationSource.Trigger,
                invocation_source_id=self.__record.name,
                parameter_values=self.__record.parameter_values,
                timeout=self.__record.timeout,
                caller_org_id=self.__record.org_id,
            )
        except RobotoConflictException:
            # Return None if there was an existing invocation with the same idempotency ID
            return None

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        action_name: typing.Union[str, NotSetType] = NotSet,
        action_owner_id: typing.Union[str, NotSetType] = NotSet,
        action_digest: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        additional_inputs: typing.Optional[
            typing.Union[list[str], NotSetType]
        ] = NotSet,
        compute_requirement_overrides: typing.Optional[
            typing.Union[ComputeRequirements, NotSetType]
        ] = NotSet,
        container_parameter_overrides: typing.Optional[
            typing.Union[ContainerParameters, NotSetType]
        ] = NotSet,
        condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet,
        enabled: typing.Union[bool, NotSetType] = NotSet,
        for_each: typing.Union[TriggerForEachPrimitive, NotSetType] = NotSet,
        parameter_values: typing.Optional[
            typing.Union[dict[str, typing.Any], NotSetType]
        ] = NotSet,
        required_inputs: typing.Union[list[str], NotSetType] = NotSet,
        timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet,
    ) -> "Trigger":
        request = remove_not_set(
            UpdateTriggerRequest(
                action_name=action_name,
                action_owner_id=action_owner_id,
                action_digest=action_digest,
                additional_inputs=additional_inputs,
                compute_requirement_overrides=compute_requirement_overrides,
                container_parameter_overrides=container_parameter_overrides,
                condition=condition,
                enabled=enabled,
                for_each=for_each,
                parameter_values=parameter_values,
                required_inputs=required_inputs,
                timeout=timeout,
            )
        )

        response = self.__roboto_client.put(
            f"v1/triggers/{self.name}",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(TriggerRecord)
        self.__record = record
        return self
