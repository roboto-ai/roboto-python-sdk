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
    """Kind of data source an invocation reads from. ``Dataset`` is the only kind."""

    Dataset = "Dataset"


class InvocationDataSource(pydantic.BaseModel):
    """Data source an invocation reads from: a dataset, or none.

    An invocation whose invoker named no data source carries the placeholder that ``unspecified`` returns.
    """

    data_source_type: InvocationDataSourceType
    """Kind of data source, always ``InvocationDataSourceType.Dataset``."""

    data_source_id: str
    """ID of the dataset the invocation reads from, or a placeholder when the data source is unspecified.

    The placeholder names no dataset.
    """

    @staticmethod
    def unspecified() -> InvocationDataSource:
        """Return the data source of an invocation that names none.

        Its type is ``InvocationDataSourceType.Dataset`` and its ID is a placeholder that matches no dataset. Check for
        it with ``is_unspecified`` rather than by comparing IDs.
        """

        return InvocationDataSource(
            data_source_type=InvocationDataSourceType.Dataset,
            data_source_id=_UNSPECIFIED_DATA_SOURCE,
        )

    def is_unspecified(self) -> bool:
        """Return whether this is the placeholder for an invocation that names no data source."""
        return self.data_source_id == _UNSPECIFIED_DATA_SOURCE


class UploadDestinationType(enum.Enum):
    """Kind of place an invocation's outputs are uploaded to."""

    Dataset = "Dataset"
    """Dataset to upload outputs to. The default."""

    Unknown = "Unknown"
    """Destination type this SDK version does not recognize.

    The SDK reads any type it has no member for as ``Unknown``, so a response from a newer version of Roboto still
    parses. Do not send it in an invocation request. Upgrade the SDK to read the actual type.
    """


class InvocationUploadDestination(pydantic.BaseModel):
    """Where Roboto uploads the files an action writes to its output directory."""

    destination_type: UploadDestinationType = UploadDestinationType.Dataset
    """Kind of destination. Defaults to a dataset."""

    destination_id: typing.Optional[str] = None
    """ID of the destination: for a dataset destination, the dataset's ID."""

    @pydantic.field_validator("destination_type", mode="before")
    @classmethod
    def pre_validate_destination_type(cls, value: typing.Any) -> typing.Any:
        """Read a destination type this SDK version does not recognize as an unknown type.

        Such a value becomes ``UploadDestinationType.Unknown``.
        """
        if isinstance(value, UploadDestinationType):
            return value

        if isinstance(value, str) and value not in UploadDestinationType.__members__:
            return UploadDestinationType.Unknown

        return value

    @classmethod
    def dataset(cls, dataset_id: str) -> InvocationUploadDestination:
        """Build a destination that uploads outputs to a dataset.

        Args:
            dataset_id: ID of the dataset to upload outputs to.
        """

        return cls(destination_type=UploadDestinationType.Dataset, destination_id=dataset_id)

    @property
    def is_dataset(self) -> bool:
        """Whether this is a dataset destination that names a dataset."""

        return self.destination_type is UploadDestinationType.Dataset and self.destination_id is not None

    @property
    def is_unknown(self) -> bool:
        """Whether the destination's type is one this SDK version does not recognize."""

        return self.destination_type is UploadDestinationType.Unknown


