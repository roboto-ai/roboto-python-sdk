# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import json
import typing

import pydantic

from .action_record import (
    ComputeRequirements,
    ContainerParameters,
    ExecutorContainer,
)


class InvocationDataSourceType(enum.Enum):
    """Source of data for an Action's InputBinding"""

    Dataset = "Dataset"


class InvocationDataSource(pydantic.BaseModel):
    data_source_type: InvocationDataSourceType
    # The "type" determines the meaning of "id":
    #   - if type is "Dataset," id is a dataset_id
    data_source_id: str


class ActionProvenance(pydantic.BaseModel):
    name: str
    org_id: str
    # 2023-09-11 (GM): Optional for backwards compatibility; new invocations will always have a digest
    digest: typing.Optional[str] = None


class ExecutableProvenance(pydantic.BaseModel):
    # Optional for backwards compatibility
    container_image_uri: typing.Optional[str] = None
    container_image_digest: typing.Optional[str] = None


class InvocationSource(enum.Enum):
    Trigger = "Trigger"
    Manual = "Manual"


class SourceProvenance(pydantic.BaseModel):
    source_type: InvocationSource
    # The “type” determines the meaning of “id:”
    #   - if type is “Trigger,” id is a TriggerId;
    #   - if type is “Manual,” id is a UserId.
    source_id: str


class InvocationProvenance(pydantic.BaseModel):
    action: ActionProvenance
    """The Action that was invoked."""

    executable: ExecutableProvenance
    """The underlying executable (e.g., Docker image) that was run."""

    source: SourceProvenance
    """The source of the invocation."""


class InvocationStatus(int, enum.Enum):
    Queued = 0
    Scheduled = 1
    Downloading = 2
    Processing = 3
    Uploading = 4
    Completed = 5
    # Failure status' and cancellation exists outside linear progression of invocation status
    Cancelled = 997
    Failed = 998
    Deadly = 999

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def from_value(v: typing.Union[int, str]) -> "InvocationStatus":
        for value in InvocationStatus:
            if v in [value.value, value.name]:
                return value

        raise ValueError(f"Illegal Invocation status {v}")

    def can_transition_to(self, other: "InvocationStatus") -> bool:
        if self == other:
            return True

        if self in {
            InvocationStatus.Completed,
            InvocationStatus.Cancelled,
            InvocationStatus.Deadly,
        }:
            return False

        if self is InvocationStatus.Failed:
            if other in {InvocationStatus.Queued, InvocationStatus.Deadly}:
                return True
            return False

        if other in {InvocationStatus.Cancelled, InvocationStatus.Failed}:
            return True

        if other is InvocationStatus.Deadly:
            return self in {InvocationStatus.Queued, InvocationStatus.Failed}

        return other.value > self.value

    def is_running(self) -> bool:
        return self in {
            InvocationStatus.Downloading,
            InvocationStatus.Processing,
            InvocationStatus.Uploading,
        }

    def is_terminal(self) -> bool:
        return self in {
            InvocationStatus.Completed,
            InvocationStatus.Cancelled,
            InvocationStatus.Failed,
            InvocationStatus.Deadly,
        }

    def next(self) -> typing.Optional["InvocationStatus"]:
        if self.is_terminal():
            return None
        return InvocationStatus(self.value + 1)


class InvocationStatusRecord(pydantic.BaseModel):
    status: InvocationStatus
    detail: typing.Optional[str] = None
    timestamp: datetime.datetime  # Persisted as ISO 8601 string in UTC

    def to_presentable_dict(self) -> dict[str, typing.Optional[str]]:
        return {
            "status": str(self.status),
            "timestamp": self.timestamp.isoformat(),
            "detail": self.detail,
        }


class LogsLocation(pydantic.BaseModel):
    bucket: str
    prefix: str


class InvocationRecord(pydantic.BaseModel):
    # When adding or removing fields, make sure to update __str__
    created: datetime.datetime  # Persisted as ISO 8601 string in UTC
    data_source: InvocationDataSource
    input_data: list[str]
    invocation_id: str  # Sort key
    idempotency_id: typing.Optional[str] = None
    compute_requirements: ComputeRequirements
    container_parameters: ContainerParameters
    last_heartbeat: typing.Optional[datetime.datetime] = None
    last_status: InvocationStatus
    org_id: str  # Partition key
    parameter_values: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    provenance: InvocationProvenance
    status: list[InvocationStatusRecord] = pydantic.Field(default_factory=list)
    duration: datetime.timedelta = pydantic.Field(default_factory=datetime.timedelta)
    timeout: int

    def __str__(self) -> str:
        return json.dumps(
            {
                "created": self.created.isoformat(),
                "data_source": self.data_source.model_dump(mode="json"),
                "input_data": self.input_data,
                "invocation_id": self.invocation_id,
                "idempotency_id": self.idempotency_id,
                "compute_requirements": self.compute_requirements.model_dump(
                    mode="json"
                ),
                "container_parameters": self.container_parameters.model_dump(
                    mode="json"
                ),
                "last_heartbeat": self.last_heartbeat,
                "last_status": self.last_status,
                "org_id": self.org_id,
                "parameter_values": self.parameter_values,
                "provenance": self.provenance.model_dump(mode="json"),
                "status": [
                    status_record.to_presentable_dict() for status_record in self.status
                ],
                "duration": str(self.duration),
                "timeout": self.timeout,
            },
            indent=2,
        )


class LogRecord(pydantic.BaseModel):
    # If a log record is a partial log, this is a correlation ID for its parts
    # See documentation in the InvocationAwsDelegate in the method responsible for serving logs.
    partial_id: typing.Optional[str] = None
    log: str
    process: ExecutorContainer
    timestamp: datetime.datetime
