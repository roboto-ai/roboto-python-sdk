# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import warnings

from ...api_version import RobotoApiVersion
from ...exceptions import RobotoConflictException
from ...http import RobotoClient
from ...http.constants import API_VERSION_HEADER
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

_LEGACY_TRIGGER_API_VERSION_HEADERS = {API_VERSION_HEADER: RobotoApiVersion.v2026_08_10.value}
"""Header that pins a request to API version v2026_08_10.

v2026_08_10 is the last API version whose ``/v1/triggers`` endpoints send and accept triggers in this class's
``causes`` and ``for_each`` shape.

From v2026_08_27 on, those endpoints use the shape of :py:class:`~roboto.domain.triggers.Trigger`.
"""


class Trigger:
    """Deprecated. A trigger in the legacy trigger model: a rule that invokes an action when files or metadata change.

    Use :py:class:`~roboto.domain.triggers.Trigger` instead, which reads and edits every trigger.

    A trigger invokes its action when files are uploaded to or ingested in a dataset, or when a dataset's or file's
    metadata changes, and the data meets the trigger's condition and required inputs. It invokes the action once per
    dataset or once per matching file, with the trigger's parameter values and overrides.

    This model cannot express every trigger: one with several targets, an agent or Slack target, or a platform event
    other than those of :py:class:`~roboto.domain.actions.TriggerEvaluationCause`. To this class, such a trigger does
    not exist: ``from_name`` does not find it, ``query`` leaves it out, and ``delete`` leaves it in place.

    Get a ``Trigger`` from ``create``, ``from_name``, or ``query``. Constructing one issues a ``DeprecationWarning``.
    Each instance holds a copy of the trigger's record, which ``update`` replaces with Roboto's response.
    """

    __record: TriggerRecord
    __roboto_client: RobotoClient

    @staticmethod
    def get_evaluations_for_dataset(
        dataset_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator[TriggerEvaluationRecord, None, None]:
        """Yield every trigger's evaluations of a dataset, newest first, fetching them a page at a time.

        Args:
            dataset_id: ID of the dataset.
            owner_org_id: Organization that owns the dataset. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No dataset has this ID. It surfaces on the first iteration.

        Examples:
            Print each evaluation's trigger, status, and outcome:

            >>> from roboto.domain.actions import Trigger
            >>> for evaluation in Trigger.get_evaluations_for_dataset("ds_12345"):
            ...     print(evaluation.trigger_id, evaluation.status, evaluation.outcome)

            Collect the evaluations that invoked an action:

            >>> from roboto.domain.actions import TriggerEvaluationOutcome
            >>> invoked = [
            ...     evaluation
            ...     for evaluation in Trigger.get_evaluations_for_dataset("ds_12345")
            ...     if evaluation.outcome == TriggerEvaluationOutcome.InvokedAction
            ... ]
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
                headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
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
        """Create a trigger that invokes an action when a dataset's files or metadata change.

        Args:
            name: Human-readable name of the trigger, unique within its organization. Letters, digits, underscores,
                and hyphens only, at most 256 characters.
            action_name: Name of the action to invoke, unique within the organization that owns it.
            required_inputs: Gitignore-style patterns, such as ``**/*.bag``, for the files the trigger requires and
                passes to the action as its input data. With ``for_each`` set to
                :py:attr:`~roboto.domain.actions.TriggerForEachPrimitive.Dataset`, the trigger invokes its action when
                each pattern matches at least one file in the dataset. With
                :py:attr:`~roboto.domain.actions.TriggerForEachPrimitive.DatasetFile`, it invokes the action once for
                each file that matches any pattern. At least one pattern must be neither empty nor only whitespace.
            for_each: Whether the trigger invokes its action once per dataset or once per file.
            enabled: Whether the trigger is enabled as soon as it is created.
            action_digest: Digest of the action version to invoke. ``None`` invokes the latest version.
            action_owner_id: ID of the organization that owns the action. ``None`` means the organization the trigger
                is created in.
            additional_inputs: Gitignore-style patterns for more files to pass to the action as input data. Unlike
                ``required_inputs``, no file has to match them for the trigger to invoke its action. ``None`` adds no
                files; a list must contain at least one pattern that is neither empty nor only whitespace.
            causes: Platform events that cause Roboto to evaluate the trigger. ``None`` evaluates it when files are
                uploaded. :py:attr:`~roboto.domain.actions.TriggerEvaluationCause.RecurringSchedule` is rejected.
            compute_requirement_overrides: Compute requirements that replace the action's own in each invocation.
                ``None`` uses the action's own.
            condition: Condition the data must meet for the trigger to invoke its action. ``None`` sets none.
            container_parameter_overrides: Container parameters that replace the action's own in each invocation.
                ``None`` uses the action's own.
            parameter_values: Values for the action's parameters, keyed by parameter name, that each invocation
                receives. ``None`` passes none.
            service_user_id: Deprecated. Roboto ignores it: a trigger's invocations run as its organization's service
                user.
            timeout: Maximum run time of each invocation, in minutes. ``None`` uses the action's timeout.
            caller_org_id: Organization to create the trigger in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new trigger.

        Raises:
            pydantic.ValidationError: ``name`` has a character other than a letter, digit, underscore, or hyphen, or
                is longer than 256 characters, or every pattern in ``required_inputs`` or ``additional_inputs`` is
                empty or only whitespace.
            RobotoConflictException: The organization already has a trigger with this name.
            RobotoNotFoundException: No action has this name in the organization that owns it.
            RobotoInvalidRequestException: Roboto rejects the trigger's settings, such as a ``causes`` that includes
                ``RecurringSchedule``.

        Note:
            If enabling the trigger would put the organization over its limit of enabled triggers, Roboto creates it
            disabled.

        Examples:
            Invoke an action once for each dataset that contains a ROS bag:

            >>> from roboto.domain.actions import Trigger, TriggerForEachPrimitive
            >>> trigger = Trigger.create(
            ...     name="auto_process_bags",
            ...     action_name="ros_ingestion",
            ...     required_inputs=["**/*.bag"],
            ...     for_each=TriggerForEachPrimitive.Dataset,
            ... )

            Invoke an action with parameter values, only on datasets whose metadata meets a condition:

            >>> from roboto.query import Comparator, Condition
            >>> trigger = Trigger.create(
            ...     name="lidar_processing",
            ...     action_name="lidar_processor",
            ...     required_inputs=["**/*.pcd"],
            ...     for_each=TriggerForEachPrimitive.Dataset,
            ...     condition=Condition(field="metadata.sensor_type", comparator=Comparator.Equals, value="lidar"),
            ...     parameter_values={"resolution": "high", "filter": "statistical"},
            ... )

            Invoke an action once for each image file, with more CPU and memory than the action asks for:

            >>> from roboto.domain.actions import ComputeRequirements
            >>> trigger = Trigger.create(
            ...     name="heavy_processing",
            ...     action_name="ml_inference",
            ...     required_inputs=["**/*.jpg", "**/*.png"],
            ...     for_each=TriggerForEachPrimitive.DatasetFile,
            ...     compute_requirement_overrides=ComputeRequirements(vCPU=8192, memory=16384),
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
            headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
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
        """Fetch a trigger by name.

        Trigger names are unique within an organization, so a name and an organization identify one trigger.

        Args:
            name: Name of the trigger.
            owner_org_id: Organization that owns the trigger. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no trigger with this name, or that trigger is one the legacy
                trigger model cannot express.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> trigger = Trigger.from_name("auto_process_bags")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get(
            f"v1/triggers/{name}",
            owner_org_id=owner_org_id,
            headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
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
        """Yield the organization's triggers that match a query, fetching them a page at a time.

        Scheduled triggers, and triggers the legacy trigger model cannot express, are left out. A condition can name
        a field of :py:class:`~roboto.domain.actions.TriggerRecord`, or ``action.name``, ``action.owner``, or
        ``action.digest`` for the action a trigger invokes.

        Args:
            spec: Conditions and sort order of the query. ``None`` matches every trigger in the organization. The
                method sets ``spec.after`` on the object passed in as it fetches each page.
            owner_org_id: Organization to query triggers in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoIllegalArgumentException: The query names a field triggers cannot be queried by. It surfaces on the
                first iteration.

        Examples:
            Print the names of the triggers that invoke one action:

            >>> from roboto.domain.actions import Trigger
            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(field="action.name", comparator=Comparator.Equals, value="ros_ingestion")
            ... )
            >>> for trigger in Trigger.query(spec):
            ...     print(trigger.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        while True:
            response = roboto_client.post(
                "v1/triggers/query",
                data=spec,
                owner_org_id=owner_org_id,
                idempotent=True,
                headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
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
        warnings.warn(
            "roboto.domain.actions.Trigger is the legacy trigger model and will be removed; "
            "use roboto.domain.triggers.Trigger.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def condition(self) -> typing.Optional[ConditionType]:
        """Condition the data must meet for the trigger to invoke its action, or ``None`` if the trigger has none."""
        return self.__record.condition

    @property
    def created(self) -> datetime.datetime:
        """Time the trigger was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the trigger."""
        return self.__record.created_by

    @property
    def enabled(self) -> bool:
        """Whether the trigger is enabled. A disabled trigger never invokes its action."""
        return self.__record.enabled

    @property
    def for_each(self) -> TriggerForEachPrimitive:
        """Whether the trigger invokes its action once per dataset or once per file."""
        return self.__record.for_each

    @property
    def name(self):
        """Human-readable name of the trigger, unique within its organization."""
        return self.__record.name

    @property
    def modified(self) -> datetime.datetime:
        """Time the trigger was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the trigger.

        Roboto's own system user when Roboto made the change.
        """
        return self.__record.modified_by

    @property
    def org_id(self):
        """ID of the organization that owns the trigger."""
        return self.__record.org_id

    @property
    def record(self) -> TriggerRecord:
        """Record of the trigger that this instance holds."""
        return self.__record

    @property
    def service_user_id(self) -> typing.Optional[str]:
        """ID of the service user the trigger invokes its action as."""
        return self.__record.service_user_id

    @property
    def trigger_id(self) -> str:
        """Unique ID of the trigger."""
        return self.__record.trigger_id

    def delete(self):
        """Delete the trigger.

        Deleting a trigger that no longer exists succeeds and changes nothing.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> Trigger.from_name("auto_process_bags").delete()
        """
        self.__roboto_client.delete(
            f"v1/triggers/{self.name}",
            owner_org_id=self.org_id,
            headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
        )

    def disable(self):
        """Disable the trigger, so that it stops invoking its action, and update this instance's record.

        It calls ``update``, whose failures also apply.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> Trigger.from_name("auto_process_bags").disable()
        """
        self.update(enabled=False)

    def enable(self):
        """Enable the trigger, and update this instance's record.

        It calls ``update``, whose failures also apply.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> Trigger.from_name("auto_process_bags").enable()
        """
        self.update(enabled=True)

    def get_action(self) -> Action:
        """Fetch the action the trigger invokes, at the trigger's digest, or the latest version if it has none.

        Raises:
            RobotoNotFoundException: The action no longer exists, or has no version with the trigger's digest.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> action = Trigger.from_name("auto_process_bags").get_action()
            >>> print(action.name)
        """
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
        """Yield the trigger's evaluations, newest first, fetching them a page at a time.

        Args:
            limit: Maximum number of evaluations per request. ``None`` uses Roboto's default of 100. It does not limit
                the total: the generator fetches pages until none remain.
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at
                the first page.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> for evaluation in Trigger.from_name("auto_process_bags").get_evaluations():
            ...     print(evaluation.evaluation_start, evaluation.status, evaluation.outcome)
        """
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
                headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
            )
            paginated_results = response.to_paginated_list(TriggerEvaluationRecord)
            for record in paginated_results.items:
                yield record
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def get_invocations(self) -> collections.abc.Generator[Invocation, None, None]:
        """Yield the invocations Roboto started for this trigger, fetching them a page at a time.

        Invocations made with ``invoke`` are not included.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> for invocation in Trigger.from_name("auto_process_bags").get_invocations():
            ...     print(invocation.id)
        """
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
        """Fetch the trigger's most recent evaluation, or ``None`` if it has never been evaluated.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> evaluation = Trigger.from_name("auto_process_bags").latest_evaluation()
            >>> if evaluation is not None:
            ...     print(evaluation.status, evaluation.outcome)
        """
        evaluations = list(self.get_evaluations(limit=1))
        return evaluations[0] if evaluations else None

    def invoke(
        self,
        data_source: InvocationDataSource,
        idempotency_id: typing.Optional[str] = None,
        input_data_override: typing.Optional[list[str]] = None,
        upload_destination: typing.Optional[InvocationUploadDestination] = None,
    ) -> typing.Optional[Invocation]:
        """Invoke the trigger's action on a data source, with the trigger's input data, parameter values, and overrides.

        Only Roboto administrators can call this method: Roboto raises ``RobotoUnauthorizedException`` for any other
        caller. The invocation records this trigger, by name, as its source.

        Args:
            data_source: Data source for the action to read from.
            idempotency_id: ID that makes the invocation run at most once: another call with the same ID in the same
                organization creates no second invocation. ``None`` sets none.
            input_data_override: Gitignore-style patterns for the input files, in place of the trigger's
                ``required_inputs``. ``None`` or an empty list uses ``required_inputs``.
            upload_destination: Where Roboto uploads the files the action writes to its output directory. ``None``
                uploads them to the dataset the inputs come from, when they all come from one.

        Returns:
            The new invocation, or ``None`` if an invocation with ``idempotency_id`` already exists.
        """
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
            # Roboto raises this when the organization already has an invocation with this idempotency_id.
            return None

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the trigger's record as a dictionary of JSON-compatible values.

        Returns:
            :py:class:`~roboto.domain.actions.TriggerRecord` of the trigger, as a JSON-compatible dictionary.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> trigger_dict = Trigger.from_name("auto_process_bags").to_dict()
            >>> print(trigger_dict["trigger_id"])
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        action_name: typing.Union[str, NotSetType] = NotSet,
        action_owner_id: typing.Union[str, NotSetType] = NotSet,
        action_digest: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        additional_inputs: typing.Optional[typing.Union[list[str], NotSetType]] = NotSet,
        causes: typing.Union[list[TriggerEvaluationCause], NotSetType] = NotSet,
        compute_requirement_overrides: typing.Optional[typing.Union[ComputeRequirements, NotSetType]] = NotSet,
        container_parameter_overrides: typing.Optional[typing.Union[ContainerParameters, NotSetType]] = NotSet,
        condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet,
        enabled: typing.Union[bool, NotSetType] = NotSet,
        for_each: typing.Union[TriggerForEachPrimitive, NotSetType] = NotSet,
        parameter_values: typing.Optional[typing.Union[dict[str, typing.Any], NotSetType]] = NotSet,
        required_inputs: typing.Union[list[str], NotSetType] = NotSet,
        timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet,
    ) -> "Trigger":
        """Update the trigger's settings.

        An argument left unset (``NotSet``) leaves that setting unchanged.

        Args:
            action_name: Name of the action to invoke, unique within the organization that owns it.
            action_owner_id: ID of the organization that owns the action.
            action_digest: Digest of the action version to invoke. ``None`` invokes the latest version.
            additional_inputs: Gitignore-style patterns for more files to pass to the action as input data. ``None``
                clears them.
            causes: Platform events that cause Roboto to evaluate the trigger.
            compute_requirement_overrides: Compute requirements that replace the action's own in each invocation.
                ``None`` clears the override, so invocations use the action's own.
            container_parameter_overrides: Container parameters that replace the action's own in each invocation.
                ``None`` clears the override, so invocations use the action's own.
            condition: Condition the data must meet for the trigger to invoke its action. ``None`` clears it.
            enabled: Whether the trigger is enabled.
            for_each: Whether the trigger invokes its action once per dataset or once per file.
            parameter_values: Values for the action's parameters, keyed by parameter name. ``None`` clears them.
            required_inputs: Gitignore-style patterns for the files the trigger requires, matched as described on
                ``create``.
            timeout: Maximum run time of each invocation, in minutes. ``None`` clears the override, so invocations
                use the action's timeout.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The action the trigger would invoke does not exist.
            RobotoInvalidRequestException: Roboto rejects the updated settings.

        Examples:
            Point the trigger at a pinned version of its action:

            >>> from roboto.domain.actions import Trigger
            >>> trigger = Trigger.from_name("auto_process_bags")
            >>> trigger.update(action_digest="abc123")

            Clear the trigger's condition:

            >>> trigger.update(condition=None)
        """
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
            headers=dict(_LEGACY_TRIGGER_API_VERSION_HEADERS),
        )
        record = response.to_record(TriggerRecord)
        self.__record = record
        return self

    def wait_for_evaluations_to_complete(
        self,
        timeout: float = 60 * 5,
        poll_interval: Interval = 5,
    ) -> None:
        """Wait until none of the trigger's evaluations is pending.

        Each poll fetches every evaluation the trigger has.

        Args:
            timeout: Maximum time to wait, in seconds. Defaults to 300 (five minutes).
            poll_interval: Time to wait between polls, in seconds, or a function that takes the number of polls made
                so far and returns the seconds to wait before the next one.

        Raises:
            roboto.waiters.TimeoutError: An evaluation is still pending after ``timeout`` seconds.

        Examples:
            >>> from roboto.domain.actions import Trigger
            >>> Trigger.from_name("auto_process_bags").wait_for_evaluations_to_complete(timeout=60)
        """
        wait_for(
            lambda: all(
                [evaluation.status != TriggerEvaluationStatus.Pending for evaluation in self.get_evaluations()]
            ),
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for evaluations for trigger '{self.name}' to complete",
        )
