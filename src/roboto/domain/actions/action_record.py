# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import enum
import hashlib
import json
import typing

import pydantic

from roboto.pydantic.serializers import (
    field_serializer_user_metadata,
)
from roboto.types import UserMetadata


class Accessibility(str, enum.Enum):
    """
    Controls who can query for and invoke an action.

    Future accessibility levels may include: "user" and/or "team".
    """

    Organization = "organization"
    """All members of the organization owning the Action can query for and invoke the action."""

    ActionHub = "action_hub"
    """All users of Roboto can query for and invoke the action."""


class ActionParameter(pydantic.BaseModel):
    name: str
    required: bool = False
    description: typing.Optional[str] = None
    default: typing.Optional[typing.Any] = None
    """
    Default value applied for parameter if it is not required and no value is given at invocation.
    Accepts any default value, but coerced to a string.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ActionParameter):
            return NotImplemented

        return (
            self.name == other.name
            and self.required == other.required
            and self.description == other.description
            and self.default == other.default
        )

    @pydantic.field_validator("default", mode="before")
    @classmethod
    def validate_default(cls, v: typing.Optional[typing.Any]) -> typing.Optional[str]:
        if v is None:
            return v

        return str(v)


class ActionParameterChangeset(pydantic.BaseModel):
    put_parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    remove_parameters: list[str] = pydantic.Field(default_factory=list)

    class Builder:
        __put_parameters: list[ActionParameter]
        __remove_parameters: list[str]

        def __init__(self) -> None:
            self.__put_parameters = []
            self.__remove_parameters = []

        def put_parameter(
            self, parameter: ActionParameter
        ) -> "ActionParameterChangeset.Builder":
            self.__put_parameters.append(parameter)
            return self

        def remove_parameter(
            self, parameter_name: str
        ) -> "ActionParameterChangeset.Builder":
            self.__remove_parameters.append(parameter_name)
            return self

        def build(self) -> "ActionParameterChangeset":
            changeset: collections.abc.Mapping = {
                "put_parameters": self.__put_parameters,
                "remove_parameters": self.__remove_parameters,
            }
            return ActionParameterChangeset(**{k: v for k, v in changeset.items() if v})

    def is_empty(self) -> bool:
        return not self.put_parameters and not self.remove_parameters


class ActionReference(pydantic.BaseModel):
    """Qualified action reference."""

    name: str
    digest: typing.Optional[str] = None
    owner: typing.Optional[str] = None

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ActionReference):
            return NotImplemented

        return (
            self.name == other.name
            and self.digest == other.digest
            and self.owner == other.owner
        )

    def __str__(self) -> str:
        return (
            f"{self.owner}/{self.name}"
            if not self.digest
            else f"{self.owner}/{self.name}@{self.digest}"
        )


class ExecutorContainer(enum.Enum):
    LogRouter = "firelens_log_router"
    Monitor = "monitor"
    Setup = "setup"
    Action = "action"
    OutputHandler = "output_handler"


class ComputeRequirements(pydantic.BaseModel):
    """
    Compute requirements for an action invocation.

    .. _Relevant AWS Fargate documentation:
        https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html#fargate-tasks-size
    """

    vCPU: int = 512  # 256, 512, 1024, 2048, 4096, 8192, 16384
    memory: int = 1024  # 512, 1024, 2024, ... (120 * 1024) in MiB
    gpu: typing.Literal[False] = False  # Not yet supported
    storage: int = 21  # in GiB (min 21, max 200 if on premium tier)

    @pydantic.model_validator(mode="after")
    def validate_storage_limit(self):
        if self.storage < 21:
            raise ValueError(
                f"Unsupported Storage value {self.storage}. Storage must be at least 21 GiB."
            )
        return self

    @pydantic.model_validator(mode="after")
    def validate_vcpu_mem_combination(self) -> "ComputeRequirements":
        allowed_vpcu = (256, 512, 1024, 2048, 4096, 8192, 16384)
        if self.vCPU not in allowed_vpcu:
            raise ValueError(f"Unsupported vCPU value. Allowed options: {allowed_vpcu}")

        memory = self.memory
        allowed_memory: collections.abc.Sequence[int] = list()
        if self.vCPU == 256:
            allowed_memory = [512, 1024, 2048]
        elif self.vCPU == 512:
            allowed_memory = range(1024, 5 * 1024, 1024)
        elif self.vCPU == 1024:
            allowed_memory = range(2 * 1024, 9 * 1024, 1024)
        elif self.vCPU == 2048:
            allowed_memory = range(4 * 1024, 17 * 1024, 1024)
        elif self.vCPU == 4096:
            allowed_memory = range(8 * 1024, 31 * 1024, 1024)
        elif self.vCPU == 8192:
            allowed_memory = range(16 * 1024, 61 * 1024, 4 * 1024)
        elif self.vCPU == 16384:
            allowed_memory = range(32 * 1024, 121 * 1024, 8 * 1024)
        else:
            raise ValueError(f"Unknown vCPU value {self.vCPU}")

        if memory not in allowed_memory:
            raise ValueError(
                f"Unsupported memory/vCPU combination, allowed memory for {self.vCPU} vCPU: {list(allowed_memory)}"
            )

        return self

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ComputeRequirements):
            return NotImplemented

        return (
            self.vCPU == other.vCPU
            and self.memory == other.memory
            and self.gpu == other.gpu
            and self.storage == other.storage
        )

    model_config = pydantic.ConfigDict(extra="forbid")


class ContainerParameters(pydantic.BaseModel):
    command: typing.Optional[list[str]] = None
    entry_point: typing.Optional[list[str]] = None
    env_vars: typing.Optional[dict[str, str]] = None
    workdir: typing.Optional[str] = None

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ContainerParameters):
            return NotImplemented

        return (
            self.command == other.command
            and self.entry_point == other.entry_point
            and self.env_vars == other.env_vars
            and self.workdir == other.workdir
        )

    model_config = pydantic.ConfigDict(extra="forbid")


class ActionRecord(pydantic.BaseModel):
    # Required fields without defaults
    created: datetime.datetime  # Persisted as ISO 8601 string in UTC
    created_by: str
    modified: datetime.datetime  # Persisted as ISO 8601 string in UTC
    modified_by: str
    name: str  # Sort key
    org_id: str  # Partition key

    # Optional fields with defaults
    accessibility: Accessibility = Accessibility.Organization
    compute_requirements: typing.Optional[ComputeRequirements] = None
    container_parameters: typing.Optional[ContainerParameters] = None
    description: typing.Optional[str] = None
    digest: typing.Optional[str] = None
    inherits: typing.Optional[ActionReference] = None
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    # Persisted as ISO 8601 string in UTC
    published: typing.Optional[datetime.datetime] = None
    tags: list[str] = pydantic.Field(default_factory=list)
    uri: typing.Optional[str] = None
    short_description: typing.Optional[str] = None
    timeout: typing.Optional[int] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.digest = self.compute_digest() if not self.digest else self.digest

    def compute_digest(self) -> str:
        hasher = hashlib.blake2b(
            digest_size=16,
            # https://docs.python.org/3.9/library/hashlib.html#personalization
            person=b"ActionRecord",
        )
        digestable = self.model_dump(exclude_unset=True, mode="json")
        hasher.update(json.dumps(digestable, sort_keys=True).encode("utf-8"))
        return hasher.hexdigest()

    @property
    def reference(self) -> ActionReference:
        return ActionReference(
            name=self.name,
            digest=self.digest,
            owner=self.org_id,
        )

    @pydantic.field_serializer("metadata")
    def serialize_metadata(self, metadata: dict[str, typing.Any]) -> UserMetadata:
        return field_serializer_user_metadata(metadata)
