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
    Comparator,
    Condition,
    ConditionType,
    QuerySpecification,
)
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...waiters import Interval, wait_for
from .action import Action
from .invocation import Invocation
from .invocation_record import (
    ComputeRequirements,
    ContainerParameters,
    InvocationDataSource,
    InvocationSource,
    InvocationUploadDestination,
)
from .trigger_operations import (
    CreateTriggerRequest,
    UpdateTriggerRequest,
)
from .trigger_record import (
    TriggerEvaluationCause,
    TriggerEvaluationRecord,
    TriggerEvaluationStatus,
    TriggerForEachPrimitive,
    TriggerRecord,
)


class Trigger:
    """A rule that automatically invokes an action when specific events or conditions occur.

    Triggers enable automated data processing workflows by monitoring for specific
    events (like new datasets being created) and automatically invoking actions
    when conditions are met. They eliminate the need for manual intervention in
    routine data processing tasks.

    Triggers can be configured to:

    - Monitor for new datasets, files, or other data sources
    - Apply conditional logic to determine when to execute
    - Specify input data patterns and action parameters
    - Override compute requirements and container parameters
    - Execute actions for each matching item or in batch

    A trigger consists of:

    - Target action to invoke
    - Input data requirements and patterns
    - Execution conditions and causes
    - Parameter values and overrides
    - Scheduling and execution settings
    """

    __record: TriggerRecord
    __roboto_client: RobotoClient

    @staticmethod
    def get_evaluations_for_dataset(
        dataset_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator[TriggerEvaluationRecord, None, None]:
        """Get all trigger evaluations for a specific dataset.

        Retrieves the history of trigger evaluations that were performed for
        a given dataset, including successful invocations and failed attempts.

        Args:
            dataset_id: The ID of the dataset to get evaluations for.
            owner_org_id: Organization ID that owns the dataset. If not provided,
                searches in the caller's organization.
            roboto_client: Roboto client instance. Uses default if not provided.

        Yields:
            TriggerEvaluationRecord instances for the dataset.

        Raises:
            RobotoNotFoundException: If the dataset is not found.
            RobotoUnauthorizedException: If the caller lacks permission to access evaluations.

        Examples:
            Get all evaluations for a dataset:

            >>> for evaluation in Trigger.get_evaluations_for_dataset("ds_12345"):
            ...     print(f"Trigger: {evaluation.trigger_name}, Status: {evaluation.status}")

            Check if any triggers succeeded for a dataset:

            >>> from roboto.domain.actions import TriggerEvaluationStatus
            >>> evaluations = list(Trigger.get_evaluations_for_dataset("ds_12345"))
            >>> successful = [e for e in evaluations if e.status == TriggerEvaluationStatus.Succeeded]
            >>> print(f"Found {len(successful)} successful trigger evaluations")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        page_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if page_token is not None:
                query_params["page_token"] = page_token

            paginated_results = roboto_client.get(
                f"v1/triggers/dataset/id/{dataset_id}/evaluations",
                query=query_params,
                owner_org_id=owner_org_id,
            ).to_paginated_list(TriggerEvaluationRecord)
            for record in paginated_results.items:
                yield record
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    @classmethod
    def create(
        cls,
        name: str,
        action_name: str,
        required_inputs: list[str],
        for_each: TriggerForEachPrimitive,
        enabled: bool = True,
        action_digest: typing.Optional[str] = None,
        action_owner_id: typing.Optional[str] = None,
        additional_inputs: typing.Optional[list[str]] = None,
        causes: typing.Optional[list[TriggerEvaluationCause]] = None,
        compute_requirement_overrides: typing.Optional[ComputeRequirements] = None,
        condition: typing.Optional[ConditionType] = None,
        container_parameter_overrides: typing.Optional[ContainerParameters] = None,
        parameter_values: typing.Optional[dict[str, typing.Any]] = None,
        service_user_id: typing.Optional[str] = None,
        timeout: typing.Optional[int] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Trigger":
        """Create a new trigger that automatically invokes an action when conditions are met.

        Creates a trigger that monitors for specific events (like new datasets or files)
        and automatically invokes the specified action when the trigger conditions are
        satisfied. This enables automated data processing workflows.

        Args:
            name: Unique name for the trigger within the organization.
            action_name: Name of the action to invoke when the trigger fires.
            required_inputs: List of file patterns that must be present for the trigger to fire.
                Uses glob patterns like "**/*.bag" or "data/*.csv".
            for_each: Granularity of execution - Dataset creates one invocation per dataset,
                DatasetFile creates one invocation per matching file.
            enabled: Whether the trigger should be active immediately after creation.
            action_digest: Specific version digest of the action to invoke. If not provided,
                uses the latest version.
            action_owner_id: Organization ID that owns the target action. If not provided,
                searches in the caller's organization.
            additional_inputs: Optional additional file patterns to include in invocations.
            causes: List of events that can cause this trigger to be evaluated. If not
                provided, uses default causes.
            compute_requirement_overrides: Optional compute requirement overrides for
                action invocations.
            condition: Optional condition that must be met for the trigger to fire.
                Can filter based on metadata, file properties, etc.
            container_parameter_overrides: Optional container parameter overrides for
                action invocations.
            parameter_values: Parameter values to pass to the action when invoked.
            service_user_id: Optional service user ID for authentication.
            timeout: Optional timeout override for action invocations in minutes.
            caller_org_id: Organization ID to create the trigger in. Defaults to caller's org.
            roboto_client: Roboto client instance. Uses default if not provided.

        Returns:
            The newly created Trigger instance.

        Raises:
            RobotoIllegalArgumentException: If the trigger configuration is invalid.
            RobotoInvalidRequestException: If the request is malformed.
            RobotoUnauthorizedException: If the caller lacks permission to create triggers.

        Examples:
            Create a simple trigger for ROS bag files:

            >>> from roboto.domain.actions import Trigger, TriggerForEachPrimitive
            >>> trigger = Trigger.create(
            ...     name="auto_process_bags",
            ...     action_name="ros_ingestion",
            ...     required_inputs=["**/*.bag"],
            ...     for_each=TriggerForEachPrimitive.Dataset
            ... )

            Create a conditional trigger with parameters:

            >>> from roboto.query import Condition
            >>> condition = Condition("metadata.sensor_type").equals("lidar")
            >>> trigger = Trigger.create(
            ...     name="lidar_processing",
            ...     action_name="lidar_processor",
            ...     required_inputs=["**/*.pcd"],
            ...     for_each=TriggerForEachPrimitive.Dataset,
            ...     condition=condition,
            ...     parameter_values={"resolution": "high", "filter": "statistical"}
            ... )

            Create a trigger with compute overrides:

            >>> from roboto.domain.actions import ComputeRequirements
            >>> trigger = Trigger.create(
            ...     name="heavy_processing",
            ...     action_name="ml_inference",
            ...     required_inputs=["**/*.jpg", "**/*.png"],
            ...     for_each=TriggerForEachPrimitive.DatasetFile,
            ...     compute_requirement_overrides=ComputeRequirements(vCPU=8192, memory=16384)
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateTriggerRequest(
            action_digest=action_digest,
            action_name=action_name,
            action_owner_id=action_owner_id,
            additional_inputs=additional_inputs,
            causes=causes,
            compute_requirement_overrides=compute_requirement_overrides,
            condition=condition,
            container_parameter_overrides=container_parameter_overrides,
            enabled=enabled,
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

    @property
    def trigger_id(self) -> str:
        return self.__record.trigger_id

    def delete(self):
        self.__roboto_client.delete(
            f"v1/triggers/{self.name}",
            owner_org_id=self.org_id,
        )

    def disable(self):
        self.update(enabled=False)

    def enable(self):
        self.update(enabled=True)

    def get_action(self) -> Action:
        return Action.from_name(
            self.__record.action.name,
            digest=self.__record.action.digest,
            owner_org_id=self.__record.action.owner,
            roboto_client=self.__roboto_client,
        )

    def get_evaluations(
        self,
        limit: typing.Optional[int] = None,
        page_token: typing.Optional[str] = None,
    ) -> collections.abc.Generator[TriggerEvaluationRecord, None, None]:
        query_params: dict[str, typing.Union[int, str]] = {}
        if limit is not None:
            query_params["limit"] = limit

        while True:
            if page_token is not None:
                query_params["page_token"] = page_token
            response = self.__roboto_client.get(
                f"v1/triggers/{self.name}/evaluations",
                query=query_params,
                owner_org_id=self.org_id,
            )
            paginated_results = response.to_paginated_list(TriggerEvaluationRecord)
            for record in paginated_results.items:
                yield record
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def get_invocations(self) -> collections.abc.Generator[Invocation, None, None]:
        query_spec = QuerySpecification(
            condition=Condition(
                field="provenance.source.source_id",
                comparator=Comparator.Equals,
                value=self.trigger_id,
            )
        )
        yield from Invocation.query(
            query_spec,
            owner_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def latest_evaluation(self) -> typing.Optional[TriggerEvaluationRecord]:
        evaluations = list(self.get_evaluations(limit=1))
        return evaluations[0] if evaluations else None

    def invoke(
        self,
        data_source: InvocationDataSource,
        idempotency_id: typing.Optional[str] = None,
        input_data_override: typing.Optional[list[str]] = None,
        upload_destination: typing.Optional[InvocationUploadDestination] = None,
    ) -> typing.Optional[Invocation]:
        try:
            return self.get_action().invoke(
                compute_requirement_overrides=self.__record.compute_requirement_overrides,
                container_parameter_overrides=self.__record.container_parameter_overrides,
                data_source_id=data_source.data_source_id,
                data_source_type=data_source.data_source_type,
                input_data=input_data_override or self.__record.required_inputs,
                upload_destination=upload_destination,
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
        causes: typing.Union[list[TriggerEvaluationCause], NotSetType] = NotSet,
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
                causes=causes,
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

    def wait_for_evaluations_to_complete(
        self,
        timeout: float = 60 * 5,  # 5 minutes in seconds
        poll_interval: Interval = 5,
    ) -> None:
        """
        Wait for all evaluations for this trigger to complete.

        Throws a :py:exc:`~roboto.waiters.TimeoutError` if the timeout is reached.

        Args:
            timeout: The maximum amount of time, in seconds, to wait for the evaluations to complete.
            poll_interval: The amount of time, in seconds, to wait between polling iterations.
        """
        wait_for(
            lambda: all(
                [
                    evaluation.status != TriggerEvaluationStatus.Pending
                    for evaluation in self.get_evaluations()
                ]
            ),
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for evaluations for trigger '{self.name}' to complete",
        )
