# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...exceptions import (
    RobotoIllegalArgumentException,
)
from ...http import RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from ...updates import MetadataChangeset
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
)
from .invocation import Invocation
from .invocation_operations import (
    CreateInvocationRequest,
)
from .invocation_record import (
    InvocationDataSourceType,
    InvocationRecord,
    InvocationSource,
)

SHORT_DESCRIPTION_LENGTH = 140


class Action:
    __record: ActionRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        compute_requirements: typing.Optional[ComputeRequirements] = None,
        container_parameters: typing.Optional[ContainerParameters] = None,
        description: typing.Optional[str] = None,
        inherits: typing.Optional[ActionReference] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        parameters: typing.Optional[list[ActionParameter]] = None,
        short_description: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        timeout: typing.Optional[int] = None,
        uri: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Action":
        request = CreateActionRequest(
            compute_requirements=compute_requirements,
            container_parameters=container_parameters,
            description=description,
            inherits=inherits,
            metadata=metadata or {},
            name=name,
            parameters=parameters or [],
            short_description=short_description,
            tags=tags or [],
            timeout=timeout,
            uri=uri,
        )

        if (
            is_set(request.short_description)
            and request.short_description is not None
            and len(request.short_description) > SHORT_DESCRIPTION_LENGTH
        ):
            raise RobotoIllegalArgumentException(
                f"Short description exceeds max length of {SHORT_DESCRIPTION_LENGTH} characters"
            )

        roboto_client = RobotoClient.defaulted(roboto_client)

        response = roboto_client.post(
            "v1/actions",
            data=request,
            caller_org_id=caller_org_id,
        )
        record = response.to_record(ActionRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        digest: typing.Optional[str] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Action":
        roboto_client = RobotoClient.defaulted(roboto_client)
        query_params = {"digest": digest} if digest else None
        response = roboto_client.get(
            f"v1/actions/{name}",
            query=query_params,
            owner_org_id=owner_org_id,
        )
        record = response.to_record(ActionRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        accessibility: Accessibility = Accessibility.Organization,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Action", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(ActionRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # Support dot notation for nested fields
            # E.g., "metadata.SoftwareVersion"
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = (
                "are not known attributes of Action"
                if plural
                else "is not a known attribute of Action"
            )
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        url_path = (
            "v1/actions/query"
            if accessibility == Accessibility.Organization
            else "v1/actions/query/actionhub"
        )

        while True:
            response = roboto_client.post(
                url_path,
                data=spec,
                idempotent=True,
                owner_org_id=owner_org_id,
            )
            paginated_results = response.to_paginated_list(ActionRecord)
            for record in paginated_results.items:
                yield cls(record, roboto_client)
            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: ActionRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def accessibility(self) -> Accessibility:
        return self.__record.accessibility

    @property
    def compute_requirements(self) -> typing.Optional[ComputeRequirements]:
        return self.__record.compute_requirements

    @property
    def container_parameters(self) -> typing.Optional[ContainerParameters]:
        return self.__record.container_parameters

    @property
    def created(self) -> datetime.datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def digest(self) -> str:
        return (
            self.__record.digest
            if self.__record.digest
            else self.__record.compute_digest()
        )

    @property
    def inherits_from(self) -> typing.Optional[ActionReference]:
        return self.__record.inherits

    @property
    def modified(self) -> datetime.datetime:
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        return self.__record.modified_by

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def parameters(self) -> collections.abc.Sequence[ActionParameter]:
        return [param.model_copy() for param in self.__record.parameters]

    @property
    def record(self) -> ActionRecord:
        return self.__record

    @property
    def uri(self) -> typing.Optional[str]:
        return self.__record.uri

    @property
    def timeout(self) -> typing.Optional[int]:
        return self.__record.timeout

    def delete(self) -> None:
        self.__roboto_client.delete(
            f"v1/actions/{self.name}",
            owner_org_id=self.org_id,
        )

    def invoke(
        self,
        data_source_id: str,
        data_source_type: InvocationDataSourceType,
        input_data: list[str],
        invocation_source: InvocationSource,
        compute_requirement_overrides: typing.Optional[ComputeRequirements] = None,
        container_parameter_overrides: typing.Optional[ContainerParameters] = None,
        idempotency_id: typing.Optional[str] = None,
        invocation_source_id: typing.Optional[str] = None,
        parameter_values: typing.Optional[dict[str, typing.Any]] = None,
        timeout: typing.Optional[int] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> Invocation:
        request = CreateInvocationRequest(
            data_source_id=data_source_id,
            data_source_type=data_source_type,
            input_data=input_data,
            invocation_source=invocation_source,
            compute_requirement_overrides=compute_requirement_overrides,
            container_parameter_overrides=container_parameter_overrides,
            idempotency_id=idempotency_id,
            invocation_source_id=invocation_source_id,
            parameter_values=parameter_values,
            timeout=timeout,
        )

        if request.timeout is None:
            request.timeout = self.__record.timeout

        response = self.__roboto_client.post(
            f"v1/actions/{self.name}/invoke",
            data=request,
            # invocation record will be created in the effective org of the requestor
            caller_org_id=caller_org_id,
            # owner_org_id is the org that owns the action to be invoked
            owner_org_id=self.org_id,
            query={"digest": self.digest},
        )
        record = response.to_record(InvocationRecord)
        return Invocation(record, self.__roboto_client)

    def set_accessibility(self, accessibility: Accessibility) -> "Action":
        request = SetActionAccessibilityRequest(accessibility=accessibility)
        response = self.__roboto_client.put(
            f"v1/actions/{self.name}/accessibility",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(ActionRecord)
        self.__record = record
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        compute_requirements: typing.Optional[
            typing.Union[ComputeRequirements, NotSetType]
        ] = NotSet,
        container_parameters: typing.Optional[
            typing.Union[ContainerParameters, NotSetType]
        ] = NotSet,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        inherits: typing.Optional[typing.Union[ActionReference, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        parameter_changeset: typing.Union[
            ActionParameterChangeset, NotSetType
        ] = NotSet,
        short_description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet,
        uri: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
    ) -> "Action":
        request = remove_not_set(
            UpdateActionRequest(
                compute_requirements=compute_requirements,
                container_parameters=container_parameters,
                description=description,
                inherits=inherits,
                metadata_changeset=metadata_changeset,
                parameter_changeset=parameter_changeset,
                uri=uri,
                short_description=short_description,
                timeout=timeout,
            )
        )

        if (
            is_set(request.short_description)
            and request.short_description is not None
            and len(request.short_description) > SHORT_DESCRIPTION_LENGTH
        ):
            raise RobotoIllegalArgumentException(
                f"Short description exceeds max length of {SHORT_DESCRIPTION_LENGTH} characters"
            )

        response = self.__roboto_client.put(
            f"v1/actions/{self.name}",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(ActionRecord)
        self.__record = record
        return self
