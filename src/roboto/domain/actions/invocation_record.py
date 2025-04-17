# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

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

_UNSPECIFIED_DATA_SOURCE: str = "__UNSPECIFIED_DATA_SOURCE__"


class InvocationDataSourceType(enum.Enum):
    """Source of data for an action's input binding"""

    Dataset = "Dataset"


class InvocationDataSource(pydantic.BaseModel):
    """Abstracted data source that can be provided to an invocation"""

    data_source_type: InvocationDataSourceType
    # The "type" determines the meaning of "id":
    #   - if type is "Dataset," id is a dataset_id
    data_source_id: str

    @staticmethod
    def unspecified() -> InvocationDataSource:
        """Returns a special value indicating that no invocation source is specified."""

        return InvocationDataSource(
            data_source_type=InvocationDataSourceType.Dataset,
            data_source_id=_UNSPECIFIED_DATA_SOURCE,
        )

    def is_unspecified(self) -> bool:
        return self.data_source_id == _UNSPECIFIED_DATA_SOURCE


class DataSelector(pydantic.BaseModel):
    """Selector for inputs (e.g. files) to an action invocation."""

    query: typing.Optional[str] = None
    """RoboQL query representing the desired inputs."""

    ids: typing.Optional[list[str]] = None
    """Specific input IDs (e.g. a dataset ID)."""

    names: typing.Optional[list[str]] = None
    """Specific input names (e.g. topic names)."""

    dataset_id: typing.Optional[str] = None
    """Dataset ID, needed for backward compatibility purposes.
    Prefer RoboQL: dataset_id = <the ID in double quotes>"""

    @pydantic.model_validator(mode="after")
    def ensure_not_empty(self) -> DataSelector:
        if not any([self.query, self.ids, self.names]):
            raise ValueError("At least one selector field must be provided!")

        return self


class FileSelector(DataSelector):
    """Selector for file inputs to an action invocation.

    This selector type exists for backward compatibility purposes. We encourage you
    to use the `query` field to scope your input query to any dataset and/or file paths.
    """

    paths: typing.Optional[list[str]] = None
    """File paths or patterns. Prefer RoboQL: path LIKE <path pattern in double quotes>"""

    @pydantic.model_validator(mode="after")
    def ensure_not_empty(self) -> FileSelector:
        if not any([self.query, self.ids, self.names, self.paths]):
            raise ValueError("At least one file selector field must be provided!")

        return self


class InvocationInput(pydantic.BaseModel):
    """Input specification for an action invocation.

    An invocation may require no inputs at all, or some combination of Roboto files, topics,
    events, etc. Those are specified using selectors, which tell the invocation how to locate
    inputs. Selector choices include RoboQL queries (for maximum flexibility), as well as unique
    IDs or friendly names.

    Note: support for certain input types is a work in progress, and will be offered in future Roboto
    platform releases.

    At least one data selector must be provided in order to construct a valid `InvocationInput`
    instance.
    """

    files: typing.Optional[typing.Union[FileSelector, list[FileSelector]]] = None
    """File selectors."""

    topics: typing.Optional[typing.Union[DataSelector, list[DataSelector]]] = None
    """Topic selectors."""

    @pydantic.model_validator(mode="after")
    def ensure_not_empty(self) -> InvocationInput:
        if not any(
            [
                self.files,
                self.topics,
            ]
        ):
            raise ValueError("At least one input field must be provided!")

        return self

    @classmethod
    def from_dataset_file_paths(
        cls, dataset_id: str, file_paths: list[str]
    ) -> InvocationInput:
        return cls(files=FileSelector(dataset_id=dataset_id, paths=file_paths))

    @property
    def safe_files(self) -> list[FileSelector]:
        match self.files:
            case None:
                return []
            case FileSelector():
                return [self.files]
            case _:
                return self.files

    @property
    def file_paths(self) -> list[str]:
        res: set[str] = set()

        for selector in self.safe_files:
            paths: list[str] = selector.paths or []
            res.update(paths)

        return list(res)

    @property
    def safe_topics(self) -> list[DataSelector]:
        match self.topics:
            case None:
                return []
            case DataSelector():
                return [self.topics]
            case _:
                return self.topics


class ActionProvenance(pydantic.BaseModel):
    """Provenance information for an action"""

    name: str
    org_id: str
    # 2023-09-11 (GM): Optional for backwards compatibility; new invocations will always have a digest
    digest: typing.Optional[str] = None


class ExecutableProvenance(pydantic.BaseModel):
    """Provenance information for an action executable"""

    # Optional for backwards compatibility
    container_image_uri: typing.Optional[str] = None
    container_image_digest: typing.Optional[str] = None


class InvocationSource(enum.Enum):
    """Method by which an invocation was run"""

    Trigger = "Trigger"
    Manual = "Manual"


class SourceProvenance(pydantic.BaseModel):
    """Provenance information for an invocation source"""

    source_type: InvocationSource
    # The “type” determines the meaning of “id:”
    #   - if type is “Trigger,” id is a TriggerId;
    #   - if type is “Manual,” id is a UserId.
    source_id: str


class InvocationProvenance(pydantic.BaseModel):
    """Provenance information for an invocation"""

    action: ActionProvenance
    """The Action that was invoked."""

    executable: ExecutableProvenance
    """The underlying executable (e.g., Docker image) that was run."""

    source: SourceProvenance
    """The source of the invocation."""


class InvocationStatus(int, enum.Enum):
    """Invocation status enum"""

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
    """
    A wire-transmissible representation of an invocation status.
    """

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
    """
    Invocation log storage location
    """

    bucket: str
    prefix: str


class InvocationRecord(pydantic.BaseModel):
    """
    A wire-transmissible representation of an invocation.
    """

    # When adding or removing fields, make sure to update __str__
    created: datetime.datetime  # Persisted as ISO 8601 string in UTC
    data_source: InvocationDataSource
    input_data: list[str]
    rich_input_data: typing.Optional[InvocationInput] = None
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
                "rich_input_data": (
                    self.rich_input_data.model_dump(mode="json")
                    if self.rich_input_data
                    else None
                ),
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
    """
    A wire-transmissible representation of a log record.
    """

    # If a log record is a partial log, this is a correlation ID for its parts
    # See documentation in the InvocationAwsDelegate in the method responsible for serving logs.
    partial_id: typing.Optional[str] = None
    log: str
    process: ExecutorContainer
    timestamp: datetime.datetime