class DataSelector(pydantic.BaseModel):
    """Selector that chooses one kind of an invocation's inputs: its files, its sessions, or its topics.

    Carried in ``InvocationInput.sessions`` and ``InvocationInput.topics``.

    Set at least one of ``query``, ``ids``, and ``names``. The selector chooses every input that any of them matches.
    Constructing a selector that sets none of them raises ``pydantic.ValidationError``.
    """

    query: typing.Optional[str] = None
    """RoboQL query that matches the inputs to select."""

    ids: typing.Optional[list[str]] = None
    """IDs of the inputs to select.

    File IDs in a file selector, session IDs in a session selector, and topic IDs in a topic selector. Repeated IDs are
    dropped.
    """

    names: typing.Optional[list[str]] = None
    """Names of the inputs to select, such as topic names. Repeated names are dropped."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset that a file selector's ``paths`` are relative to.

    Every other field ignores it, and session and topic selectors ignore it entirely, with a warning. To limit a
    selection to one dataset, write the condition into ``query`` instead: ``dataset_id = "ds_12345"`` for files, or
    ``dataset.dataset_id = "ds_12345"`` for sessions and topics.
    """

    @pydantic.field_validator("ids", "names", mode="after")
    @classmethod
    def _dedupe(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        if value is None:
            return None
        return list(dict.fromkeys(value))

    @pydantic.model_validator(mode="after")
    def ensure_not_empty(self) -> DataSelector:
        """Reject a selector that sets none of ``query``, ``ids``, and ``names``."""
        if not any([self.query, self.ids, self.names]):
            raise ValueError("At least one selector field must be provided!")

        return self


class FileSelector(DataSelector):
    """Selector that chooses an invocation's file inputs, which can also select files by path within one dataset.

    Carried in ``InvocationInput.files``.

    A RoboQL ``query`` can select the same files as ``dataset_id`` and ``paths``, across any number of datasets:
    ``dataset_id = "ds_12345" AND path LIKE "%.mcap"``.

    Set at least one of ``query``, ``ids``, ``names``, and ``paths``. Constructing a file selector that sets none of
    them raises ``pydantic.ValidationError``.
    """

    paths: typing.Optional[list[str]] = None
    """Gitignore-style patterns for the files to select.

    The patterns are relative to ``dataset_id`` or, when it is unset, to the invocation's data source. A RoboQL
    ``query`` can express them instead, as ``path LIKE "<pattern>"``.
    """

    @pydantic.model_validator(mode="after")
    def ensure_not_empty(self) -> FileSelector:
        """Reject a selector that sets none of ``query``, ``ids``, ``names``, and ``paths``."""
        if not any([self.query, self.ids, self.names, self.paths]):
            raise ValueError("At least one file selector field must be provided!")

        return self


class InvocationInput(pydantic.BaseModel):
    """Inputs an invocation reads: files, sessions, and topics, each chosen by one or more selectors.

    A selector chooses inputs by RoboQL query, by ID, or by name; see ``DataSelector``. At least one of ``files``,
    ``sessions``, and ``topics`` must be set: constructing an input that sets none of them, or sets each to an empty
    list, raises ``pydantic.ValidationError``. An invocation that reads no inputs has no ``InvocationInput``.
    """

    files: typing.Optional[typing.Union[FileSelector, list[FileSelector]]] = None
    """Selectors for the files to read, as one selector or a list."""

    sessions: typing.Optional[typing.Union[DataSelector, list[DataSelector]]] = None
    """Selectors for the sessions to read, as one selector or a list."""

    topics: typing.Optional[typing.Union[DataSelector, list[DataSelector]]] = None
    """Selectors for the topics to read, as one selector or a list."""

    @pydantic.model_validator(mode="after")
    def ensure_not_empty(self) -> InvocationInput:
        """Reject an input that sets none of ``files``, ``sessions``, and ``topics``, or sets each to an empty list."""
        if not any(
            [
                self.files,
                self.topics,
                self.sessions,
            ]
        ):
            raise ValueError("At least one invocation input selector must be provided!")

        return self

    @classmethod
    def from_dataset_file_paths(cls, dataset_id: str, file_paths: list[str]) -> InvocationInput:
        """Build an input that selects files in a dataset by path.

        Args:
            dataset_id: ID of the dataset to select files from.
            file_paths: Gitignore-style patterns for the files to select, relative to the dataset.
        """
        return cls(files=FileSelector(dataset_id=dataset_id, paths=file_paths))

    @classmethod
    def from_session_id(cls, session_id: str) -> InvocationInput:
        """Build an input that selects one session by ID.

        Args:
            session_id: ID of the session to select.
        """
        return cls(sessions=DataSelector(ids=[session_id]))

    @classmethod
    def file_query(cls, roboql_query: str) -> InvocationInput:
        """Build an input that selects the files a RoboQL query matches.

        Args:
            roboql_query: RoboQL query that matches the files to select.
        """
        return cls(files=FileSelector(query=roboql_query))

    @classmethod
    def session_query(cls, roboql_query: str) -> InvocationInput:
        """Build an input that selects the sessions a RoboQL query matches.

        Args:
            roboql_query: RoboQL query that matches the sessions to select.
        """
        return cls(sessions=DataSelector(query=roboql_query))

    @classmethod
    def topic_query(cls, roboql_query: str) -> InvocationInput:
        """Build an input that selects the topics a RoboQL query matches.

        Args:
            roboql_query: RoboQL query that matches the topics to select.
        """
        return cls(topics=DataSelector(query=roboql_query))

    @property
    def safe_files(self) -> list[FileSelector]:
        """File selectors as a list, empty when ``files`` is unset."""
        if self.files is None:
            return []

        return self.files if isinstance(self.files, list) else [self.files]

    @property
    def file_paths(self) -> list[str]:
        """Path patterns of every file selector, combined without repeats, in no particular order."""
        res: set[str] = set()

        for selector in self.safe_files:
            paths: list[str] = selector.paths or []
            res.update(paths)

        return list(res)

    @property
    def safe_sessions(self) -> list[DataSelector]:
        """Session selectors as a list, empty when ``sessions`` is unset."""
        if self.sessions is None:
            return []

        return self.sessions if isinstance(self.sessions, list) else [self.sessions]

    @property
    def safe_topics(self) -> list[DataSelector]:
        """Topic selectors as a list, empty when ``topics`` is unset."""
        if self.topics is None:
            return []

        return self.topics if isinstance(self.topics, list) else [self.topics]


class ActionProvenance(pydantic.BaseModel):
    """Action an invocation ran, identified by its name, its owning organization, and its version's digest.

    Carried in ``InvocationProvenance.action``.

    ``name`` and ``org_id`` are both empty strings when Roboto cannot name the action, such as when the invocation
    ran code that is not a saved action.
    """

    name: str
    """Name of the action, unique within the organization that owns it."""

    org_id: str
    """ID of the organization that owns the action.

    For an Action Hub action, this differs from the organization the invocation ran in.
    """

    digest: typing.Optional[str] = None
    """Digest of the action version the invocation ran, or ``None`` if Roboto recorded none."""


class ExecutableProvenance(pydantic.BaseModel):
    """Container image an invocation ran.

    Carried in ``InvocationProvenance.executable``.
    """

    container_image_uri: typing.Optional[str] = None
    """URI of the action's container image."""

    container_image_digest: typing.Optional[str] = None
    """Digest of the container image Roboto pulled to run the invocation, or ``None`` if it recorded none."""


class InvocationSource(enum.Enum):
    """How an invocation was started: by a user, or by a trigger."""

    Trigger = "Trigger"
    Manual = "Manual"


class SourceProvenance(pydantic.BaseModel):
    """User or trigger that started an invocation.

    Carried in ``InvocationProvenance.source``.
    """

    source_type: InvocationSource
    """Whether a user or a trigger started the invocation."""

    source_id: str
    """ID of the trigger or user that started the invocation.

    It is a trigger ID when ``source_type`` is ``InvocationSource.Trigger``, and a user ID when it is
    ``InvocationSource.Manual``.
    """


class InvocationProvenance(pydantic.BaseModel):
    """What an invocation ran and what started it.

    Carried in ``InvocationRecord.provenance``.
    """

    action: ActionProvenance
    """Action the invocation ran."""

    executable: ExecutableProvenance
    """Container image the invocation ran."""

    source: SourceProvenance
    """User or trigger that started the invocation."""


class InvocationStatus(int, enum.Enum):
    """Status of an invocation.

    An invocation moves through the statuses from ``Queued`` to ``Completed`` in order of value, and may skip some.
    ``Cancelled``, ``Failed``, and ``Deadly`` end it outside that order. Their values are higher than ``Completed``'s,
    so comparing values, such as ``status > InvocationStatus.Processing``, also matches them.
    """

    Queued = 0
    """The invocation is waiting for Roboto to start it."""

    Scheduled = 1
    """Roboto is provisioning compute to run it."""

    Downloading = 2
    """Roboto is preparing the execution environment and downloading inputs, if the action needs them."""

    Processing = 3
    """The action's container is running."""

    Uploading = 4
    """Roboto is uploading the files the action wrote to its output directory, if any."""

    Completed = 5
    """The invocation finished successfully."""

    Cancelled = 997
    """The invocation was cancelled before it finished."""

    Failed = 998
    """The invocation ended in failure. Roboto can queue a failed invocation again, to retry it."""

    Deadly = 999
    """The invocation failed and will not be retried."""

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def from_value(v: typing.Union[int, str]) -> "InvocationStatus":
        """Return the status whose number is ``v``, or whose name is ``v`` in any case.

        Args:
            v: A status number such as ``998``, or a status name such as ``"Failed"`` or ``"failed"``.

        Raises:
            ValueError: ``v`` is neither a status number nor a status name.
        """
        for status in InvocationStatus:
            if v == status.value or (isinstance(v, str) and v.lower() == status.name.lower()):
                return status

        raise ValueError(f"Illegal Invocation status {v}")

    def can_transition_to(self, other: "InvocationStatus") -> bool:
        """Return whether an invocation in this status may move to ``other``.

        - Any status may stay where it is.
        - ``Completed``, ``Cancelled``, and ``Deadly`` move nowhere else.
        - ``Failed`` moves only to ``Queued``, to retry, or to ``Deadly``.
        - Any other status moves to ``Cancelled``, to ``Failed``, or to a status with a higher value, except that
          only ``Queued`` moves to ``Deadly``.

        Args:
            other: Status to move to.
        """
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
        """Return whether this status is ``Downloading``, ``Processing``, or ``Uploading``."""
        return self in {
            InvocationStatus.Downloading,
            InvocationStatus.Processing,
            InvocationStatus.Uploading,
        }

    def is_terminal(self) -> bool:
        """Return whether this status ends the invocation: ``Completed``, ``Cancelled``, ``Failed``, or ``Deadly``.

        A ``Failed`` invocation can still be queued again, to retry it.
        """
        return self in {
            InvocationStatus.Completed,
            InvocationStatus.Cancelled,
            InvocationStatus.Failed,
            InvocationStatus.Deadly,
        }

    def next(self) -> typing.Optional["InvocationStatus"]:
        """Return the next status from ``Queued`` to ``Completed``, or ``None`` if this status is terminal."""
        if self.is_terminal():
            return None
        return InvocationStatus(self.value + 1)


class InvocationStatusRecord(pydantic.BaseModel):
    """Entry in an invocation's status history: a status, and when the invocation entered it.

    Carried in ``InvocationRecord.status``.
    """

    status: InvocationStatus
    """Status the invocation entered."""

    detail: typing.Optional[str] = None
    """Human-readable explanation of the status, such as why the invocation failed, or ``None`` if there is none."""

    timestamp: datetime.datetime
    """Time the invocation entered the status, in UTC."""

    def to_presentable_dict(self) -> dict[str, typing.Optional[str]]:
        """Return the record as a dictionary for display, with the status by name and the time in ISO 8601 format.

        ``detail`` is ``None`` when the record has none.
        """
        return {
            "status": str(self.status),
            "timestamp": self.timestamp.isoformat(),
            "detail": self.detail,
        }


class LogsLocation(pydantic.BaseModel):
    """S3 location where Roboto stores an invocation's log files.

    Roboto records it with :py:meth:`~roboto.domain.actions.Invocation.set_logs_location`. To read the logs, use
    :py:meth:`~roboto.domain.actions.Invocation.get_logs`.
    """

    bucket: str
    """Name of the S3 bucket that holds the logs."""

    prefix: str
    """Key prefix under which the logs are stored."""


class InvocationRecord(pydantic.BaseModel):
    """Data record of an invocation, as the Roboto API returns it.

    An invocation is one run of an action, started by a user or by a trigger.
    :py:class:`~roboto.domain.actions.Invocation` wraps this record with methods that act on the invocation, and
    exposes it as :py:attr:`~roboto.domain.actions.Invocation.record`.
    """

    # __str__ lists every field; update it when adding or removing one.
    created: datetime.datetime
    """Time the invocation was created, in UTC."""

    data_source: InvocationDataSource
    """Dataset the invocation reads from, or an unspecified data source when its invoker named none."""

    input_data: list[str]
    """Deprecated. Paths within ``data_source`` that the invoker selected.

    Use ``rich_input_data`` instead. Set only when the request selected nothing but such paths, and empty otherwise.
    """

    rich_input_data: typing.Optional[InvocationInput] = None
    """Inputs as the invoker requested them, or ``None`` if it requested none.

    A file selector with ``paths`` and no ``dataset_id`` is relative to ``data_source``.
    :py:attr:`~roboto.domain.actions.Invocation.input_data` returns a copy with that ``dataset_id`` filled in.
    """

    resolved_input_data: typing.Optional[InvocationInput] = None
    """Inputs the request resolved to, each named by its file, session, or topic ID.

    The inputs may span any number of datasets. ``None`` when the invocation records no resolved inputs.
    """

    upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Where Roboto uploads the files the action writes to its output directory.

    ``None`` if the invoker named no destination. Without one, Roboto uploads them to the dataset the inputs come
    from, when they all come from one.
    """

    invocation_id: str
    """Unique ID of the invocation, beginning with ``iv_``."""

    idempotency_id: typing.Optional[str] = None
    """ID the invoker gave so that the invocation runs at most once.

    Another request with the same ID in the same organization creates no second invocation. ``None`` if the invoker
    gave none.
    """

    compute_requirements: ComputeRequirements
    """CPU, memory, and storage the invocation runs with: the action's, with any overrides the invoker gave."""

    container_parameters: ContainerParameters
    """Command, entry point, environment variables, and working directory the invocation's container starts with.

    They are the action's, with any overrides the invoker gave.
    """

    last_heartbeat: typing.Optional[datetime.datetime] = None
    """Time the running invocation last reported that it is still alive, or ``None`` if it never has."""

    last_status: InvocationStatus
    """Latest status of the invocation."""

    org_id: str
    """ID of the organization that owns the invocation."""

    parameter_values: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the action's parameters for this invocation, keyed by parameter name.

    Parameters the invoker left out have their defaults.
    """

    provenance: InvocationProvenance
    """Action and container image the invocation ran, and the user or trigger that started it."""

    status: list[InvocationStatusRecord] = pydantic.Field(default_factory=list)
    """Statuses the invocation has entered, each with the time it entered it."""

    duration: datetime.timedelta = pydantic.Field(default_factory=datetime.timedelta)
    """Time the invocation spent running, summed over its attempts if it was retried. Zero until an attempt ends."""

    timeout: int
    """Maximum time, in minutes, the invocation may run."""

    def __str__(self) -> str:
        return json.dumps(
            {
                "created": self.created.isoformat(),
                "data_source": self.data_source.model_dump(mode="json"),
                "input_data": self.input_data,
                "rich_input_data": (self.rich_input_data.model_dump(mode="json") if self.rich_input_data else None),
                "resolved_input_data": (
                    self.resolved_input_data.model_dump(mode="json") if self.resolved_input_data else None
                ),
                "upload_destination": (
                    self.upload_destination.model_dump(mode="json") if self.upload_destination else None
                ),
                "invocation_id": self.invocation_id,
                "idempotency_id": self.idempotency_id,
                "compute_requirements": self.compute_requirements.model_dump(mode="json"),
                "container_parameters": self.container_parameters.model_dump(mode="json"),
                "last_heartbeat": self.last_heartbeat,
                "last_status": self.last_status,
                "org_id": self.org_id,
                "parameter_values": self.parameter_values,
                "provenance": self.provenance.model_dump(mode="json"),
                "status": [status_record.to_presentable_dict() for status_record in self.status],
                "duration": str(self.duration),
                "timeout": self.timeout,
            },
            indent=2,
        )


class LogRecord(pydantic.BaseModel):
    """Line of output that one of an invocation's containers wrote to STDOUT or STDERR.

    :py:meth:`~roboto.domain.actions.Invocation.get_logs` yields these.
    """

    partial_id: typing.Optional[str] = None
    """ID shared by the records that one log line too long for a single record was split into.

    ``None`` on a line that arrived whole. Roboto does not rejoin the parts.
    """

    log: str
    """Text of the log line."""

    process: ExecutorContainer
    """Container that wrote the line: the setup container, the action's own container, or the output handler."""

    timestamp: datetime.datetime
    """Time the container wrote the line."""
